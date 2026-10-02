"""작도용 속성 블록 정의 (블록 기반 가져오기 = 방식 A).

규칙
- 블록 삽입점 = 접속점. 전선(WIRE 레이어 선) 끝점을 삽입점에 맞춘다.
- 전선 속성은 E_WIRE_LABEL 블록을 해당 선 바로 위에 놓아 입력한다.
"""
from __future__ import annotations

import ezdxf

from .model import (ATTR_TAGS, BOX_TERMINAL, FUSE, INLINE, PIN, SHEET_REF, SPLICE,
                    WIRE)

BLOCK_KIND = {
    "E_FUSE": FUSE,
    "E_BOXTERM": BOX_TERMINAL,
    "E_SPLICE": SPLICE,
    "E_INLINE": INLINE,
    "E_PIN": PIN,
    "E_SHEETREF": SHEET_REF,
    "E_WIRE_LABEL": WIRE,
}
KIND_BLOCK = {v: k for k, v in BLOCK_KIND.items()}

WIRE_LAYER = "WIRE"
SYMBOL_LAYER = "E_SYMBOL"


def _shape(blk, kind: str) -> None:
    a = {"layer": SYMBOL_LAYER}
    if kind == FUSE:          # 왼쪽에 퓨즈 몸체, 삽입점은 출력쪽(오른쪽 끝)
        blk.add_lwpolyline([(-14, -2), (-4, -2), (-4, 2), (-14, 2)], close=True, dxfattribs=a)
        blk.add_line((-16, 0), (-14, 0), dxfattribs=a)
        blk.add_line((-4, 0), (0, 0), dxfattribs=a)
    elif kind == BOX_TERMINAL:
        blk.add_lwpolyline([(-1, -1), (1, -1), (1, 1), (-1, 1)], close=True, dxfattribs=a)
    elif kind == SPLICE:
        blk.add_circle((0, 0), 0.8, dxfattribs=a)
    elif kind == INLINE:
        blk.add_lwpolyline([(-1.5, -2), (1.5, -2), (1.5, 2), (-1.5, 2)], close=True, dxfattribs=a)
    elif kind == PIN:
        blk.add_circle((0, 0), 1.0, dxfattribs=a)
    elif kind == SHEET_REF:
        blk.add_lwpolyline([(0, 0), (3, 2.5), (24, 2.5), (24, -2.5), (3, -2.5)], close=True, dxfattribs=a)


# 화면에 보일 속성 (나머지는 숨김 속성)
_VISIBLE = {
    FUSE: ["FUSE_NO", "RATING", "FUNCTION"],
    BOX_TERMINAL: ["TERMINAL_NO"],
    SPLICE: ["SPLICE_NO"],
    INLINE: ["CONN_NAME", "PIN_NO"],
    PIN: ["DEVICE", "PIN_NO", "PIN_FUNC"],
    SHEET_REF: ["LINK_ID", "TARGET_SHEET"],
    WIRE: ["WIRE_NO", "SQ", "COLOR"],
}


# 속성 글자 시작 위치 (x, y, 줄 간격) — 같은 점에 겹쳐 놓는 퓨즈·박스 단자·참조 박스 글자가 겹치지 않게
_TEXT_POS = {
    FUSE: (-14, 3, 2),
    BOX_TERMINAL: (-1, -3.5, -2),
    SHEET_REF: (5, 0.6, -2),
}


def define_blocks(doc) -> None:
    """도면에 E_* 블록 정의를 추가한다 (이미 있으면 건너뜀)."""
    if WIRE_LAYER not in doc.layers:
        doc.layers.add(WIRE_LAYER, color=1)
    if SYMBOL_LAYER not in doc.layers:
        doc.layers.add(SYMBOL_LAYER, color=7)
    for name, kind in BLOCK_KIND.items():
        if name in doc.blocks:
            continue
        blk = doc.blocks.new(name)
        _shape(blk, kind)
        vis = _VISIBLE[kind]
        x, y, step = _TEXT_POS.get(kind, (0, 3, 2))
        for tag in ATTR_TAGS[kind]:
            hidden = tag not in vis
            blk.add_attdef(tag, (x, y), dxfattribs={"height": 1.5, "flags": 1 if hidden else 0,
                                                    "layer": SYMBOL_LAYER})
            if not hidden:
                y += step


def place(msp, kind: str, at: tuple[float, float], attrs: dict[str, str]):
    ins = msp.add_blockref(KIND_BLOCK[kind], at, dxfattribs={"layer": SYMBOL_LAYER})
    ins.add_auto_attribs({k: str(v) for k, v in attrs.items()})
    return ins


def wire(msp, *pts: tuple[float, float]):
    if len(pts) == 2:
        return msp.add_line(pts[0], pts[1], dxfattribs={"layer": WIRE_LAYER})
    return msp.add_lwpolyline(pts, dxfattribs={"layer": WIRE_LAYER})


def make_template(path: str) -> None:
    """GstarCAD 에서 INSERT 로 불러 쓸 블록 라이브러리 DXF."""
    doc = ezdxf.new("R2013")
    define_blocks(doc)
    msp = doc.modelspace()
    x = 0.0
    for kind in KIND_BLOCK:
        place(msp, kind, (x, 0), {t: t for t in ATTR_TAGS[kind]})
        x += 40
    doc.saveas(path)
