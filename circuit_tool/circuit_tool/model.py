"""회로 데이터 모델 — 유일한 원본(Single Source of Truth).

DXF/DWG 는 입출력 형식일 뿐이며, 검증·CSV·도면 출력은 모두 이 모델에서 만든다.
이 모듈은 다른 모듈에 의존하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 요소 종류
FUSE = "FUSE"
BOX_TERMINAL = "BOX_TERMINAL"
SPLICE = "SPLICE"
INLINE = "INLINE"
PIN = "PIN"
SHEET_REF = "SHEET_REF"
WIRE = "WIRE"

# 종류별 속성 (블록 ATTRIB 태그와 동일)
ATTR_TAGS: dict[str, list[str]] = {
    FUSE: ["JBOX_NO", "FUSE_NO", "FUNCTION", "RATING", "PWR_TYPE"],
    BOX_TERMINAL: ["BOX", "TERMINAL_NO", "TERMINAL_PN"],
    SPLICE: ["SPLICE_NO"],
    INLINE: ["CONN_NAME", "PIN_NO", "TERMINAL_PN"],
    PIN: ["DEVICE", "CONN", "PIN_NO", "PIN_FUNC", "LOAD_CURRENT", "TERMINAL_PN"],
    SHEET_REF: ["LINK_ID", "TARGET_SHEET", "TARGET_DEVICE", "TARGET_CONN", "TARGET_PIN", "DIRECTION"],
    WIRE: ["WIRE_NO", "MATERIAL", "SQ", "COLOR", "ENV"],
}

POWER_FUNCS = {"B+", "IG", "ACC"}
PIN_FUNCS = POWER_FUNCS | {"GND", "SIG"}

# 추적 시 통과하는 요소 (요구사항 6장)
PASS_THROUGH = {BOX_TERMINAL, SPLICE, INLINE, SHEET_REF}
# 단자 품번을 갖는 요소 (단자 판정 대상)
TERMINAL_KINDS = {BOX_TERMINAL, INLINE, PIN}


@dataclass
class Geometry:
    """원래 도형 정보. 내보내기 시 handle 로 원본 엔티티를 찾아 값만 바꾼다."""
    handle: str | None
    layer: str = ""
    points: list[list[float]] = field(default_factory=list)
    block: str | None = None


@dataclass
class Sheet:
    id: str                 # 파일명(확장자 제외)
    drawing_no: str
    vehicle: str
    sheet_no: str | None
    sheet_total: str | None
    name: str
    rev: str
    source: str = ""        # 가져온 DXF 경로


@dataclass
class Element:
    id: str
    sheet: str
    kind: str
    attrs: dict[str, str]
    geom: Geometry

    def label(self) -> str:
        a = self.attrs
        if self.kind == FUSE:
            return f"{a.get('FUSE_NO', '?')}"
        if self.kind == PIN:
            return f"{a.get('DEVICE', '?')} {a.get('CONN', '')}-{a.get('PIN_NO', '?')}".replace(" -", " ")
        if self.kind == BOX_TERMINAL:
            return f"{a.get('BOX', '')} {a.get('TERMINAL_NO', '?')}".strip()
        if self.kind == SPLICE:
            return f"SPLICE {a.get('SPLICE_NO', '?')}"
        if self.kind == INLINE:
            return f"{a.get('CONN_NAME', '?')}-{a.get('PIN_NO', '?')}"
        if self.kind == SHEET_REF:
            return f"REF {a.get('LINK_ID', '?')}"
        return self.id


@dataclass
class Wire:
    """전선 구간: 두 접속 요소 사이의 선(꺾임 포함) 하나."""
    id: str
    sheet: str
    attrs: dict[str, str]
    ends: list[str | None]                  # 양 끝 요소 id (None = 미연결)
    segments: list[list[list[float]]]       # [[x1,y1],[x2,y2]] 목록
    handles: list[str]                      # 선 엔티티 handle
    label_handle: str | None = None         # 전선 라벨 블록 handle (속성 내보내기 대상)


@dataclass
class Issue:
    type: str
    sheet: str
    location: str
    message: str


@dataclass
class Project:
    sheets: dict[str, Sheet] = field(default_factory=dict)
    elements: dict[str, Element] = field(default_factory=dict)
    wires: dict[str, Wire] = field(default_factory=dict)
    links: list[list[str]] = field(default_factory=list)   # 같은 점에 놓여 직접 연결된 요소 쌍
    issues: list[Issue] = field(default_factory=list)      # 가져오기 단계 오류
    display: dict[str, dict] = field(default_factory=dict)  # 시트별 화면 표시용 도형

    # ---- 저장/불러오기 (JSON) ----
    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            sheets={k: Sheet(**v) for k, v in d["sheets"].items()},
            elements={k: Element(**{**v, "geom": Geometry(**v["geom"])}) for k, v in d["elements"].items()},
            wires={k: Wire(**v) for k, v in d["wires"].items()},
            links=d.get("links", []),
            issues=[Issue(**i) for i in d.get("issues", [])],
            display=d.get("display", {}),
        )

    def item(self, item_id: str) -> Element | Wire | None:
        return self.elements.get(item_id) or self.wires.get(item_id)


def to_float(text: str | None) -> float | None:
    """숫자 해석. 실패하면 None (추정하지 않는다)."""
    if text is None:
        return None
    t = str(text).strip().upper().removesuffix("A").removesuffix("SQ").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None
