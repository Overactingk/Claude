"""DXF → 회로 데이터 모델 (블록 기반 가져오기, 방식 A).

연결 판단: 선 끝점과 블록 삽입점의 좌표 일치(허용오차 tol).
- 선은 끝점끼리만 연결 (중간 통과는 연결 아님)
- 블록 없는 점에서 3갈래 이상 → 오류 (Splice 블록 필요). 추적은 계속하도록 연결은 유지
- 블록 없는 끝점(1갈래) → 미연결 오류
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import ezdxf
from ezdxf import path as ezpath

from .blocks import BLOCK_KIND, WIRE_LAYER
from .model import (ATTR_TAGS, WIRE, Element, Geometry, Issue, Project, Sheet,
                    Wire)
from .sheetname import select_latest

DEFAULT_TOL = 0.5         # 접속 허용오차 (도면 단위)
DEFAULT_LABEL_TOL = 5.0   # 전선 라벨 ↔ 선 최대 거리


class _Nodes:
    """좌표 → 노드 번호 (허용오차 내 같은 점은 같은 노드)."""

    def __init__(self, tol: float):
        self.tol = tol
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        self.pts: list[tuple[float, float]] = []

    def get(self, x: float, y: float) -> int:
        gx, gy = round(x / self.tol), round(y / self.tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in self.grid[(gx + dx, gy + dy)]:
                    px, py = self.pts[n]
                    if math.hypot(px - x, py - y) <= self.tol:
                        return n
        self.pts.append((x, y))
        self.grid[(gx, gy)].append(len(self.pts) - 1)
        return len(self.pts) - 1


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _display(msp) -> dict:
    """화면 표시용 배경 도형 (전선은 별도로 그린다)."""
    polys, texts = [], []

    def add(e):
        t = e.dxftype()
        if t in ("TEXT", "ATTRIB", "MTEXT"):
            if t == "ATTRIB" and e.is_invisible:
                return
            txt = e.plain_text() if t == "MTEXT" else e.dxf.text
            if t == "MTEXT":
                ins, h, rot = e.dxf.insert, e.dxf.char_height, e.dxf.get("rotation", 0)
            else:
                ins = e.dxf.align_point if e.dxf.get("halign", 0) or e.dxf.get("valign", 0) else e.dxf.insert
                ins = ins if ins is not None else e.dxf.insert
                h, rot = e.dxf.height, e.dxf.get("rotation", 0)
            if txt:
                texts.append([round(ins.x, 3), round(ins.y, 3), round(h, 3), round(rot, 1), txt])
            return
        if t == "INSERT":
            for v in e.virtual_entities():
                if v.dxftype() != "ATTDEF":
                    add(v)
            for a in e.attribs:
                add(a)
            return
        if t == "LINE" and e.dxf.layer.upper() == WIRE_LAYER:
            return
        if t == "LWPOLYLINE" and e.dxf.layer.upper() == WIRE_LAYER:
            return
        try:
            p = ezpath.make_path(e)
        except (TypeError, ValueError):
            return
        pts = [[round(v.x, 3), round(v.y, 3)] for v in p.flattening(0.2)]
        if len(pts) >= 2:
            polys.append(pts)

    for e in msp:
        add(e)
    return {"polys": polys, "texts": texts}


def import_sheet(proj: Project, sheet: Sheet, doc, tol: float = DEFAULT_TOL,
                 label_tol: float = DEFAULT_LABEL_TOL) -> None:
    msp = doc.modelspace()
    sid = sheet.id
    nodes = _Nodes(tol)
    issues = proj.issues

    # 1) 블록
    node_elems: dict[int, list[str]] = defaultdict(list)
    labels: list[tuple[str, dict, tuple[float, float]]] = []
    for ins in msp.query("INSERT"):
        kind = BLOCK_KIND.get(ins.dxf.name.upper())
        if kind is None:
            continue
        attrs = {a.dxf.tag.upper(): a.dxf.text.strip() for a in ins.attribs}
        for tag in ATTR_TAGS[kind]:
            attrs.setdefault(tag, "")
        x, y = ins.dxf.insert.x, ins.dxf.insert.y
        if kind == WIRE:
            labels.append((ins.dxf.handle, attrs, (x, y)))
            continue
        eid = f"{sid}:{ins.dxf.handle}"
        proj.elements[eid] = Element(eid, sid, kind, attrs,
                                     Geometry(ins.dxf.handle, ins.dxf.layer, [[x, y]], ins.dxf.name))
        node_elems[nodes.get(x, y)].append(eid)

    # 같은 점의 요소끼리는 직접 연결
    for elems in node_elems.values():
        for i in range(1, len(elems)):
            proj.links.append([elems[0], elems[i]])

    # 2) 전선 선분
    segs: list[tuple[int, int, list[list[float]], str]] = []
    for e in msp:
        if e.dxf.layer.upper() != WIRE_LAYER:
            continue
        t = e.dxftype()
        if t == "LINE":
            pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        elif t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if e.closed:
                pts.append(pts[0])
        else:
            continue
        for a, b in zip(pts, pts[1:]):
            na, nb = nodes.get(*a), nodes.get(*b)
            if na != nb:
                segs.append((na, nb, [list(a), list(b)], e.dxf.handle))

    adj: dict[int, list[int]] = defaultdict(list)
    for i, (na, nb, _, _) in enumerate(segs):
        adj[na].append(i)
        adj[nb].append(i)

    def is_stop(n: int) -> bool:   # 전선 구간의 끝이 되는 노드
        return bool(node_elems.get(n)) or len(adj[n]) != 2

    for n, lst in adj.items():
        if node_elems.get(n):
            continue
        x, y = nodes.pts[n]
        if len(lst) == 1:
            issues.append(Issue("미연결 전선 끝", sid, f"({x:.1f},{y:.1f})", "접속 블록 없이 끝난 선"))
        elif len(lst) >= 3:
            issues.append(Issue("Splice 블록 없음", sid, f"({x:.1f},{y:.1f})",
                                f"{len(lst)}갈래 분기에 Splice 블록이 없음"))

    # 3) 선분을 전선 구간으로 묶기 (블록/분기점 사이)
    used = [False] * len(segs)
    junction_ids: dict[int, str] = {}   # 블록 없는 분기점 → 가상 요소

    def end_elem(n: int) -> str | None:
        if node_elems.get(n):
            return node_elems[n][0]
        if len(adj[n]) >= 3:
            if n not in junction_ids:
                x, y = nodes.pts[n]
                jid = f"{sid}:J{n}"
                proj.elements[jid] = Element(jid, sid, "SPLICE", {"SPLICE_NO": "(미작도)"},
                                             Geometry(None, "", [[x, y]], None))
                junction_ids[n] = jid
            return junction_ids[n]
        return None

    wires: list[Wire] = []
    for i in range(len(segs)):
        if used[i]:
            continue
        # i 에서 양쪽으로 확장
        chain = [i]
        used[i] = True
        ends = []
        for start_side in (0, 1):
            cur_seg, cur_node = i, segs[i][start_side]
            side = []
            while not is_stop(cur_node):
                nxt = [s for s in adj[cur_node] if s != cur_seg and not used[s]]
                if not nxt:
                    break
                cur_seg = nxt[0]
                used[cur_seg] = True
                side.append(cur_seg)
                na, nb = segs[cur_seg][0], segs[cur_seg][1]
                cur_node = nb if na == cur_node else na
            ends.append(cur_node)
            chain = (list(reversed(side)) + chain) if start_side == 0 else chain + side
        wid = f"{sid}:W{segs[i][3]}_{i}"
        wires.append(Wire(wid, sid, {t: "" for t in ATTR_TAGS[WIRE]},
                          [end_elem(ends[0]), end_elem(ends[1])],
                          [segs[s][2] for s in chain],
                          sorted({segs[s][3] for s in chain})))

    # 4) 전선 라벨 → 가장 가까운 전선 구간
    for handle, attrs, p in labels:
        best, bd = None, label_tol
        for w in wires:
            for a, b in w.segments:
                d = _seg_dist(p, a, b)
                if d <= bd:
                    best, bd = w, d
        if best is None:
            issues.append(Issue("전선 라벨 미할당", sid, attrs.get("WIRE_NO", handle),
                                f"반경 {label_tol} 안에 전선 없음"))
            continue
        if best.label_handle and best.attrs.get("WIRE_NO") != attrs.get("WIRE_NO"):
            issues.append(Issue("전선 라벨 중복", sid, f"{best.attrs.get('WIRE_NO')} / {attrs.get('WIRE_NO')}",
                                "한 전선 구간에 서로 다른 라벨"))
            continue
        best.attrs.update(attrs)
        best.label_handle = handle

    for w in wires:
        if w.label_handle is None:
            (x1, y1), _ = w.segments[0]
            issues.append(Issue("전선 라벨 없음", sid, f"({x1:.1f},{y1:.1f})", "회로번호·SQ 를 알 수 없음"))
        if w.label_handle:
            w.id = f"{sid}:W{w.label_handle}"
        proj.wires[w.id] = w

    proj.display[sid] = _display(msp)


def import_folder(folder: str | Path, tol: float = DEFAULT_TOL,
                  label_tol: float = DEFAULT_LABEL_TOL) -> Project:
    """폴더의 DXF 를 모두 가져온다 (하위 폴더 제외, 최신 리비전만)."""
    paths = sorted(Path(folder).glob("*.dxf")) + sorted(Path(folder).glob("*.DXF"))
    chosen, issues = select_latest(list(dict.fromkeys(paths)))
    proj = Project(issues=issues)
    for p, sheet in chosen:
        try:
            doc = ezdxf.readfile(p)
        except (IOError, ezdxf.DXFStructureError) as ex:
            proj.issues.append(Issue("DXF 읽기 실패", sheet.id, p.name, str(ex)))
            continue
        proj.sheets[sheet.id] = sheet
        import_sheet(proj, sheet, doc, tol, label_tol)
    return proj
