import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_skill_zip  # noqa: E402


def test_zip_layout(tmp_path):
    z = zipfile.ZipFile(build_skill_zip.build(tmp_path / "s.zip"))
    names = z.namelist()
    assert "hwp-helper/SKILL.md" in names and "hwp-helper/hwpx.py" in names
    assert any(n.startswith("hwp-helper/hwpxkit/") for n in names)
    assert any(n.startswith("hwp-helper/presets/rnd-report/") for n in names)
    assert any(n.startswith("hwp-helper/reference/") for n in names)


def test_zip_excludes_private_and_dev_files(tmp_path):
    names = zipfile.ZipFile(build_skill_zip.build(tmp_path / "s.zip")).namelist()
    for bad in ("private/", "tests/", "docs/", ".superpowers", "scripts/", "__pycache__", ".hwp\"", "monthly", "final"):
        assert not any(bad in n for n in names), bad


def test_zip_launcher_runs(tmp_path):
    zipfile.ZipFile(build_skill_zip.build(tmp_path / "s.zip")).extractall(tmp_path / "x")
    out = subprocess.run([sys.executable, str(tmp_path / "x" / "hwp-helper" / "hwpx.py"), "presets"],
                         capture_output=True)
    assert out.returncode == 0 and "rnd-report" in out.stdout.decode("utf-8")


def test_zip_docs_have_no_plugin_root_variable(tmp_path):
    """claude.ai에는 CLAUDE_PLUGIN_ROOT가 없다 (최종 리뷰)."""
    z = zipfile.ZipFile(build_skill_zip.build(tmp_path / "s.zip"))
    for n in z.namelist():
        if n.endswith(".md"):
            assert "CLAUDE_PLUGIN_ROOT" not in z.read(n).decode("utf-8"), n
