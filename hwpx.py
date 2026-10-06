"""hwpx-report 엔진 실행기. 플러그인 루트나 claude.ai 스킬 폴더 어디에 있어도 같은 폴더의 hwpxkit을 쓴다.

사용: python hwpx.py <명령> ...   (명령 목록: python hwpx.py -h)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hwpxkit.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
