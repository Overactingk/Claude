"""이벤트 로그 저장소 (서버 없이 공유폴더만으로 동시 사용).

원리 — 단일 작성자(single-writer):
- 공유폴더의 events/ 아래에 설치(PC)마다 파일 1개: <사용자>_<설치ID>.jsonl
- 각 프로그램은 '자기 파일'에만 한 줄씩 추가(append)한다 → 파일 잠금 충돌이 없음
- 읽을 때는 모든 파일을 모아 시간순으로 재생(replay)해서 현재 상태를 만든다
  (CAN에서 메시지 ID마다 송신 ECU가 1개인 것과 같은 원리)

이벤트 한 줄 예시:
{"id": "...", "ts": "2026-10-02T09:12:33.123456", "by": "이가람C",
 "type": "task_set", "task": "ab12...", "fields": {"target": "2026-10-10"}}
"""

import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

# 업무 필드 목록 (화면·엑셀·이력에서 공통 사용)
TASK_FIELDS = {
    "project": "프로젝트 차종",
    "created_date": "작성날짜",
    "target": "목표",
    "done_date": "완료",
    "content": "업무내용",
    "owner": "주담당",
    "collaborators": "협업자",
    "file_path": "파일경로",
    "note": "비고",
    "source": "출처",
    "requester": "요청자",
    "deleted": "삭제",
}
DATE_FIELDS = ("created_date", "target", "done_date")


def parse_date(value: str | None) -> date | None:
    """'2026-10-02' → date. 빈 값은 None."""
    return date.fromisoformat(value) if value else None


class Store:
    """events/ 폴더의 모든 로그를 읽어 업무·사용자 상태를 메모리에 유지한다."""

    def __init__(self, data_dir: Path, writer_name: str | None = None):
        self.events_dir = Path(data_dir) / "events"
        self.writer_name = writer_name  # 내가 쓸 파일 이름 (없으면 읽기 전용)
        self._lock = threading.Lock()  # 같은 프로그램 안의 요청끼리만 보호
        self._offsets: dict[str, int] = {}  # 파일별로 어디까지 읽었는지
        self._events: list[dict] = []
        self.errors: list[str] = []  # 깨진 줄 등 (입력점검 화면에 표시)
        self.rev = 0  # 변경될 때마다 증가 → 브라우저 자동 새로고침 판단용
        self.tasks: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self._last_own_ts = ""  # 내 파일의 마지막 시각 (시계가 뒤로 가도 순서 보장용)

    # ---------- 읽기 ----------

    def refresh(self) -> None:
        """새로 추가된 줄만 읽고, 있으면 전체 재생."""
        with self._lock:
            new_events = []
            for path in sorted(self.events_dir.glob("*.jsonl")):
                new_events += self._read_new_lines(path)
            if new_events:
                self._events += new_events
                # 같은 시각이면 같은 파일 안의 줄 순서를 따른다
                # ponytail: 변경 시 전체 재정렬·재생. 이벤트 수십만 건이 되면 증분 방식으로 변경
                self._events.sort(key=lambda e: (e["ts"], e["_src"], e["_seq"]))
                self._replay()
                self.rev += 1

    def _read_new_lines(self, path: Path) -> list[dict]:
        offset = self._offsets.get(path.name, 0)
        if path.stat().st_size <= offset:
            return []
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        # 다른 PC가 아직 쓰는 중인 마지막 줄(줄바꿈 없음)은 다음에 읽는다
        end = chunk.rfind(b"\n") + 1
        self._offsets[path.name] = offset + end
        events = []
        for raw in chunk[:end].splitlines():
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.errors.append(f"{path.name}: 읽을 수 없는 줄 무시 ({raw[:40]!r})")
                continue
            ev["_src"], ev["_seq"] = path.name, offset + len(events)  # 파일 내 순서 (메모리에서만)
            events.append(ev)
            if path.stem == self.writer_name:
                self._last_own_ts = max(self._last_own_ts, ev["ts"])
        return events

    def _replay(self) -> None:
        tasks: dict[str, dict] = {}
        users: dict[str, dict] = {}
        for ev in self._events:
            kind = ev["type"]
            if kind == "user":
                users.setdefault(ev["name"], {"name": ev["name"]}).update(ev["fields"])
            elif kind == "task_new":
                tasks[ev["task"]] = _new_task(ev, no=len(tasks) + 1)
            elif kind == "task_set" and ev["task"] in tasks:
                _apply_set(tasks[ev["task"]], ev)
            elif kind == "comment" and ev["task"] in tasks:
                tasks[ev["task"]]["comments"].append(
                    {"ts": ev["ts"], "by": ev["by"], "text": ev["text"]}
                )
        self.tasks, self.users = tasks, users

    # ---------- 쓰기 ----------

    def append(self, by: str, kind: str, **payload) -> dict:
        """내 파일에 이벤트 한 줄 추가. 공유폴더 오류는 OSError로 그대로 올린다(조용히 잃지 않음)."""
        if not self.writer_name:
            raise RuntimeError("쓰기 파일이 지정되지 않았습니다.")
        now = datetime.now()
        if self._last_own_ts and now <= datetime.fromisoformat(self._last_own_ts):
            # Windows 시계 해상도(수 ms)·시각 보정으로 같은/이전 시각이 나와도 내 이벤트 순서는 유지
            now = datetime.fromisoformat(self._last_own_ts) + timedelta(microseconds=1)
        ev = {
            "id": uuid.uuid4().hex,
            "ts": now.isoformat(timespec="microseconds"),
            "by": by,
            "type": kind,
            **payload,
        }
        self.events_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(ev, ensure_ascii=False) + "\n"
        with (self.events_dir / f"{self.writer_name}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)  # 한 번의 write로 한 줄 전체를 기록
        self.refresh()
        return ev

    def create_task(self, by: str, fields: dict) -> str:
        task_id = uuid.uuid4().hex[:12]
        self.append(by, "task_new", task=task_id, fields=fields)
        return task_id

    def update_task(self, by: str, task_id: str, fields: dict) -> None:
        if fields:
            self.append(by, "task_set", task=task_id, fields=fields)

    def add_comment(self, by: str, task_id: str, text: str) -> None:
        self.append(by, "comment", task=task_id, text=text)

    def set_user(self, by: str, name: str, **fields) -> None:
        self.append(by, "user", name=name, fields=fields)


def _new_task(ev: dict, no: int) -> dict:
    task = {key: None for key in TASK_FIELDS}
    task.update(collaborators=[], deleted=False)
    task.update(ev["fields"])
    task["collaborators"] = sorted(task["collaborators"])
    task.update(
        id=ev["task"],
        no=no,
        created_by=ev["by"],
        updated_ts=ev["ts"],
        updated_by=ev["by"],
        comments=[],
        audit=[],
        target_history=[],
    )
    if task["target"]:
        task["target_history"].append({"date": task["target"], "by": ev["by"], "ts": ev["ts"]})
    return task


def _apply_set(task: dict, ev: dict) -> None:
    for field, new in ev["fields"].items():
        if field == "collaborators":
            new = sorted(new)  # 순서만 다른 경우를 '변경'으로 보지 않도록 정렬 보관
        old = task.get(field)
        if old == new:
            continue
        task[field] = new
        task["audit"].append(
            {"ts": ev["ts"], "by": ev["by"], "field": field, "old": old, "new": new}
        )
        if field == "target" and new:
            task["target_history"].append({"date": new, "by": ev["by"], "ts": ev["ts"]})
    task["updated_ts"], task["updated_by"] = ev["ts"], ev["by"]


def writer_file_name(me: str, install_id: str) -> str:
    """설치마다 다른 파일 → 같은 사람이 PC 2대를 써도 파일 작성자는 항상 1명."""
    return f"{me}_{install_id}"


def ensure_dir_writable(path: Path) -> None:
    """시작 시 공유폴더 접근 확인. 실패하면 OSError."""
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".probe_{os.getpid()}"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
