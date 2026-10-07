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


def test_replace_without_selection_refuses(fake):
    r = fake({"ok": True, "selected": False})
    with pytest.raises(live.LiveError, match="드래그해 주세요"):
        live.replace("새 문장")
    assert [c["action"] for c in r.calls] == ["selection"]  # 바꾸기 동작은 부르지 않음


def test_replace_single_paragraph_uses_text(fake):
    r = fake({"ok": True, "selected": True, "text": "옛 문장", "para": 3, "in_table": False},
             {"ok": True})
    result = live.replace("새 **문장**")
    assert result["mode"] == "text"
    assert r.calls[1]["action"] == "replace_text"
    assert Path(r.calls[1]["text_file"]).name.endswith(".txt")


def test_markdown_block_needs_fragment():
    assert live._needs_fragment("○ 개조식 줄", 1)
    assert live._needs_fragment("| a | b |\n|---|---|\n| 1 | 2 |", 1)
    assert live._needs_fragment("첫 줄\n둘째 줄", 1)
    assert live._needs_fragment("한 줄", 2)
    assert not live._needs_fragment("그냥 한 문장", 1)


@pytest.mark.hangul
def test_live_replace_and_insert_keep_format(live_doc, tmp_path):
    from hwpxkit.body import all_text, own_text
    from hwpxkit.header import Header
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    name, _ = live_doc
    live.call("select_test", doc=name, para=1, start=0, end=2)
    assert live.replace("바뀐 글", doc=name)["mode"] == "text"
    live.insert("□ 끼워 넣은 항목\n○ 세부 내용\n\n표: 끼워 넣은 표\n| 구분 | 값 |\n|---|---|\n| 가 | 1 |\n", doc=name)
    pkg = Package.open(live.export(tmp_path / "after.hwpx", doc=name))
    texts = [own_text(p) for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p")]
    assert any("바뀐 글" in t for t in texts)
    assert any(t.endswith("끼워 넣은 항목") for t in texts)
    caps = [all_text(c) for c in pkg.xml(pkg.section_names()[0]).iter(q("hp:caption"))]
    assert any("끼워 넣은 표" in c for c in caps)
    h = Header(pkg)
    faces = {h.charpr_faces(r.get("charPrIDRef"))["HANGUL"]
             for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p") and "끼워 넣은 항목" in own_text(p)
             for r in p.findall(q("hp:run")) if r.find(q("hp:t")) is not None}
    assert faces == {"휴먼명조"}  # gov-brief 글머리 글꼴 그대로
