"""claude.ai 업로드용 스킬 zip: hwpx-report/{SKILL.md, reference/, hwpx.py, hwpxkit/, presets/}.

사용: python scripts/build_skill_zip.py  → dist/hwpx-report-skill.zip
개인 문서(private/)·테스트·문서·개발 파일은 넣지 않는다.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "hwpx-report"


def _files():
    skill = ROOT / "skills" / "hwpx-report"
    yield skill / "SKILL.md", "SKILL.md"
    for f in sorted((skill / "reference").glob("*.md")):
        yield f, f"reference/{f.name}"
    yield ROOT / "hwpx.py", "hwpx.py"
    for f in sorted((ROOT / "hwpxkit").rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".ps1"):
            yield f, f"hwpxkit/{f.relative_to(ROOT / 'hwpxkit').as_posix()}"
    for f in sorted((ROOT / "presets").rglob("*")):
        if f.is_file():
            yield f, f"presets/{f.relative_to(ROOT / 'presets').as_posix()}"


def build(dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in _files():
            if src.suffix == ".md":  # claude.ai에는 CLAUDE_PLUGIN_ROOT가 없다 → SKILL.md가 있는 폴더
                text = src.read_text(encoding="utf-8")
                text = text.replace('"${CLAUDE_PLUGIN_ROOT}/hwpx.py"', "<스킬 폴더>/hwpx.py")
                z.writestr(f"{TOP}/{arc}", text.replace("${CLAUDE_PLUGIN_ROOT}", "<스킬 폴더>"))
            else:
                z.write(src, f"{TOP}/{arc}")
    return dst


if __name__ == "__main__":
    out = build(ROOT / "dist" / "hwpx-report-skill.zip")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"만들었어요: {out} ({out.stat().st_size // 1024} KB)")
