"""명령줄 진입점:  python -m circuit_tool <명령> ..."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import converter
from .blocks import make_template
from .exporter import export_project
from .importer import DEFAULT_LABEL_TOL, DEFAULT_TOL, import_folder
from .model import Project
from .parts_db import PartsDB
from .report import write_reports
from .sample import make_sample
from .sheetname import check_sheet_list
from .table import export_table, import_table
from .text_scan import scan_folder
from .verifier import verify

DEFAULT_DB = Path(__file__).resolve().parent.parent / "parts_db"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="circuit_tool", description="차량 전장 회로 검증·편집")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("dwg2dxf", help="DWG 폴더 → DXF 폴더 (ODA File Converter 필요)")
    s.add_argument("src"); s.add_argument("dst")
    s = sub.add_parser("dxf2dwg", help="DXF 폴더 → DWG 폴더 (ODA File Converter 필요)")
    s.add_argument("src"); s.add_argument("dst"); s.add_argument("--version", default="R2018")

    s = sub.add_parser("import", help="DXF 폴더 → 프로젝트(JSON)")
    s.add_argument("dxf_dir"); s.add_argument("-o", "--out", default="project.json")
    s.add_argument("--tol", type=float, default=DEFAULT_TOL, help="접속 허용오차")
    s.add_argument("--label-tol", type=float, default=DEFAULT_LABEL_TOL, help="전선 라벨 거리")
    s.add_argument("--sheet-list", help="회로도 리스트 엑셀 (누락 시트 대조)")

    s = sub.add_parser("verify", help="추적·판정 → CSV 3개")
    s.add_argument("project"); s.add_argument("-o", "--out", default="out")
    s.add_argument("--db", default=str(DEFAULT_DB), help="부품 DB 폴더")

    s = sub.add_parser("export", help="프로젝트 → DXF (원본 배치 유지, 속성값만 반영)")
    s.add_argument("project"); s.add_argument("-o", "--out", default="export_dxf")

    s = sub.add_parser("table-out", help="요소 목록 CSV 로 내보내기 (편집용)")
    s.add_argument("project"); s.add_argument("-o", "--out", default="elements.csv")
    s = sub.add_parser("table-in", help="편집한 요소 목록 CSV 반영")
    s.add_argument("project"); s.add_argument("csv")

    s = sub.add_parser("gui", help="화면(브라우저) 실행")
    s.add_argument("project"); s.add_argument("--db", default=str(DEFAULT_DB))
    s.add_argument("--port", type=int, default=8765)

    s = sub.add_parser("scan-text", help="블록 없는 기존 도면 텍스트 해석 후보 (방식 B 미리보기)")
    s.add_argument("dxf_dir"); s.add_argument("-o", "--out", default="text_candidates.csv")

    s = sub.add_parser("template", help="작도용 블록 라이브러리 DXF 생성")
    s.add_argument("-o", "--out", default="E_BLOCKS.dxf")
    s = sub.add_parser("sample", help="테스트 케이스 도면(CE_BOX, DR_UNIT) 생성")
    s.add_argument("-o", "--out", default="sample_dxf")

    a = ap.parse_args(argv)

    if a.cmd in ("dwg2dxf", "dxf2dwg"):
        to = "dxf" if a.cmd == "dwg2dxf" else "dwg"
        done = converter.convert_folder(a.src, a.dst, to, getattr(a, "version", "R2018"))
        print(f"{len(done)}개 변환 → {a.dst}")
    elif a.cmd == "import":
        proj = import_folder(a.dxf_dir, a.tol, a.label_tol)
        if a.sheet_list:
            proj.issues += check_sheet_list(a.sheet_list, list(proj.sheets.values()))
        proj.save(a.out)
        print(f"시트 {len(proj.sheets)}, 요소 {len(proj.elements)}, 전선 {len(proj.wires)}, "
              f"가져오기 오류 {len(proj.issues)} → {a.out}")
    elif a.cmd == "verify":
        proj = Project.load(a.project)
        res = verify(proj, PartsDB.load(a.db))
        for p in write_reports(res, proj.issues, a.out):
            print(p)
        ng = sum(r["퓨즈 판정"] == "NG" for r in res.fuse_rows) + \
            sum("NG" in (r["전선 판정"], r["단자 판정"]) for r in res.wire_rows)
        print(f"퓨즈 {len(res.fuse_rows)}, 전선 구간 {len(res.wire_rows)}, NG {ng}, "
              f"오류 {len(proj.issues) + len(res.issues)}")
    elif a.cmd == "export":
        written, issues = export_project(Project.load(a.project), a.out)
        for i in issues:
            print(f"[{i.type}] {i.sheet} {i.location}: {i.message}")
        print(f"{len(written)}개 DXF → {a.out}")
    elif a.cmd == "table-out":
        export_table(Project.load(a.project), a.out)
        print(a.out)
    elif a.cmd == "table-in":
        proj = Project.load(a.project)
        for c in import_table(proj, a.csv):
            print(c)
        proj.save(a.project)
    elif a.cmd == "gui":
        from .gui import serve
        serve(a.project, a.db, a.port)
    elif a.cmd == "scan-text":
        c, f = scan_folder(a.dxf_dir, a.out)
        print(f"후보 {c}, 미해석 {f} → {a.out}")
    elif a.cmd == "template":
        make_template(a.out)
        print(a.out)
    elif a.cmd == "sample":
        for p in make_sample(a.out):
            print(p)
