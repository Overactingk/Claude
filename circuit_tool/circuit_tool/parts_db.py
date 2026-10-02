"""부품 사양 마스터 (사용자가 직접 관리하는 CSV).

- wire_ampacity.csv : MATERIAL, SQ, ENV, AMPACITY_A, SOURCE
- terminals.csv     : TERMINAL_PN, RATING_A, SQ_MIN, SQ_MAX, SOURCE
- fuse.csv          : ITEM(MARGIN | STD_RATING), VALUE, SOURCE

DB에 없는 값은 None 을 돌려주고, 판정은 '판정 불가'가 된다. 수치를 추정하지 않는다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .model import to_float


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip().upper(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def _sq_key(sq) -> str:
    v = to_float(sq)
    return "" if v is None else f"{v:g}"


@dataclass
class Terminal:
    pn: str
    rating: float | None
    sq_min: float | None
    sq_max: float | None


@dataclass
class PartsDB:
    wires: dict[tuple[str, str, str], float] = field(default_factory=dict)   # (MATERIAL, SQ, ENV)
    terminals: dict[str, Terminal] = field(default_factory=dict)
    fuse_margin: float | None = None
    fuse_std: list[float] = field(default_factory=list)

    @classmethod
    def load(cls, folder: str | Path) -> "PartsDB":
        d = Path(folder)
        db = cls()
        for r in _rows(d / "wire_ampacity.csv"):
            amp = to_float(r.get("AMPACITY_A"))
            if amp is not None:
                db.wires[(r["MATERIAL"].upper(), _sq_key(r["SQ"]), r.get("ENV", "").upper())] = amp
        for r in _rows(d / "terminals.csv"):
            pn = r["TERMINAL_PN"].upper()
            db.terminals[pn] = Terminal(pn, to_float(r.get("RATING_A")),
                                        to_float(r.get("SQ_MIN")), to_float(r.get("SQ_MAX")))
        for r in _rows(d / "fuse.csv"):
            item, val = r.get("ITEM", "").upper(), to_float(r.get("VALUE"))
            if val is None:
                continue
            if item == "MARGIN":
                db.fuse_margin = val
            elif item == "STD_RATING":
                db.fuse_std.append(val)
        return db

    def ampacity(self, material: str, sq: str, env: str) -> tuple[float | None, str]:
        """(허용전류, 실패 사유). ENV 미지정이면 재질·SQ 가 같은 행이 하나일 때만 사용."""
        m, s, e = material.upper().strip(), _sq_key(sq), env.upper().strip()
        if not m or not s:
            return None, "재질/SQ 미입력"
        if e:
            v = self.wires.get((m, s, e))
            return (v, "") if v is not None else (None, f"DB에 없음 ({m} {s}sq {e})")
        cands = [v for (mm, ss, _), v in self.wires.items() if mm == m and ss == s]
        if len(cands) == 1:
            return cands[0], ""
        if not cands:
            return None, f"DB에 없음 ({m} {s}sq)"
        return None, f"적용 환경(ENV) 미지정 — {m} {s}sq 의 환경별 값이 여러 개"

    def terminal(self, pn: str) -> Terminal | None:
        return self.terminals.get(pn.upper().strip())
