import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_launcher_runs_from_copied_plugin_with_korean_path(tmp_path):
    dst = tmp_path / "플러그인 폴더 (테스트)"
    dst.mkdir()
    shutil.copy(ROOT / "hwpx.py", dst / "hwpx.py")
    shutil.copytree(ROOT / "hwpxkit", dst / "hwpxkit", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "presets", dst / "presets")
    out = subprocess.run([sys.executable, str(dst / "hwpx.py"), "presets", "--json"], capture_output=True,
                         cwd=tmp_path, env={"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert "rnd-report" in out.stdout.decode("utf-8")
