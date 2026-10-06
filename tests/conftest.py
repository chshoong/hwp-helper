import json
import shutil
from pathlib import Path

import pytest

from hwpxkit import bridge

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PRIVATE = ROOT / "private"


@pytest.fixture
def blank(tmp_path) -> Path:
    """한글이 만든 빈 문서의 복사본 (테스트가 마음대로 고쳐도 됨)."""
    dst = tmp_path / "blank.hwpx"
    shutil.copy(FIXTURES / "blank.hwpx", dst)
    return dst


@pytest.fixture
def private_dir() -> Path:
    """사용자 실제 문서 폴더. 없으면(다른 PC, CI) 테스트를 건너뛴다."""
    if not (PRIVATE / "monthly.hwpx").exists():
        pytest.skip("private/ 실제 문서 없음")
    return PRIVATE


@pytest.fixture
def expected(private_dir) -> dict:
    """실제 문서 테스트의 기대 문자열 (private/expected.json, 저장소에 넣지 않음). 없으면 건너뛴다."""
    path = private_dir / "expected.json"
    if not path.exists():
        pytest.skip("private/expected.json 없음")
    return json.loads(path.read_text(encoding="utf-8"))


def pytest_collection_modifyitems(config, items):
    if bridge.available():
        return
    skip = pytest.mark.skip(reason="한글(한컴오피스)이 설치되어 있지 않음")
    for item in items:
        if "hangul" in item.keywords:
            item.add_marker(skip)
