"""전장그룹 업무관리 — 화면(라우트)과 실행 진입점.

각자 PC에서 이 프로그램을 실행하면 내 PC 안에서만 접속되는 화면(127.0.0.1)이 열리고,
데이터는 공유폴더의 이벤트 로그(store.py)로 주고받는다.
"""

import argparse
import configparser
import getpass
import json
import os
import shutil
import socket
import sys
import threading
import time
import uuid
import webbrowser
from datetime import date
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for

from app import rules
from app.export import build_workbook, owner_cell, target_cell
from app.store import DATE_FIELDS, TASK_FIELDS, Store, ensure_dir_writable, writer_file_name

# PyInstaller exe로 묶였을 때는 임시폴더(_MEIPASS)에 템플릿이 풀린다
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
# 설정 파일은 exe(또는 프로젝트) 옆에 둔다 → PC마다 따로
HOME_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else BUNDLE_DIR

SOURCES = ["구두", "업무전달방", "회의", "메일", "자체"]
EDIT_FIELDS = [f for f in TASK_FIELDS if f != "deleted"]
REQUIRED_ON_CREATE = ["project", "created_date", "target", "content", "owner"]
VIRTUAL_OWNER = "전장"  # 팀 공통 업무용 가상 담당자 (관리자만 지정)


def create_app(data_dir: Path, local_path: Path, today=date.today) -> Flask:
    """today를 주입받아 테스트에서 날짜를 고정할 수 있게 함."""
    app = Flask(
        __name__,
        template_folder=str(BUNDLE_DIR / "app" / "templates"),
        static_folder=str(BUNDLE_DIR / "app" / "static"),
    )
    app.secret_key = "jeonjang-local-only"  # 내 PC 안에서만 쓰는 화면 메시지용
    local = _load_local(local_path)
    store = Store(data_dir)

    def bind_writer() -> None:
        store.writer_name = (
            writer_file_name(local["me"], local["install_id"]) if local.get("me") else None
        )

    bind_writer()
    store.refresh()

    def me() -> str:
        return local.get("me", "")

    def is_admin() -> bool:
        return bool(store.users.get(me(), {}).get("is_admin"))

    def login_users() -> list[dict]:
        return [u for u in store.users.values() if u.get("can_login", True) and u.get("active", True)]

    def owner_choices() -> list[str]:
        names = [u["name"] for u in login_users()]
        if is_admin() and VIRTUAL_OWNER in store.users:
            names.append(VIRTUAL_OWNER)
        return names

    def get_task(task_id: str) -> dict:
        task = store.tasks.get(task_id)
        if task is None or task["deleted"]:
            abort(404)
        return task

    def require_edit(task: dict) -> None:
        if not rules.can_edit(task, me(), is_admin()):
            abort(403)

    def save_or_flash(action) -> bool:
        """공유폴더 쓰기 실패를 화면에 알리고 False. (조용히 잃지 않음)"""
        try:
            action()
            return True
        except OSError as e:
            flash(f"저장 실패: 공유폴더에 쓸 수 없습니다 ({e}). 네트워크 연결을 확인하세요.", "error")
            return False

    @app.before_request
    def before() -> Response | None:
        # 다른 웹사이트가 내 브라우저를 통해 이 화면으로 몰래 저장 요청하는 것(CSRF) 차단
        if request.method == "POST" and request.origin and request.origin != request.host_url.rstrip("/"):
            abort(403)
        store.refresh()
        if not me() and request.endpoint not in ("setup", "static", "api_rev"):
            return redirect(url_for("setup"))
        return None

    @app.context_processor
    def inject() -> dict:
        t = today()
        return {
            "me": me(),
            "is_admin": is_admin(),
            "today": t,
            "status_of": lambda task: rules.status_of(task, t),
            "days_left": lambda task: rules.days_left(task, t),
            "issues_of": lambda task: rules.input_issues(task, t),
            "can_edit": lambda task: rules.can_edit(task, me(), is_admin()),
            "target_cell": target_cell,
            "owner_cell": owner_cell,
            "field_names": TASK_FIELDS,
            "store_errors": store.errors,
            "rev": store.rev,  # 페이지를 그린 시점의 기준값 (자동 새로고침 비교용)
        }

    # ---------- 사용자 선택 ----------

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if request.method == "POST":
            name = request.form.get("name", "")
            if name not in {u["name"] for u in login_users()}:
                flash("목록에서 이름을 선택하세요.", "error")
            else:
                local["me"] = name
                _save_local(local_path, local)
                bind_writer()
                return redirect(url_for("task_list"))
        return render_template("setup.html", users=login_users())

    # ---------- 업무 목록 ----------

    def filtered_tasks(args) -> list[dict]:
        t = today()
        owner, project, status = args.get("owner"), args.get("project"), args.get("status")
        include_collab = args.get("collab") == "1"
        date_from, date_to = args.get("from"), args.get("to")
        keyword = (args.get("q") or "").strip().lower()
        result = []
        for task in store.tasks.values():
            if task["deleted"]:
                continue
            if owner and not (
                task["owner"] == owner or (include_collab and owner in task["collaborators"])
            ):
                continue
            if project and task["project"] != project:
                continue
            st = rules.status_of(task, t)
            if status == "미완료" and st == rules.DONE:
                continue
            if status in (rules.DONE, rules.OVERDUE, rules.DUE_SOON) and st != status:
                continue
            if date_from and (not task["target"] or task["target"] < date_from):
                continue
            if date_to and (not task["target"] or task["target"] > date_to):
                continue
            if keyword:
                text = (task["content"] or "") + " ".join(c["text"] for c in task["comments"])
                if keyword not in text.lower():
                    continue
            result.append(task)
        return sorted(result, key=rules.sort_key)

    def projects() -> list[str]:
        return sorted({t["project"] for t in store.tasks.values() if t["project"]})

    @app.route("/")
    def task_list():
        return render_template(
            "list.html",
            tasks=filtered_tasks(request.args),
            projects=projects(),
            owners=[u["name"] for u in store.users.values()],
            args=request.args,
        )

    @app.route("/export.xlsx")
    def export():
        data = build_workbook(filtered_tasks(request.args), today())
        name = f"전장_업무전달리스트_{today().isoformat()}.xlsx"
        return Response(
            data,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    # ---------- 등록·수정 ----------

    def read_form() -> tuple[dict, list[str]]:
        """폼 값 → 필드 dict. 날짜 형식 오류는 errors로."""
        fields, errors = {}, []
        for f in EDIT_FIELDS:
            if f == "collaborators":
                fields[f] = sorted(set(request.form.getlist(f)))
                continue
            value = request.form.get(f, "").strip()
            if f == "content":
                value = value.replace("\r\n", "\n")  # 줄바꿈·★·▶ 그대로 보존
            if f in DATE_FIELDS and value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    errors.append(f"{TASK_FIELDS[f]} 날짜 형식 오류: {value}")
            fields[f] = value or None
        if fields["owner"] in fields["collaborators"]:
            fields["collaborators"].remove(fields["owner"])
        if fields["owner"] == VIRTUAL_OWNER and not is_admin():
            errors.append("'전장' 공통 업무는 관리자만 지정할 수 있습니다.")
        return fields, errors

    @app.route("/task/new", methods=["GET", "POST"])
    def task_new():
        if request.method == "POST":
            fields, errors = read_form()
            errors += [f"{TASK_FIELDS[f]}은(는) 필수입니다." for f in REQUIRED_ON_CREATE if not fields[f]]
            if not errors:
                fields = {k: v for k, v in fields.items() if v}  # 빈 값은 기록 안 함
                result = {}
                if save_or_flash(lambda: result.update(id=store.create_task(me(), fields))):
                    flash("등록했습니다.", "ok")
                    return redirect(url_for("task_detail", task_id=result["id"]))
            for e in errors:
                flash(e, "error")
            task = {**fields, "id": None}
        else:
            task = {f: None for f in EDIT_FIELDS} | {
                "id": None,
                "collaborators": [],
                "created_date": today().isoformat(),
                "owner": me(),
            }
        return render_template("form.html", task=task, orig=None, **form_context())

    def form_context() -> dict:
        return {
            "owners": owner_choices(),
            "collab_choices": [u["name"] for u in login_users()],
            "projects": projects(),
            "sources": SOURCES,
            "requesters": [u["name"] for u in login_users()],
        }

    @app.route("/task/<task_id>/edit", methods=["GET", "POST"])
    def task_edit(task_id: str):
        task = get_task(task_id)
        require_edit(task)
        if request.method == "POST":
            fields, errors = read_form()
            orig = json.loads(request.form["orig"])
            if not fields["content"] or not fields["owner"]:
                errors.append("업무내용과 주담당은 비울 수 없습니다.")
            changes, conflicts = merge_changes(task, orig, fields)
            if not errors:
                if save_or_flash(lambda: store.update_task(me(), task_id, changes)):
                    for f in conflicts:
                        flash(
                            f"[{TASK_FIELDS[f]}] 다른 사람이 먼저 수정해 내 값은 저장하지 않았습니다. "
                            f"현재값: {task[f] or '(빈칸)'}",
                            "error",
                        )
                    if changes:
                        flash("저장했습니다.", "ok")
                    return redirect(url_for("task_detail", task_id=task_id))
            for e in errors:
                flash(e, "error")
            return render_template("form.html", task=task | fields, orig=orig, **form_context())
        orig = {f: task[f] for f in EDIT_FIELDS}
        return render_template("form.html", task=task, orig=orig, **form_context())

    @app.route("/task/<task_id>")
    def task_detail(task_id: str):
        return render_template("detail.html", task=get_task(task_id))

    @app.route("/task/<task_id>/comment", methods=["POST"])
    def task_comment(task_id: str):
        task = get_task(task_id)
        require_edit(task)
        text = request.form.get("text", "").strip().replace("\r\n", "\n")
        if text and save_or_flash(lambda: store.add_comment(me(), task_id, text)):
            flash("진행내용을 추가했습니다.", "ok")
        return redirect(url_for("task_detail", task_id=task_id))

    @app.route("/task/<task_id>/delete", methods=["POST"])
    def task_delete(task_id: str):
        get_task(task_id)
        if not is_admin():
            abort(403)
        # 소프트 삭제: 기록은 남기고 목록에서만 숨김
        if save_or_flash(lambda: store.update_task(me(), task_id, {"deleted": True})):
            flash("삭제했습니다. (이력은 보존됨)", "ok")
        return redirect(url_for("task_list"))

    @app.route("/bulk_done", methods=["POST"])
    def bulk_done():
        done = request.form.get("done_date") or today().isoformat()
        count = 0
        for task_id in request.form.getlist("ids"):
            task = store.tasks.get(task_id)
            if task and not task["done_date"] and rules.can_edit(task, me(), is_admin()):
                if not save_or_flash(lambda: store.update_task(me(), task_id, {"done_date": done})):
                    break
                count += 1
        flash(f"{count}건 완료 처리했습니다. (완료일 {done})", "ok")
        return redirect(request.referrer or url_for("task_list"))

    # ---------- 현황·점검 ----------

    @app.route("/dashboard")
    def dashboard():
        t = today()
        live = [x for x in store.tasks.values() if not x["deleted"]]
        rows = []
        for name in store.users:
            mine = [x for x in live if x["owner"] == name]
            open_ = [x for x in mine if x["done_date"] is None]
            rows.append({
                "name": name,
                "total": len(mine),
                "open": len(open_),
                "done": len(mine) - len(open_),
                "overdue": sum(rules.status_of(x, t) == rules.OVERDUE for x in mine),
                "week": sum(_within(rules.days_left(x, t), 0, 7) for x in open_),
                "collab": sum(
                    name in x["collaborators"] and x["done_date"] is None for x in live
                ),
            })
        return render_template("dashboard.html", rows=rows)

    @app.route("/checks")
    def checks():
        t = today()
        flagged = [
            (task, rules.input_issues(task, t))
            for task in sorted(store.tasks.values(), key=rules.sort_key)
            if not task["deleted"]
        ]
        flagged = [(task, issues) for task, issues in flagged if issues]
        return render_template("checks.html", flagged=flagged)

    # ---------- 관리자 ----------

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        if not is_admin():
            abort(403)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if name:
                fields = {
                    "is_admin": request.form.get("is_admin") == "1",
                    "active": request.form.get("active") == "1",
                    "can_login": request.form.get("can_login") == "1",
                }
                if save_or_flash(lambda: store.set_user(me(), name, **fields)):
                    flash(f"{name} 저장했습니다.", "ok")
            return redirect(url_for("admin"))
        return render_template("admin.html", users=list(store.users.values()))

    @app.route("/api/rev")
    def api_rev():
        """브라우저가 5초마다 확인 → 값이 바뀌면 화면 새로고침."""
        return {"rev": store.rev}

    return app


def merge_changes(task: dict, orig: dict, new: dict) -> tuple[dict, list[str]]:
    """필드 단위 낙관적 잠금.

    - 내가 바꾸지 않은 필드: 무시 (다른 사람 수정을 덮어쓰지 않음)
    - 내가 바꿨는데, 화면을 연 뒤 다른 사람도 바꾼 필드: 충돌 → 저장 안 함
    - 그 외: 저장
    """
    changes, conflicts = {}, []
    for field, value in new.items():
        if value == orig.get(field):
            continue
        if task.get(field) != orig.get(field):
            conflicts.append(field)
        else:
            changes[field] = value
    return changes, conflicts


# ---------- 설정·실행 ----------


def _load_local(path: Path) -> dict:
    """PC별 정보(내 이름, 설치ID). 없으면 설치ID를 새로 만든다."""
    try:
        local = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        local = {}
    if "install_id" not in local:
        local["install_id"] = uuid.uuid4().hex[:8]
        _save_local(path, local)
    return local


def _save_local(path: Path, local: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")


def _within(value: int | None, low: int, high: int) -> bool:
    return value is not None and low <= value <= high


def load_config(path: Path) -> configparser.SectionProxy:
    config = configparser.ConfigParser()
    if not config.read(path, encoding="utf-8-sig"):  # 메모장 저장(BOM) 대응
        raise SystemExit(f"설정 파일이 없습니다: {path}\nconfig.example.ini를 복사해 config.ini로 만드세요.")
    return config["settings"]


def backup_loop(events_dir: Path, backup_dir: Path) -> None:
    """하루 1번 events 폴더를 날짜 폴더로 복사. 먼저 켜진 PC가 수행."""
    while True:
        dest = backup_dir / date.today().isoformat()
        if events_dir.exists() and not dest.exists():
            try:
                shutil.copytree(events_dir, dest, dirs_exist_ok=True)
                print(f"[백업] {dest}")
            except OSError as e:
                print(f"[백업 실패] {e}")
        time.sleep(3600)


def local_file(data_dir: Path, port: int) -> Path:
    """PC별 정보 파일 위치.

    회사 PC는 C 드라이브 저장이 막혀 있어(문서중앙화) exe 옆이 아니라 데이터 폴더에 둔다.
    PC이름_사용자_포트 로 구분 → 같은 폴더를 여럿이 써도 겹치지 않음.
    """
    pc = os.environ.get("COMPUTERNAME") or socket.gethostname()
    return data_dir / "local" / f"{pc}_{getpass.getuser()}_{port}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="전장 업무관리")
    parser.add_argument("--import", dest="seed", type=Path, help="기존 업무 이관 (관리자 1회)")
    parser.add_argument("--port", type=int, help="화면 포트 (한 PC에서 2개 띄워 테스트할 때)")
    args = parser.parse_args()

    cfg = load_config(HOME_DIR / "config.ini")
    data_dir = Path(cfg["data_dir"])
    port = args.port or cfg.getint("port", 8765)

    # 관리자 1회: 기존 업무 이관 (데이터이관.bat → exe --import seed_tasks.json)
    if args.seed:
        from scripts.import_seed import import_seed

        count = import_seed(args.seed, data_dir)
        input(f"{count}건 이관 완료 → {data_dir / 'events'}\nEnter를 누르면 종료합니다.")
        return
    url = f"http://127.0.0.1:{port}/"

    # 이미 실행 중이면 브라우저만 열고 종료 (PC당 1개 실행 → 내 파일 작성자도 1개)
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            webbrowser.open(url)
            return

    try:
        ensure_dir_writable(data_dir / "events")
    except OSError as e:
        input(f"[오류] 데이터 폴더에 저장할 수 없습니다: {data_dir}\n{e}\n"
              "config.ini의 data_dir이 저장 가능한 곳(예: U 드라이브)인지 확인하세요.\n"
              "Enter를 누르면 종료합니다.")
        return

    if cfg.get("backup_dir"):
        threading.Thread(
            target=backup_loop, args=(data_dir / "events", Path(cfg["backup_dir"])), daemon=True
        ).start()

    from waitress import serve

    app = create_app(data_dir, local_file(data_dir, port))
    print("=" * 50)
    print(" 전장 업무관리 실행 중:", url)
    print(" 데이터 폴더:", data_dir)
    print(" 이 창을 닫으면 프로그램이 종료됩니다.")
    print("=" * 50)
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    serve(app, host="127.0.0.1", port=port)  # 내 PC 안에서만 접속 (방화벽 설정 불필요)


if __name__ == "__main__":
    main()
