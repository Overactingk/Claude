"""요구사항 12장 테스트 케이스."""
import csv
from pathlib import Path

import ezdxf
import pytest

from circuit_tool.exporter import export_project
from circuit_tool.importer import import_folder
from circuit_tool.model import Project
from circuit_tool.parts_db import PartsDB
from circuit_tool.report import write_reports
from circuit_tool.sample import CE_BOX, DR_UNIT, make_sample
from circuit_tool.sheetname import parse_sheet_name, select_latest
from circuit_tool.table import export_table, import_table
from circuit_tool.verifier import NA, NG, OK, verify

DB = Path(__file__).resolve().parent.parent / "parts_db"


@pytest.fixture
def dxf_dir(tmp_path):
    make_sample(tmp_path / "dxf")
    return tmp_path / "dxf"


@pytest.fixture
def proj(dxf_dir):
    return import_folder(dxf_dir)


def run(proj):
    return verify(proj, PartsDB.load(DB))


def pin(proj, device, no):
    return next(e for e in proj.elements.values()
                if e.kind == "PIN" and e.attrs["DEVICE"] == device and e.attrs["PIN_NO"] == no)


def types(res):
    return {i.type for i in res.issues}


def test_sheet_name():
    s = parse_sheet_name("69001-KV405_001004_(CE_BOX)_R0.dwg")
    assert (s.drawing_no, s.vehicle, s.sheet_no, s.sheet_total, s.name, s.rev) == \
        ("69001", "KV405", "001", "004", "CE_BOX", "R0")
    s = parse_sheet_name("69002-KV405_(AUX_FUSE_BOX)_R0.dwg")
    assert s.sheet_no is None and s.name == "AUX_FUSE_BOX"
    assert parse_sheet_name("69032-KV405_001002(NACEKO_SW)_R0.dwg").sheet_no == "001"
    assert parse_sheet_name("69019-KV405_(REAR_LAMP_BACK_UP_ALARM)_R00.dwg").rev == "R00"
    assert parse_sheet_name("메모.dwg") is None


def test_latest_revision():
    chosen, issues = select_latest([Path("69005-KV405_(START)_R0.dxf"), Path("69005-KV405_(START)_R2.dxf"),
                                    Path("69005-KV405_(START)_R1.dxf")])
    assert [s.rev for _, s in chosen] == ["R2"]
    assert len(issues) == 2


def test_import_clean(proj):
    assert len(proj.sheets) == 2
    assert proj.issues == []
    assert sorted(w.attrs["WIRE_NO"] for w in proj.wires.values()) == ["75", "75", "90", "90A", "90B"]


def test_fuse_load_sum_and_rows(proj):
    res = run(proj)
    f35 = next(r for r in res.fuse_rows if r["퓨즈번호"] == "F35")
    assert f35["부하 합계(A)"] == pytest.approx(4.5)          # 두 핀 전류 합
    assert f35["퓨즈 판정"] == OK
    rows = {r["회로번호"]: r for r in res.wire_rows if r["퓨즈번호"] == "F35"}
    assert set(rows) == {"90", "90A", "90B"}                   # 구간별 별도 행
    assert rows["90"]["하류 부하(A)"] == pytest.approx(4.5)
    assert rows["90B"]["하류 부하(A)"] == pytest.approx(4.0)
    assert rows["90A"]["전선 판정"] == NG                       # 0.5sq(가상 9A) < 10A
    assert rows["90"]["전선 판정"] == OK
    assert res.issues == []


def test_power_type_mismatch(proj):
    pin(proj, "FOG LAMP", "3").attrs["PIN_FUNC"] = "B+"
    assert "전원 종류 불일치" in types(run(proj))


def test_unknown_terminal(proj):
    pin(proj, "FOG LAMP", "3").attrs["TERMINAL_PN"] = "TRM-XXX"
    res = run(proj)
    row = next(r for r in res.wire_rows if r["회로번호"] == "90B")
    assert row["단자 판정"] == NA
    assert any("DB에 없음" in i.message for i in res.issues)


def test_missing_sheet_ref_pair(dxf_dir):
    path = dxf_dir / DR_UNIT
    doc = ezdxf.readfile(path)
    for ins in doc.modelspace().query("INSERT[name=='E_SHEETREF']"):
        if ins.get_attrib_text("LINK_ID") == "L-F35":
            doc.modelspace().delete_entity(ins)
    doc.saveas(path)
    res = run(import_folder(dxf_dir))
    assert "참조 짝 오류" in types(res)
    assert "연결 오류" in types(res)       # 퓨즈까지 추적 안 되는 전원 핀


def test_missing_load(proj):
    pin(proj, "DRL UNIT", "2").attrs["LOAD_CURRENT"] = ""
    res = run(proj)
    assert "전류 미입력" in types(res)
    assert next(r for r in res.fuse_rows if r["퓨즈번호"] == "F35")["퓨즈 판정"] == NA


def test_splice_required(tmp_path, dxf_dir):
    path = dxf_dir / DR_UNIT
    doc = ezdxf.readfile(path)
    for ins in doc.modelspace().query("INSERT[name=='E_SPLICE']"):
        doc.modelspace().delete_entity(ins)
    doc.saveas(path)
    proj = import_folder(dxf_dir)
    assert any(i.type == "Splice 블록 없음" for i in proj.issues)
    # 오류는 내되 추적은 계속된다
    f35 = next(r for r in run(proj).fuse_rows if r["퓨즈번호"] == "F35")
    assert f35["부하 합계(A)"] == pytest.approx(4.5)


def test_csv_bom(proj, tmp_path):
    paths = write_reports(run(proj), proj.issues, tmp_path / "out")
    assert all(p.read_bytes().startswith(b"\xef\xbb\xbf") for p in paths)
    with paths[0].open(encoding="utf-8-sig") as f:
        assert next(csv.reader(f))[0] == "시트"


def test_edit_export_roundtrip(proj, tmp_path):
    t = tmp_path / "el.csv"
    export_table(proj, t)
    with t.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["DEVICE"] == "FOG LAMP":
            r["LOAD_CURRENT"] = "6.5"
    with t.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    assert any("LOAD_CURRENT" in c for c in import_table(proj, t))

    out = tmp_path / "exp"
    written, issues = export_project(proj, out)
    assert len(written) == 2 and issues == []
    again = import_folder(out)
    assert pin(again, "FOG LAMP", "3").attrs["LOAD_CURRENT"] == "6.5"
    # 배치 유지: 요소·전선 좌표가 그대로
    assert sorted(e.geom.points[0] for e in again.elements.values()) == \
        sorted(e.geom.points[0] for e in proj.elements.values())
    assert len(again.wires) == len(proj.wires) and again.issues == []


def test_project_save_load(proj, tmp_path):
    proj.save(tmp_path / "p.json")
    p2 = Project.load(tmp_path / "p.json")
    assert run(p2).fuse_rows == run(proj).fuse_rows


def test_sheet_list_check(proj, tmp_path):
    from openpyxl import Workbook

    from circuit_tool.sheetname import check_sheet_list
    wb = Workbook()
    ws = wb.active
    ws.append(["도면번호", "시트명"])
    ws.append([69001, "CE_BOX"])
    ws.append(["69005-KV405", "START"])
    wb.save(tmp_path / "list.xlsx")
    issues = check_sheet_list(tmp_path / "list.xlsx", list(proj.sheets.values()))
    assert {(i.type, i.sheet) for i in issues} == {("누락 시트", "69005"), ("리스트 외 시트", "69021")}
