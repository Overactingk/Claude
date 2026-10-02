"""CSV 출력 (요구사항 9.1). UTF-8 BOM, 숫자는 단위 없이."""
from __future__ import annotations

import csv
from pathlib import Path

from .model import Issue
from .verifier import Result

FUSE_COLS = ["시트", "J/BOX", "퓨즈번호", "기능", "전원", "용량(A)", "연결 핀 목록",
             "부하 합계(A)", "경로 최소 SQ", "퓨즈 판정"]
WIRE_COLS = ["시트", "퓨즈번호", "퓨즈 용량(A)", "회로번호", "재질", "SQ", "허용전류(A)", "COLOR",
             "From", "To", "하류 핀", "하류 부하(A)", "전선 판정", "단자 판정"]
ERR_COLS = ["유형", "시트", "위치", "내용"]


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    return v


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in cols])


def write_reports(res: Result, import_issues: list[Issue], out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / "fuse_summary.csv", out / "wire_detail.csv", out / "error_report.csv"]
    _write(paths[0], FUSE_COLS, res.fuse_rows)
    _write(paths[1], WIRE_COLS, res.wire_rows)
    errs = [{"유형": i.type, "시트": i.sheet, "위치": i.location, "내용": i.message}
            for i in list(import_issues) + res.issues]
    _write(paths[2], ERR_COLS, errs)
    return paths
