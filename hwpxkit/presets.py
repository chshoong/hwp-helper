"""프리셋 목록과 경로. 프리셋은 presets/<이름>/template.hwpx (scripts/build_presets.py로 제작)."""
from __future__ import annotations

import json
from pathlib import Path

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"


def listing() -> list[dict]:
    return json.loads((PRESETS_DIR / "presets.json").read_text(encoding="utf-8"))


def path(name: str) -> Path:
    names = [p["name"] for p in listing()]
    if name not in names:
        raise ValueError(f"'{name}' 프리셋이 없어요. 가능한 프리셋: {', '.join(names)}")
    return PRESETS_DIR / name / "template.hwpx"
