"""요구사항 12장 테스트 케이스 도면 생성 (CE_BOX + DR_UNIT 2장).

F42 (B+, 10A) → 75 (FLRY 0.75) → [인라인 DASH-DASH SUB 5] → 75 → DRL UNIT 1번 핀 (B+)
F35 (IG, 10A) → 90 (FLRY 0.75) → 분기점 → 90A (FLRY 0.5) → DRL UNIT 2번 핀 (IG)
                                       → 90B (FLRY 0.5) → FOG LAMP 3번 핀 (IG)
※ 전류값은 가상값.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

from .blocks import define_blocks, place, wire
from .model import BOX_TERMINAL, FUSE, INLINE, PIN, SHEET_REF, SPLICE, WIRE

CE_BOX = "69001-KV405_001004_(CE_BOX)_R0.dxf"
DR_UNIT = "69021-KV405_(DR_UNIT)_R0.dxf"


def _label(msp, at, no, sq, color="W", mat="FLRY", env="실내"):
    place(msp, WIRE, at, {"WIRE_NO": no, "MATERIAL": mat, "SQ": sq, "COLOR": color, "ENV": env})


def make_sample(folder: str | Path) -> list[Path]:
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2013")
    define_blocks(doc)
    m = doc.modelspace()
    m.add_text("CE BOX (SAMPLE)", dxfattribs={"height": 3, "insert": (-20, 20)})
    for y, no, func, ptype, term, link in ((0, "F42", "DRL", "B+", "E74", "L-F42"),
                                           (-30, "F35", "FOG/DRL IG", "IG", "G42", "L-F35")):
        place(m, FUSE, (0, y), {"JBOX_NO": "CE", "FUSE_NO": no, "FUNCTION": func, "RATING": "10A",
                                "PWR_TYPE": ptype})
        place(m, BOX_TERMINAL, (0, y), {"BOX": "CE", "TERMINAL_NO": term, "TERMINAL_PN": "TRM-A"})
        place(m, SHEET_REF, (0, y), {"LINK_ID": link, "TARGET_SHEET": "21", "TARGET_DEVICE": "DR UNIT",
                                     "DIRECTION": "OUT"})
    m.add_lwpolyline([(-30, -45), (40, -45), (40, 15), (-30, 15)], close=True)   # 박스 외곽 (배경)
    p1 = d / CE_BOX
    doc.saveas(p1)

    doc = ezdxf.new("R2013")
    define_blocks(doc)
    m = doc.modelspace()
    m.add_text("DR UNIT (SAMPLE)", dxfattribs={"height": 3, "insert": (0, 20)})
    place(m, SHEET_REF, (0, 0), {"LINK_ID": "L-F42", "TARGET_SHEET": "01", "DIRECTION": "IN"})
    wire(m, (0, 0), (40, 0)); _label(m, (18, 1), "75", "0.75", "R")
    place(m, INLINE, (40, 0), {"CONN_NAME": "DASH-DASH SUB", "PIN_NO": "5", "TERMINAL_PN": "TRM-A"})
    wire(m, (40, 0), (80, 0)); _label(m, (58, 1), "75", "0.75", "R")
    place(m, PIN, (80, 0), {"DEVICE": "DRL UNIT", "CONN": "D01", "PIN_NO": "1", "PIN_FUNC": "B+",
                            "LOAD_CURRENT": "3.0", "TERMINAL_PN": "TRM-A"})

    place(m, SHEET_REF, (0, -40), {"LINK_ID": "L-F35", "TARGET_SHEET": "01", "DIRECTION": "IN"})
    wire(m, (0, -40), (40, -40)); _label(m, (18, -39), "90", "0.75", "Y")
    place(m, SPLICE, (40, -40), {"SPLICE_NO": "SP01"})
    wire(m, (40, -40), (80, -40)); _label(m, (58, -39), "90A", "0.5", "Y")
    place(m, PIN, (80, -40), {"DEVICE": "DRL UNIT", "CONN": "D01", "PIN_NO": "2", "PIN_FUNC": "IG",
                              "LOAD_CURRENT": "0.5", "TERMINAL_PN": "TRM-A"})
    wire(m, (40, -40), (40, -70), (80, -70)); _label(m, (58, -69), "90B", "0.5", "Y")
    place(m, PIN, (80, -70), {"DEVICE": "FOG LAMP", "CONN": "F01", "PIN_NO": "3", "PIN_FUNC": "IG",
                              "LOAD_CURRENT": "4.0", "TERMINAL_PN": "TRM-A"})
    p2 = d / DR_UNIT
    doc.saveas(p2)
    return [p1, p2]
