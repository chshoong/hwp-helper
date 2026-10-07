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
    assert all(isinstance(d, str) for d in st["docs"]) and any(d.endswith(name) for d in st["docs"])
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


def test_memo_reports_missed_anchors(fake, monkeypatch, tmp_path):
    from hwpxkit import review as rv
    monkeypatch.setattr(live, "export", lambda out, doc=None: Path(out))
    monkeypatch.setattr(live, "_review_file", lambda path: [
        rv.Finding("오류", "weekday", "요일이 틀려요", anchor="2026.05.06.(목)"),
        rv.Finding("확인", "font-mix", "글꼴 섞임", anchor=""),
        rv.Finding("확인", "guide-text", "안내 문구", anchor="없는 글")])
    r = fake({"ok": True, "placed": 1, "missed": ["없는 글"]})
    result = live.review(memo=True)
    memos = r.calls[0]["memos"]
    assert [m["anchor"] for m in memos] == ["2026.05.06.(목)", "없는 글"]  # anchor 없는 항목은 메모로 안 단다
    assert memos[0]["text"].startswith("[검토] ")
    assert result["placed"] == 1 and result["missed"] == ["없는 글"]


@pytest.mark.hangul
def test_live_review_places_memo(live_doc, tmp_path):
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    name, _ = live_doc
    live.call("select_test", doc=name, para=1, start=0, end=0)
    live.insert("보고일: 2026.05.06.(목)\n", doc=name)
    result = live.review(doc=name, memo=True)
    assert result["placed"] >= 1
    pkg = Package.open(live.export(tmp_path / "memo.hwpx", doc=name))
    memos = [fb for fb in pkg.xml(pkg.section_names()[0]).iter(q("hp:fieldBegin")) if fb.get("type") == "MEMO"]
    assert any("요일" in "".join(t.text or "" for t in fb.iter(q("hp:t"))) for fb in memos)


def make_report(blank, tmp_path):
    from helpers import LONG, append_to_body, para
    from hwpxkit.header import Header
    from hwpxkit.package import Package
    pkg = Package.open(blank)
    big = Header(pkg).derive_charpr("0", height=1600, bold=True)
    for text, cp in (("제1장 서론", big), (LONG, "0"), ("제2장 방법", big), (LONG, "0"), (LONG, "0"),
                     ("제3장 결과", big), (LONG, "0")):
        append_to_body(pkg, para(text, char_pr=cp))
    return pkg.save(tmp_path / "r.hwpx")


def test_section_bounds_to_next_same_level(blank, tmp_path):
    start, n1, end, n2 = live.section_bounds(make_report(blank, tmp_path), "제2장")
    assert (start, n1, end, n2) == ("제2장 방법", 1, "제3장 결과", 1)


def test_section_bounds_last_chapter_runs_to_end(blank, tmp_path):
    assert live.section_bounds(make_report(blank, tmp_path), "제3장")[2] is None


def test_section_skips_toc_line(blank, tmp_path):
    """차례에 '제2장 방법 ···· 3'이 먼저 나와도 본문 제목을 고르고, 찾기 순번은 2번째 등장."""
    from helpers import append_to_body, para
    from hwpxkit.package import Package
    path = make_report(blank, tmp_path)
    pkg = Package.open(path)
    sec = pkg.edit(pkg.section_names()[0])
    toc = para("제2장 방법 ········ 3")
    sec.insert(1, toc)
    path2 = pkg.save(tmp_path / "toc.hwpx")
    start, n1, end, n2 = live.section_bounds(path2, "제2장")
    assert (start, n1) == ("제2장 방법", 2)


def test_section_unknown_heading(blank, tmp_path):
    with pytest.raises(live.LiveError, match="제목을 찾지 못했어요"):
        live.section_bounds(make_report(blank, tmp_path), "제9장")


@pytest.mark.hangul
def test_live_section_rewrite(live_doc, tmp_path):
    from hwpxkit.package import Package
    from hwpxkit.reader import to_markdown
    name, _ = live_doc
    before = to_markdown(Package.open(live.export(tmp_path / "b.hwpx", doc=name)))
    first = next(ln for ln in before.splitlines() if ln.startswith("# "))[2:]
    live.section(first.split()[0], f"# {first}\n\n□ 새로 쓴 장 내용\n○ 세부\n", doc=name)
    after = to_markdown(Package.open(live.export(tmp_path / "a.hwpx", doc=name)))
    assert "새로 쓴 장 내용" in after and after.count(first) == 1


def _tops_text(pkg):
    from hwpxkit.body import own_text
    return [own_text(p).strip() for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p")]


@pytest.mark.hangul
def test_live_section_twice_keeps_next_heading(live_doc, tmp_path):
    """장 다시 쓰기를 두 번 해도 다음 장 제목이 따로 남는다 (끼워 넣은 마지막 문단과 합쳐지던 문제)."""
    from hwpxkit.package import Package
    name, _ = live_doc
    for k in (1, 2):
        live.section("Ⅰ.", f"# Ⅰ. 다시 쓴 장\n\n□ {k}번째로 다시 쓴 내용\n○ 세부\n", doc=name)
        texts = _tops_text(Package.open(live.export(tmp_path / f"s{k}.hwpx", doc=name)))
        assert "Ⅱ. 두 번째 장 제목" in texts, k
        assert texts.count("Ⅰ. 다시 쓴 장") == 1


@pytest.mark.hangul
def test_live_replace_middle_keeps_neighbors(live_doc, tmp_path):
    """문단 가운데를 여러 줄로 바꿔도 앞뒤 글은 각자 문단으로 남고 빈 문단이 생기지 않는다."""
    from hwpxkit.package import Package
    name, _ = live_doc
    texts = _tops_text(Package.open(live.export(tmp_path / "b.hwpx", doc=name)))
    i = next(i for i, t in enumerate(texts) if t.startswith("본문 견본 문단입니다."))
    live.call("select_test", doc=name, para=i, start=5, end=12)
    live.replace("○ 끼운 첫 줄\n○ 끼운 둘째 줄\n", doc=name)
    after = _tops_text(Package.open(live.export(tmp_path / "a.hwpx", doc=name)))
    j = next(k for k, t in enumerate(after) if t.startswith("본문 견본"))
    assert after[j] == texts[i][:5].strip()
    assert after[j + 1].endswith("끼운 첫 줄") and after[j + 2].endswith("끼운 둘째 줄")
    assert after[j + 3] == texts[i][12:].strip()
