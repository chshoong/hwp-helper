"""테스트 fixture 생성: 한글로 빈 문서를 만들어 tests/fixtures/blank.hwpx로 저장한다.

한글이 설치된 Windows에서 한 번 실행하고 결과를 커밋한다.
"""
from pathlib import Path

from hwpxkit import bridge

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    out = bridge.new_blank(ROOT / "tests" / "fixtures" / "blank.hwpx")
    print(f"만들었어요: {out} ({out.stat().st_size} bytes)")
