"""추적·판정 (요구사항 6, 8장). DXF 를 직접 읽지 않고 모델만 사용한다.

판정값은 OK / NG / 판정 불가 세 가지로 고정.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from .model import (FUSE, INLINE, PASS_THROUGH, PIN, PIN_FUNCS, POWER_FUNCS,
                    SHEET_REF, TERMINAL_KINDS, Issue, Project, to_float)
from .parts_db import PartsDB

OK, NG, NA = "OK", "NG", "판정 불가"


def _worst(vals: list[str]) -> str:
    if NG in vals:
        return NG
    if NA in vals:
        return NA
    return OK


@dataclass
class Result:
    fuse_rows: list[dict] = field(default_factory=list)
    wire_rows: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    traces: dict[str, dict] = field(default_factory=dict)   # 퓨즈 id → {elements, wires} (화면 하이라이트용)


class _Graph:
    def __init__(self, proj: Project, issues: list[Issue]):
        self.p = proj
        self.adj: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
        for w in proj.wires.values():
            a, b = w.ends
            if a and b:
                self._add(a, b, w.id)
        for a, b in proj.links:
            self._add(a, b, None)
        self._pair(INLINE, lambda e: (e.attrs.get("CONN_NAME", "").upper(), e.attrs.get("PIN_NO", "").upper()),
                   issues)
        self._sheet_refs(issues)

    def _add(self, a: str, b: str, wid: str | None) -> None:
        self.adj[a].append((b, wid))
        self.adj[b].append((a, wid))

    def _pair(self, kind, key, issues) -> None:
        groups = defaultdict(list)
        for e in self.p.elements.values():
            if e.kind == kind and all(key(e)):
                groups[key(e)].append(e.id)
        for ids in groups.values():
            for other in ids[1:]:
                self._add(ids[0], other, None)

    def _sheet_refs(self, issues: list[Issue]) -> None:
        groups = defaultdict(list)
        for e in self.p.elements.values():
            if e.kind != SHEET_REF:
                continue
            lid = e.attrs.get("LINK_ID", "").strip().upper()
            if not lid:
                issues.append(Issue("참조 짝 오류", e.sheet, e.label(), "LINK_ID 미입력"))
                continue
            groups[lid].append(e)
        for lid, refs in groups.items():
            if len(refs) == 1:
                issues.append(Issue("참조 짝 오류", refs[0].sheet, lid, "짝 없는 참조 (상대 시트에 같은 LINK_ID 없음)"))
                continue
            if len(refs) > 2:
                issues.append(Issue("참조 짝 오류", refs[0].sheet, lid,
                                    f"LINK_ID 중복 {len(refs)}개: " + ", ".join(r.sheet for r in refs)))
                continue
            a, b = refs
            self._add(a.id, b.id, None)
            da, db_ = a.attrs.get("DIRECTION", "").upper(), b.attrs.get("DIRECTION", "").upper()
            if da and da == db_:
                issues.append(Issue("참조 정보 불일치", a.sheet, lid, f"양쪽 방향이 모두 {da}"))
            for x, y in ((a, b), (b, a)):
                tgt = x.attrs.get("TARGET_SHEET", "").strip()
                sy = self.p.sheets.get(y.sheet)
                # 가정: 참조 시트번호 = 도면번호 끝 두 자리 (요구사항 4.3, 확인 필요)
                if tgt and sy and not sy.drawing_no.endswith(tgt.zfill(2)):
                    issues.append(Issue("참조 정보 불일치", x.sheet, lid,
                                        f"대상 시트 {tgt} ↔ 실제 짝 {sy.drawing_no} (규칙: 도면번호 끝 2자리, 확인 필요)"))

    def joined(self, eid: str) -> list[str]:
        """전선 없이 직접 붙은 요소들 (같은 점·시트 참조 짝·인라인 짝) — 전선 끝의 단자 찾기용."""
        out, q = [eid], [eid]
        while q:
            u = q.pop()
            if u != eid and self.p.elements[u].kind not in PASS_THROUGH:
                continue
            for v, wid in self.adj[u]:
                if wid is None and v not in out:
                    out.append(v)
                    q.append(v)
        return out

    def expands(self, eid: str, start: str) -> bool:
        e = self.p.elements[eid]
        return eid == start or e.kind in PASS_THROUGH

    def bfs(self, start: str, blocked: str | None = None):
        depth = {start: 0}
        q = deque([start])
        wires: set[str] = set()
        while q:
            u = q.popleft()
            if not self.expands(u, start):
                continue
            for v, wid in self.adj[u]:
                if v == blocked:
                    continue
                if wid:
                    wires.add(wid)
                if v not in depth:
                    depth[v] = depth[u] + 1
                    q.append(v)
        return depth, wires


def verify(proj: Project, db: PartsDB) -> Result:
    res = Result()
    seen: set[tuple] = set()

    def issue(*args) -> None:
        if args not in seen:
            seen.add(args)
            res.issues.append(Issue(*args))

    gi: list[Issue] = []
    g = _Graph(proj, gi)
    for i in gi:
        issue(i.type, i.sheet, i.location, i.message)

    # 핀 입력 규칙 (4.2)
    for e in proj.elements.values():
        if e.kind != PIN:
            continue
        func = e.attrs.get("PIN_FUNC", "").upper()
        if func not in PIN_FUNCS:
            issue("PIN_FUNC 오류", e.sheet, e.label(), f"허용 값 아님: '{func}' (B+/IG/ACC/GND/SIG)")
        elif func in POWER_FUNCS and to_float(e.attrs.get("LOAD_CURRENT")) is None:
            issue("전류 미입력", e.sheet, e.label(), "전원 핀 LOAD_CURRENT 없음 (병렬 핀은 0 입력)")

    traced_pins: set[str] = set()
    fuses = sorted((e for e in proj.elements.values() if e.kind == FUSE),
                   key=lambda e: (e.sheet, e.attrs.get("FUSE_NO", "")))

    for f in fuses:
        fa = f.attrs
        rating = to_float(fa.get("RATING"))
        ptype = fa.get("PWR_TYPE", "").upper()
        if rating is None:
            issue("퓨즈 용량 오류", f.sheet, f.label(), f"용량 해석 불가: '{fa.get('RATING')}'")
        elif db.fuse_std and rating not in db.fuse_std:
            issue("퓨즈 용량 오류", f.sheet, f.label(), f"표준 용량 아님: {rating:g}A")
        if ptype not in POWER_FUNCS:
            issue("전원 종류 미지정", f.sheet, f.label(), f"PWR_TYPE '{ptype}' (B+/IG/ACC)")

        depth, wires = g.bfs(f.id)
        pins = [eid for eid in depth if proj.elements[eid].kind == PIN]
        for eid in depth:
            if eid != f.id and proj.elements[eid].kind == FUSE:
                issue("연결 오류", f.sheet, f.label(), f"다른 퓨즈 {proj.elements[eid].label()} 와 연결됨")
        traced_pins.update(pins)
        res.traces[f.id] = {"elements": list(depth), "wires": sorted(wires)}

        load_sum, load_ok, pin_txt = 0.0, True, []
        for pid in pins:
            p = proj.elements[pid]
            func = p.attrs.get("PIN_FUNC", "").upper()
            cur = to_float(p.attrs.get("LOAD_CURRENT"))
            pin_txt.append(f"{p.label()}({func}{'' if cur is None else f' {cur:g}A'})")
            if ptype in POWER_FUNCS and func != ptype:
                issue("전원 종류 불일치", p.sheet, p.label(), f"핀 {func or '(없음)'} ↔ 퓨즈 {f.label()} {ptype}")
            if func in POWER_FUNCS:
                if cur is None:
                    load_ok = False
                else:
                    load_sum += cur

        if rating is None or db.fuse_margin is None or not load_ok:
            fuse_j = NA
            if db.fuse_margin is None:
                issue("판정 불가", f.sheet, f.label(), "부품 DB에 퓨즈 여유율(MARGIN) 없음")
        else:
            fuse_j = OK if rating >= load_sum * db.fuse_margin else NG

        sqs = []
        def order(wid):   # 퓨즈에 가까운 구간부터
            w = proj.wires[wid]
            return min(depth.get(x, 1e9) for x in w.ends), w.attrs.get("WIRE_NO", "")

        for wid in sorted(wires, key=order):
            w = proj.wires[wid]
            wa = w.attrs
            a, b = w.ends
            near, far = (a, b) if depth.get(a, 1e9) <= depth.get(b, 1e9) else (b, a)
            if far is None:
                down = []
            elif proj.elements[far].kind == PIN:
                down = [far]
            else:
                d2, _ = g.bfs(far, blocked=near)
                down = [x for x in d2 if proj.elements[x].kind == PIN]
            down_load = sum(to_float(proj.elements[x].attrs.get("LOAD_CURRENT")) or 0.0 for x in down
                            if proj.elements[x].attrs.get("PIN_FUNC", "").upper() in POWER_FUNCS)
            sq = to_float(wa.get("SQ"))
            if sq is not None:
                sqs.append(sq)
            loc = wa.get("WIRE_NO") or wid

            amp, why = db.ampacity(wa.get("MATERIAL", ""), wa.get("SQ", ""), wa.get("ENV", ""))
            if amp is None:
                issue("판정 불가", w.sheet, loc, f"전선 허용전류: {why}")
                wire_j = NA
            elif rating is None:
                wire_j = NA
            else:
                wire_j = OK if amp >= rating else NG

            term_js = []
            ends = [x for end in (a, b) if end for x in g.joined(end)]
            for eid in dict.fromkeys(ends):
                if proj.elements[eid].kind not in TERMINAL_KINDS:
                    continue
                e = proj.elements[eid]
                pn = e.attrs.get("TERMINAL_PN", "")
                t = db.terminal(pn) if pn else None
                if not pn:
                    issue("판정 불가", e.sheet, e.label(), "단자 품번 미입력")
                    term_js.append(NA)
                elif t is None:
                    issue("판정 불가", e.sheet, e.label(), f"단자 품번 DB에 없음: {pn}")
                    term_js.append(NA)
                else:
                    js = []
                    js.append(NA if t.rating is None or rating is None else (OK if t.rating >= rating else NG))
                    if sq is None or t.sq_min is None or t.sq_max is None:
                        js.append(NA)
                    else:
                        js.append(OK if t.sq_min <= sq <= t.sq_max else NG)
                    if NG in js:
                        issue("단자 NG", e.sheet, e.label(),
                              f"{pn}: 정격 {t.rating}A / 수용 {t.sq_min}~{t.sq_max}sq ↔ 퓨즈 {rating}A, 전선 {sq}sq")
                    term_js.append(_worst(js))

            def name(eid):
                return "(미연결)" if eid is None else proj.elements[eid].label()

            res.wire_rows.append({
                "시트": w.sheet, "퓨즈번호": fa.get("FUSE_NO", ""), "퓨즈 용량(A)": rating,
                "회로번호": wa.get("WIRE_NO", ""), "재질": wa.get("MATERIAL", ""), "SQ": sq,
                "허용전류(A)": amp, "COLOR": wa.get("COLOR", ""), "From": name(near), "To": name(far),
                "하류 핀": " / ".join(proj.elements[x].label() for x in down),
                "하류 부하(A)": round(down_load, 3), "전선 판정": wire_j, "단자 판정": _worst(term_js),
                "_id": wid,
            })

        res.fuse_rows.append({
            "시트": f.sheet, "J/BOX": fa.get("JBOX_NO", ""), "퓨즈번호": fa.get("FUSE_NO", ""),
            "기능": fa.get("FUNCTION", ""), "전원": ptype, "용량(A)": rating,
            "연결 핀 목록": " / ".join(pin_txt), "부하 합계(A)": round(load_sum, 3) if load_ok else None,
            "경로 최소 SQ": min(sqs) if sqs else None, "퓨즈 판정": fuse_j, "_id": f.id,
        })
        if not pins:
            issue("연결 오류", f.sheet, f.label(), "퓨즈 하류에 연결된 핀 없음")

    for e in proj.elements.values():
        if e.kind == PIN and e.attrs.get("PIN_FUNC", "").upper() in POWER_FUNCS and e.id not in traced_pins:
            issue("연결 오류", e.sheet, e.label(), "퓨즈까지 추적되지 않는 전원 핀")

    return res
