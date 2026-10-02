"""DWG ↔ DXF 변환 래퍼 (외부 도구: ODA File Converter).

ODA File Converter 는 별도 설치가 필요하며 사내 사용 라이선스 확인이 필요하다.
Windows 에서 기본 설치 경로가 아니면 ezdxf 설정(odafc-addon / win_exec_path)으로 지정한다.
대안: GstarCAD 에서 직접 DXF 로 저장(SAVEAS)해도 된다.
"""
from __future__ import annotations

from pathlib import Path

from ezdxf.addons import odafc


def is_available() -> bool:
    return odafc.is_installed()


def convert_folder(src_dir: str | Path, dst_dir: str | Path, to: str, version: str = "R2018") -> list[Path]:
    """폴더 단위 일괄 변환. to = 'dxf' 또는 'dwg'. 하위 폴더(OLD 등)는 제외."""
    if not odafc.is_installed():
        raise RuntimeError("ODA File Converter 가 설치되어 있지 않음 → 설치하거나 GstarCAD 에서 DXF 로 저장하세요")
    src_ext = ".dwg" if to == "dxf" else ".dxf"
    dst = Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    done = []
    for p in sorted(Path(src_dir).iterdir()):
        if p.is_file() and p.suffix.lower() == src_ext:
            target = dst / (p.stem + "." + to)
            odafc.convert(p, target, version=version, replace=True)
            done.append(target)
    return done
