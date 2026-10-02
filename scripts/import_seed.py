"""seed_tasks.json(기존 업무 47건) + 초기 사용자 → 공유폴더 이벤트 로그로 이관.

사용법 (관리자 1회만):
    python scripts/import_seed.py seed_tasks.json "\\\\서버\\전장\\업무관리"

원칙: 기존 데이터는 고치지 않고 그대로 넣는다. 문제 항목은 앱의 '입력 점검'에 표시된다.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.store import Store  # noqa: E402

IMPORTER = "이관"  # 이관 이벤트의 작성자 표기
INITIAL_USERS = [
    ("나대경M", {"is_admin": True}),
    ("이가람C", {}),
    ("이재욱M", {}),
    ("박삼용C", {}),
    ("전장", {"can_login": False}),  # 팀 공통 업무용 가상 담당자
]


def import_seed(seed_path: Path, data_dir: Path, force: bool = False) -> int:
    store = Store(data_dir, writer_name="_이관")
    store.refresh()
    if store.tasks and not force:
        raise SystemExit(f"이미 업무 {len(store.tasks)}건이 있습니다. 중복 이관 방지를 위해 중단합니다. (--force로 강제)")

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    for row in seed:  # 날짜 형식만 사전 검증 (틀리면 몇 번인지 알려주고 중단)
        for d in [row["created_date"], row["done_date"], *row["target_dates"]]:
            if d:
                try:
                    date.fromisoformat(d)
                except ValueError as e:
                    raise SystemExit(f"No.{row['no']} 날짜 형식 오류: {d}") from e

    for name, fields in INITIAL_USERS:
        if name not in store.users:
            store.set_user(IMPORTER, name, **fields)

    for row in sorted(seed, key=lambda r: r["no"]):
        targets = row["target_dates"]
        fields = {
            "project": row["project"],
            "created_date": row["created_date"],
            "target": targets[0] if targets else None,  # 최초목표
            "done_date": row["done_date"],
            "content": row["content"],
            "owner": row["owner"],
            "collaborators": row["collaborators"],
            "file_path": row["file_path"],
            "note": row["note"],
        }
        task_id = store.create_task(IMPORTER, {k: v for k, v in fields.items() if v})
        if row["progress"]:
            store.add_comment(IMPORTER, task_id, row["progress"])
        for later in targets[1:]:  # 이후 목표 → 목표 변경 이력
            store.update_task(IMPORTER, task_id, {"target": later})
    return len(seed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="seed_tasks.json 이관")
    parser.add_argument("seed", type=Path)
    parser.add_argument("data_dir", type=Path, help="config.ini의 data_dir과 같은 공유폴더 경로")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    count = import_seed(args.seed, args.data_dir, args.force)
    print(f"{count}건 이관 완료 → {args.data_dir / 'events'}")
