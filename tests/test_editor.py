"""앱 안 편집 화면(edit): 문서 모델, 부탁 목록, 서버, CLI."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from helpers import LONG, SECTION, append_to_body, para, table
from hwpxkit.body import own_text
from hwpxkit.ns import q
from hwpxkit.package import Package


def make_doc(blank, tmp_path, name="보고서.hwpx"):
    """제목·본문·표가 있는 시험 문서. 0번 문단은 빈 문서의 구역 설정 문단."""
    pkg = Package.open(blank)
    append_to_body(pkg, para("□ 제1장. 데이터 이해"))
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("둘째 본문 문단이며 " + LONG))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "창고", (0, 1): "기간", (1, 0): "A", (1, 1): "6개월"}))
    append_to_body(pkg, para("셋째 본문 문단이며 " + LONG))
    return pkg.save(tmp_path / name)


def tops(path):
    pkg = Package.open(path)
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def test_start_makes_copy_and_keeps_original(blank, tmp_path):
    from hwpxkit.editor import EditDoc, copy_path
    src = make_doc(blank, tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    d = EditDoc(src)
    assert d.path == copy_path(src) == tmp_path / "보고서_수정.hwpx"
    assert d.path.exists() and d.version == 1
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_existing_copy_is_reused(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.edit_para(1, 2, "고친 문단")
    again = EditDoc(src)
    assert any(b.get("text") == "고친 문단" for b in again.doc()["blocks"])


def test_doc_blocks_roles_and_table(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    out = d.doc()
    assert out["version"] == 1 and out["name"] == "보고서_수정.hwpx" and out["external_change"] is False
    by_i = {b["i"]: b for b in out["blocks"]}
    assert by_i[1]["kind"] == "para" and by_i[1]["text"] == "□ 제1장. 데이터 이해"
    assert by_i[2]["role"] == "body" and by_i[2]["size"] == 10.0 and by_i[2]["bold"] is False
    tbl = by_i[4]
    assert tbl["kind"] == "table"
    assert [[c["text"] for c in row] for row in tbl["rows"]] == [["창고", "기간"], ["A", "6개월"]]
    assert tbl["rows"][1][1] == {"r": 1, "c": 1, "text": "6개월", "rs": 1, "cs": 1}


def test_edit_para_keeps_formats(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    before = tops(d.path)[2]
    v = d.edit_para(1, 2, "새로 쓴 문단")
    after = tops(d.path)[2]
    assert v == 2 == d.version
    assert own_text(after) == "새로 쓴 문단"
    assert after.get("paraPrIDRef") == before.get("paraPrIDRef")
    assert after.find(q("hp:run")).get("charPrIDRef") == before.find(q("hp:run")).get("charPrIDRef")
    assert next(after.iter(q("hp:linesegarray")), None) is None


def test_edit_merges_mixed_runs_into_first(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    from hwpxkit.header import Header
    pkg = Package.open(blank)
    p = para("앞 글 ")
    bold = Header(pkg).derive_charpr("0", bold=True)
    run = p.makeelement(q("hp:run"), {"charPrIDRef": bold})
    t = run.makeelement(q("hp:t"), {})
    t.text = "굵은 글"
    run.append(t)
    p.append(run)
    append_to_body(pkg, p)
    d = EditDoc(pkg.save(tmp_path / "섞임.hwpx"))
    assert next(b for b in d.doc()["blocks"] if b["i"] == 1)["mixed"] is True
    d.edit_para(1, 1, "하나로")
    p1 = tops(d.path)[1]
    assert [own_text(p1)] == ["하나로"] and len(p1.findall(q("hp:run"))) == 1


def test_edit_keeps_section_controls(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    d.edit_para(1, 0, "첫 문단 글")
    p0 = tops(d.path)[0]
    assert own_text(p0) == "첫 문단 글" and next(p0.iter(q("hp:secPr")), None) is not None


def test_edit_refuses_object_only(blank, tmp_path):
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(make_doc(blank, tmp_path))
    with pytest.raises(EditError) as e:
        d.edit_para(1, 4, "표 문단")
    assert e.value.status == 400 and "표·그림" in str(e.value)


def test_edit_refuses_newline_and_stale_version(blank, tmp_path):
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(make_doc(blank, tmp_path))
    with pytest.raises(EditError, match="부탁하기") as e:
        d.edit_para(1, 2, "두\n줄")
    assert e.value.status == 400
    d.edit_para(1, 2, "한 번")
    with pytest.raises(EditError) as e:
        d.edit_para(1, 2, "옛 판에서")
    assert e.value.status == 409


def test_edit_cell(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    d.edit_cell(1, 4, 1, 1, "12개월\n(연장)")
    tbl = next(b for b in d.doc()["blocks"] if b["i"] == 4)
    assert tbl["rows"][1][1]["text"] == "12개월\n(연장)"


def test_undo_and_history_limit(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc, EditError
    from hwpxkit.editor import doc as docmod
    monkeypatch.setattr(docmod, "HISTORY_KEEP", 3)
    d = EditDoc(make_doc(blank, tmp_path))
    for k in range(5):
        d.edit_para(d.version, 2, f"판 {k}")
    assert len(list(d.history_dir.glob("*.hwpx"))) == 3
    d.undo()
    assert own_text(tops(d.path)[2]) == "판 3" and d.version == 7
    for _ in range(2):
        d.undo()
    with pytest.raises(EditError, match="되돌릴"):
        d.undo()


def test_external_change_detected(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    pkg = Package.open(d.path)
    _p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
    _p.find(q("hp:run")).find(q("hp:t")).text = "한글에서 고침"
    tmp = pkg.save(tmp_path / "x.hwpx")
    time.sleep(0.05)
    tmp.replace(d.path)
    out = d.doc()
    assert out["external_change"] is True and out["version"] == 2
    assert d.doc()["external_change"] is False


def test_locked_copy_is_not_damaged(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc, EditError
    from hwpxkit.editor import doc as docmod
    d = EditDoc(make_doc(blank, tmp_path))
    before = d.path.read_bytes()

    def locked(*a, **k):
        raise PermissionError("locked")
    monkeypatch.setattr(docmod, "_replace", locked)
    with pytest.raises(EditError) as e:
        d.edit_para(1, 2, "막힘")
    assert e.value.status == 423 and "한글에서" in str(e.value)
    assert d.path.read_bytes() == before and d.version == 1
    assert list(d.history_dir.glob("*.hwpx")) == []


def test_queue_add_and_status(tmp_path):
    from hwpxkit.editor import AskQueue
    qu = AskQueue.for_copy(tmp_path / "보고서_수정.hwpx")
    assert qu.path == tmp_path / "보고서_수정.부탁.jsonl"
    a = qu.add(3, 2, 4, ["가", "나"], "두 줄로 줄여줘")
    b = qu.add(3, 5, 6, ["다"], "표로 바꿔줘")
    assert (a["id"], b["id"], a["status"]) == ("a1", "a2", "pending")
    qu.set("a1", "done")
    again = AskQueue.for_copy(tmp_path / "보고서_수정.hwpx")
    assert [x["status"] for x in again.all()] == ["done", "pending"]
    assert again.get("a2")["text"] == "표로 바꿔줘"
    with pytest.raises(KeyError):
        again.get("a9")


def test_locate_same_place():
    from hwpxkit.editor.queue import locate
    assert locate(["x", "가", "나", "y"], {"start": 1, "end": 3, "texts": ["가", "나"]}) == (1, 3)


def test_locate_shifted():
    from hwpxkit.editor.queue import locate
    assert locate(["x", "새", "가", "나", "y"], {"start": 1, "end": 3, "texts": ["가", "나"]}) == (2, 4)


def test_locate_ambiguous_or_missing():
    from hwpxkit.editor.queue import locate
    ask = {"start": 1, "end": 2, "texts": ["가"]}
    assert locate(["x", "바뀜", "가", "가"], ask) is None
    assert locate(["x", "없음"], ask) is None


def _ask(d, start, end, text="두 줄로 줄여줘"):
    from hwpxkit.editor import AskQueue
    qu = AskQueue.for_copy(d.path)
    return qu, d.ask(qu, d.version, start, end, text)


def test_ask_records_texts_and_refuses_bad_range(blank, tmp_path):
    from hwpxkit.editor import EditError
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 4)
    assert a["texts"] == [LONG, "둘째 본문 문단이며 " + LONG] and a["version"] == 1
    with pytest.raises(EditError, match="첫 문단"):
        d.ask(qu, d.version, 0, 2, "x")
    with pytest.raises(EditError, match="범위"):
        d.ask(qu, d.version, 3, 3, "x")


def test_range_markdown(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    md = d.range_markdown(2, 4)
    assert LONG in md and "둘째 본문" in md and "제1장" not in md and "셋째" not in md


def test_apply_replaces_range(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 4)
    r = d.apply(qu, a["id"], "줄인 문단 하나로 정리한 결과 문장이며 길이를 맞추기 위해 조금 더 씀\n", tmp_path)
    assert r["status"] == "done" and r["version"] == 2
    texts = d.texts()
    assert "줄인 문단 하나로" in texts[2] and texts[3].startswith("창고")
    assert qu.get(a["id"])["status"] == "done"


def test_apply_after_shift(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 5, 6)
    d.edit_para(d.version, 2, "앞 문단을 고침")
    def add_para(pkg):
        root = pkg.edit(SECTION)
        ps = [p for p in root if p.tag == q("hp:p")]
        root.insert(root.index(ps[1]) + 1, para("끼운 문단"))
    d.write(add_para)
    assert d.apply(qu, a["id"], "바뀐 셋째 문단\n", tmp_path)["status"] == "done"
    assert "바뀐 셋째 문단" in d.texts()[-1]


def test_apply_stale_keeps_copy(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 3)
    d.edit_para(d.version, 2, "완전히 다른 글")
    before = d.path.read_bytes()
    r = d.apply(qu, a["id"], "새 글\n", tmp_path)
    assert r["status"] == "stale" and "바뀌" in r["message"]
    assert d.path.read_bytes() == before and qu.get(a["id"])["status"] == "stale"


def test_apply_render_error_keeps_copy(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc
    from hwpxkit.editor import doc as docmod
    from hwpxkit.render import RenderError
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 3)
    before = d.path.read_bytes()

    def boom(*a, **k):
        raise RenderError("그림 파일을 찾을 수 없어요: 없음.png")
    monkeypatch.setattr(docmod, "render_into", boom)
    r = d.apply(qu, a["id"], "![x](없음.png)\n", tmp_path)
    assert r["status"] == "error" and "없음.png" in r["message"]
    assert d.path.read_bytes() == before and d.version == 1
