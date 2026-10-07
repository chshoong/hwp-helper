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


@pytest.fixture
def live_doc(tmp_path_factory):
    """사람이 연 것처럼 시험 문서를 한글로 연다(문서 이름 고유). 끝나면 그 문서만 닫는다."""
    import subprocess as sp
    import time
    from hwpxkit import live
    from hwpxkit.presets import path as preset_path
    folder = tmp_path_factory.mktemp("live")
    name = f"livetest_{int(time.time() * 1000)}.hwpx"
    doc = folder / name
    shutil.copyfile(preset_path("gov-brief"), doc)
    before = _hwp_pids()
    sp.Popen([str(live.hwp_exe()), str(doc)])
    for _ in range(40):
        time.sleep(0.5)
        try:
            if any(name in d for d in live.status()["docs"]):
                break
        except live.LiveError:
            pass
    yield name, doc
    try:
        live.call("close_doc", doc=name)
    except live.LiveError:
        pass
    for _ in range(30):  # 이 시험이 띄운 한글이 완전히 꺼질 때까지 (다음 시험이 꺼지는 한글에 붙지 않도록)
        if not (_hwp_pids() - before):
            break
        time.sleep(0.5)
    for pid in _hwp_pids() - before:  # 창을 닫아도 숨은 채 남는 경우: 이 시험이 띄운 한글만 끈다
        sp.run(["taskkill", "/PID", pid, "/F"], capture_output=True)


def _hwp_pids() -> set:
    import subprocess as sp
    out = sp.run(["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/FO", "CSV", "/NH"], capture_output=True).stdout
    return {line.split('","')[1] for line in out.decode("cp949", errors="replace").splitlines() if '","' in line}
