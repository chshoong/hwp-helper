import json
import re
from pathlib import Path

import pytest

from hwpxkit.cli import _parser

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "hwpx-report"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name}: 머리말 없음"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


def test_plugin_and_marketplace_json():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "hwpx-report" and plugin["version"] and plugin["description"]
    assert market["name"] and market["owner"]["name"]
    assert market["plugins"] == [{"name": "hwpx-report", "source": "./", "description": plugin["description"]}]


def test_skill_frontmatter_and_references():
    fm = frontmatter(SKILL / "SKILL.md")
    assert fm["name"].strip() == "hwpx-report" and "한글" in fm["description"]
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for ref in re.findall(r"reference/([\w-]+\.md)", body):
        assert (SKILL / "reference" / ref).is_file(), ref
    assert "${CLAUDE_PLUGIN_ROOT}/hwpx.py" in body


@pytest.mark.parametrize("name", ["hwp-write", "hwp-fill", "hwp-review", "hwp-convert"])
def test_commands(name):
    path = ROOT / "commands" / f"{name}.md"
    fm = frontmatter(path)
    assert fm["description"].strip()
    assert "$ARGUMENTS" in path.read_text(encoding="utf-8")


def test_documented_commands_exist():
    """SKILL.md·reference에 적은 'hwpx.py <명령>'이 실제 CLI에 있어야 한다."""
    real = set(_parser()._subparsers._group_actions[0].choices)
    docs = [SKILL / "SKILL.md", *sorted((SKILL / "reference").glob("*.md"))]
    used = {m for d in docs for m in re.findall(r"hwpx\.py\"?\s+([a-z]+)", d.read_text(encoding="utf-8"))}
    assert used and used <= real, used - real


def test_documented_options_exist():
    text = "\n".join(p.read_text(encoding="utf-8") for p in [SKILL / "SKILL.md", *(SKILL / "reference").glob("*.md")])
    for opt in set(re.findall(r"(--[a-z]+)", text)):
        assert opt in ("--anchors", "--json", "--mode", "--replace", "--preview", "--user", "--fit"), opt
