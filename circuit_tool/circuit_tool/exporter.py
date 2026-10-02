"""모델 → DXF (1차: 가져온 원본 DXF 의 속성값만 수정, 원래 배치 유지)."""
from __future__ import annotations

from pathlib import Path

import ezdxf

from .model import Issue, Project


def _apply(ins, attrs: dict[str, str]) -> None:
    have = {a.dxf.tag.upper(): a for a in ins.attribs}
    for tag, val in attrs.items():
        if tag in have:
            have[tag].dxf.text = val
        elif val:
            ins.add_attrib(tag, val, ins.dxf.insert, dxfattribs={"flags": 1})   # 숨김 속성으로 추가


def export_project(proj: Project, out_dir: str | Path) -> tuple[list[Path], list[Issue]]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written, issues = [], []
    for sid, sheet in proj.sheets.items():
        src = Path(sheet.source)
        if not src.exists():
            issues.append(Issue("내보내기 실패", sid, str(src), "원본 DXF 없음"))
            continue
        doc = ezdxf.readfile(src)
        items = [(e.geom.handle, e.attrs, e.label()) for e in proj.elements.values() if e.sheet == sid]
        items += [(w.label_handle, w.attrs, w.attrs.get("WIRE_NO", w.id)) for w in proj.wires.values()
                  if w.sheet == sid]
        for handle, attrs, name in items:
            if handle is None:
                continue   # 미작도 분기점 등 도면에 없는 요소
            ent = doc.entitydb.get(handle)
            if ent is None or ent.dxftype() != "INSERT":
                issues.append(Issue("내보내기 실패", sid, name, f"원본에서 블록(handle {handle})을 찾지 못함"))
                continue
            _apply(ent, attrs)
        dst = out / (src.stem + ".dxf")
        doc.saveas(dst)
        written.append(dst)
    return written, issues
