"""1차 편집: 요소 목록 CSV 로 내보내 수정한 뒤 다시 반영."""
from __future__ import annotations

import csv
from pathlib import Path

from .model import ATTR_TAGS, WIRE, Project

_ALL_TAGS = list(dict.fromkeys(t for tags in ATTR_TAGS.values() for t in tags))


def export_table(proj: Project, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "SHEET", "KIND"] + _ALL_TAGS)
        for e in proj.elements.values():
            if e.geom.handle:
                w.writerow([e.id, e.sheet, e.kind] + [e.attrs.get(t, "") for t in _ALL_TAGS])
        for x in proj.wires.values():
            w.writerow([x.id, x.sheet, WIRE] + [x.attrs.get(t, "") for t in _ALL_TAGS])


def import_table(proj: Project, path: str | Path) -> list[str]:
    """수정된 값을 반영하고 변경 내역을 돌려준다. 종류에 없는 속성 열은 무시."""
    changes = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            item = proj.item(r["ID"])
            if item is None:
                changes.append(f"[무시] 없는 ID {r['ID']}")
                continue
            kind = r["KIND"]
            for tag in ATTR_TAGS.get(kind, []):
                new = (r.get(tag) or "").strip()
                if item.attrs.get(tag, "") != new:
                    changes.append(f"{r['ID']} {tag}: '{item.attrs.get(tag, '')}' → '{new}'")
                    item.attrs[tag] = new
    return changes
