import ezdxf

from circuit_tool.text_scan import scan_file


def test_text_patterns(tmp_path):
    doc = ezdxf.new()
    m = doc.modelspace()
    for i, t in enumerate(["55 (1.0 LB)", "808 (2.5 W)", "IMMO F11 10A",
                           "BCM G-22P W(G13,START,RLY30)  07", "ABS (??", "TITLE"]):
        m.add_text(t, dxfattribs={"insert": (0, i * 5)})
    p = tmp_path / "a.dxf"
    doc.saveas(p)
    cands, fails = scan_file(p)
    kinds = [c["유형"] for c in cands]
    assert kinds == ["전선", "전선", "퓨즈", "참조 박스"]
    assert "SQ=1.0" in cands[0]["해석"] and "COLOR=LB" in cands[0]["해석"]
    assert "FUSE_NO=F11" in cands[2]["해석"] and "RATING=10" in cands[2]["해석"]
    assert "PIN 후보=G13" in cands[3]["해석"] and "대상 시트=07" in cands[3]["해석"]
    assert [f["원문"] for f in fails] == ["ABS (??"]
