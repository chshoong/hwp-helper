import json
import subprocess
from pathlib import Path

import pytest

from hwpxkit import bridge, live


class FakeRunner:
    """ps1 대신 정해 둔 JSON을 돌려주고, 받은 인자를 기록한다."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd, capture_output=True, timeout=None):
        args = json.loads(Path(cmd[cmd.index("-ArgsFile") + 1]).read_text(encoding="utf-8"))
        self.calls.append(args)
        out = json.dumps(self.results.pop(0), ensure_ascii=False).encode("utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=b"")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: True)

    def install(*results):
        runner = FakeRunner(*results)
        monkeypatch.setattr(live, "_runner", runner)
        return runner
    return install


def test_status_passes_action_and_doc(fake):
    r = fake({"ok": True, "docs": ["C:/a/보고서.hwp"], "active": "C:/a/보고서.hwp", "modified": True,
              "selection": False})
    st = live.status(doc="보고서")
    assert r.calls[0]["action"] == "status" and r.calls[0]["doc"] == "보고서"
    assert st["active"].endswith("보고서.hwp") and st["modified"] is True


def test_status_not_running_message(fake):
    fake({"ok": False, "error": "not_running"})
    with pytest.raises(live.LiveError, match="한글에서 문서를 연 뒤"):
        live.status()


def test_doc_ambiguous_message(fake):
    fake({"ok": False, "error": "doc_ambiguous", "docs": ["C:/a/보고서1.hwp", "C:/a/보고서2.hwp"]})
    with pytest.raises(live.LiveError, match="보고서1.hwp.*보고서2.hwp"):
        live.status(doc="보고서")


def test_doc_not_found_message(fake):
    fake({"ok": False, "error": "doc_not_found", "docs": ["C:/a/계획서.hwp"]})
    with pytest.raises(live.LiveError, match="열린 문서: 계획서.hwp"):
        live.status(doc="보고서")


def test_selection_counts_paragraphs(fake):
    fake({"ok": True, "selected": True, "text": "첫 줄\r\n둘째 줄\r\n", "para": 7, "in_table": False})
    sel = live.selection()
    assert sel["paragraphs"] == 2 and sel["text"] == "첫 줄\n둘째 줄"


def test_no_hangul_environment(monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: False)
    with pytest.raises(bridge.BridgeError, match="Windows에서만"):
        live.status()


@pytest.mark.hangul
def test_live_status_selection_export(live_doc, tmp_path):
    from hwpxkit.package import Package
    from hwpxkit.reader import to_markdown
    name, _ = live_doc
    st = live.status(doc=name)
    assert st["active"].endswith(name)
    live.call("select_test", doc=name, para=1, start=0, end=4)
    sel = live.selection(doc=name)
    assert sel["selected"] and sel["paragraphs"] == 1 and len(sel["text"]) == 4
    out = live.export(tmp_path / "screen.hwpx", doc=name)
    assert "견본" in to_markdown(Package.open(out))
    assert live.status(doc=name)["active"].endswith(name)  # 내보내기 뒤에도 창의 문서 경로 그대로
