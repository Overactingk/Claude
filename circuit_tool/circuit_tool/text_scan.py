"""텍스트 기반 해석 미리보기 (방식 B, 2차 기능의 일부).

블록화되지 않은 기존 도면에서 텍스트를 패턴으로 해석해 '후보' 목록을 만든다.
연결 정보는 만들지 않는다. 결과는 확정이 아니며 사람이 검토해야 한다.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import ezdxf

# 55 (1.0 LB) / 808 (2.5 W) / 90A (0.5 B/W)
WIRE_RE = re.compile(r"^(?P<no>[0-9A-Z]+)\s*\(\s*(?P<sq>\d+(?:\.\d+)?)\s*(?P<color>[A-Z]{1,3}(?:/[A-Z]{1,3})?)\s*\)$")
# IMMO F11 10A
FUSE_RE = re.compile(r"^(?P<func>.+?)\s+(?P<no>F\d+[A-Z]?)\s+(?P<rating>\d+(?:\.\d+)?)\s*A$")
# BCM G-22P W(G13,START,RLY30)  07
REF_RE = re.compile(r"^(?P<dev>.+?)\s+(?P<conn>[A-Z]+-?\d+P)\s*(?P<col>[A-Z]{1,3})?\s*\((?P<inner>[^)]*)\)\s+(?P<sheet>\d{1,3})$")
PIN_TOKEN = re.compile(r"^(?:[A-Z]\d+|\d+-\d+|\d+)$")
FUNC_TOKEN = {"B+", "IG", "ACC", "GND"}


def _texts(msp):
    for e in msp.query("TEXT MTEXT"):
        t = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
        t = " ".join(t.split())
        if t:
            ins = e.dxf.insert
            yield e.dxf.handle, t, ins.x, ins.y


def scan_file(path: Path) -> tuple[list[dict], list[dict]]:
    msp = ezdxf.readfile(path).modelspace()
    cands, fails = [], []
    for h, t, x, y in _texts(msp):
        u = t.upper()
        base = {"파일": path.name, "handle": h, "X": round(x, 2), "Y": round(y, 2), "원문": t}
        if m := WIRE_RE.match(u):
            cands.append({**base, "유형": "전선", "해석": f"WIRE_NO={m['no']}; SQ={m['sq']}; COLOR={m['color']}"})
        elif m := FUSE_RE.match(u):
            cands.append({**base, "유형": "퓨즈",
                          "해석": f"FUNCTION={m['func']}; FUSE_NO={m['no']}; RATING={m['rating']}"})
        elif m := REF_RE.match(u):
            toks = [s.strip() for s in m["inner"].split(",") if s.strip()]
            pins = [s for s in toks if PIN_TOKEN.match(s)]
            funcs = [s for s in toks if s in FUNC_TOKEN]
            other = [s for s in toks if s not in pins and s not in funcs]
            cands.append({**base, "유형": "참조 박스",
                          "해석": f"DEVICE={m['dev']}; CONN={m['conn']}; PIN 후보={'/'.join(pins)}; "
                                  f"전원={'/'.join(funcs)}; 기타={'/'.join(other)}; 대상 시트={m['sheet']}"})
        elif "(" in u or re.search(r"\bF\d+\b", u):
            fails.append({**base, "유형": "미해석", "해석": "패턴 불일치 — 검토 필요"})
    return cands, fails


def scan_folder(folder: str | Path, out_csv: str | Path) -> tuple[int, int]:
    rows_c, rows_f = [], []
    for p in sorted(Path(folder).glob("*.dxf")):
        c, f = scan_file(p)
        rows_c += c
        rows_f += f
    cols = ["유형", "파일", "handle", "X", "Y", "원문", "해석"]
    with Path(out_csv).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        w.writerows(rows_c + rows_f)
    return len(rows_c), len(rows_f)
