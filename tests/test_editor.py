"""앱 안 편집 화면(edit): 문서 모델, 부탁 목록, 서버, CLI."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
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


@pytest.fixture
def server(blank, tmp_path):
    from hwpxkit.editor import AskQueue, EditDoc
    from hwpxkit.editor.server import make_server
    d = EditDoc(make_doc(blank, tmp_path))
    srv = make_server(d, AskQueue.for_copy(d.path), "열쇠", base_dir=tmp_path)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, d
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, key="열쇠"):
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Key": urllib.parse.quote(key), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_server_rejects_wrong_key(server):
    srv, _ = server
    assert call(srv, "GET", "/api/doc", key="틀림")[0] == 403
    assert call(srv, "GET", "/", key="틀림")[0] == 403


def test_server_page_with_key_in_query(server):
    srv, _ = server
    with urllib.request.urlopen(srv.url, timeout=10) as r:
        assert r.status == 200 and "한글 편집" in r.read().decode("utf-8")


def test_server_edit_flow(server):
    srv, d = server
    st, doc = call(srv, "GET", "/api/doc")
    assert st == 200 and doc["version"] == 1
    st, r = call(srv, "POST", "/api/edit", {"version": 1, "i": 2, "text": "서버로 고침"})
    assert st == 200 and r["version"] == 2
    assert call(srv, "POST", "/api/edit", {"version": 1, "i": 2, "text": "옛 판"})[0] == 409
    st, r = call(srv, "POST", "/api/edit", {"version": 2, "i": 4, "r": 0, "c": 0, "text": "창고명"})
    assert st == 200
    st, r = call(srv, "POST", "/api/undo", {})
    assert st == 200 and r["version"] == 4


def test_server_ask_and_apply(server):
    srv, d = server
    st, a = call(srv, "POST", "/api/ask", {"version": 1, "start": 2, "end": 3, "text": "줄여줘"})
    assert st == 200 and a["id"] == "a1"
    st, asks = call(srv, "GET", "/api/asks")
    assert [x["status"] for x in asks["asks"]] == ["pending"]
    st, r = call(srv, "POST", "/api/apply", {"id": "a1", "md": "줄인 결과 문장입니다\n"})
    assert st == 200 and r["status"] == "done"
    assert "줄인 결과" in d.texts()[2]


def test_server_bad_json_is_400(server):
    srv, _ = server
    st, r = call(srv, "POST", "/api/edit", {"version": 1})
    assert st == 400 and r["error"]


def test_idle_shutdown(blank, tmp_path):
    from hwpxkit.editor import AskQueue, EditDoc
    from hwpxkit.editor.server import make_server, watch_idle
    d = EditDoc(make_doc(blank, tmp_path))
    srv = make_server(d, AskQueue.for_copy(d.path), "k", idle=0.3)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    watch_idle(srv, every=0.1)
    th.join(timeout=5)
    assert not th.is_alive()
    srv.server_close()


def _cli(*args):
    from hwpxkit.cli import main
    return main(["edit", *map(str, args)])


def test_cli_asks_and_apply_without_server(blank, tmp_path, capsys):
    from hwpxkit.editor import AskQueue, EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.ask(AskQueue.for_copy(d.path), 1, 2, 3, "줄여줘")
    assert _cli("asks", src, "--json") == 0
    asks = json.loads(capsys.readouterr().out)
    assert asks[0]["id"] == "a1" and LONG in asks[0]["markdown"]
    md = tmp_path / "새.md"
    md.write_text("CLI로 바꾼 문장입니다\n", encoding="utf-8")
    assert _cli("apply", src, "a1", md) == 0
    assert "반영했어요" in capsys.readouterr().out
    assert "CLI로 바꾼" in EditDoc(src).texts()[2]


def test_cli_apply_stale_exit_1(blank, tmp_path, capsys):
    from hwpxkit.editor import AskQueue, EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.ask(AskQueue.for_copy(d.path), 1, 2, 3, "줄여줘")
    d.edit_para(d.version, 2, "딴 글")
    md = tmp_path / "새.md"
    md.write_text("새 글\n", encoding="utf-8")
    assert _cli("apply", src, "a1", md) == 1
    assert "다시 확인" in capsys.readouterr().out


def test_start_serve_stop(blank, tmp_path, capsys):
    src = make_doc(blank, tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    try:
        assert _cli("start", src) == 0
        out = capsys.readouterr().out
        url = out.splitlines()[0].split(": ", 1)[1]
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
    finally:
        assert _cli("stop", src) == 0
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    assert not (tmp_path / "보고서_수정.서버.json").exists()


def test_start_reuses_running_server(blank, tmp_path, capsys):
    src = make_doc(blank, tmp_path)
    try:
        _cli("start", src)
        first = capsys.readouterr().out.splitlines()[0]
        _cli("start", src)
        assert capsys.readouterr().out.splitlines()[0] == first
    finally:
        _cli("stop", src)


def test_page_is_self_contained_and_uses_api():
    html = (Path(__file__).parents[1] / "hwpxkit" / "editor" / "page.html").read_text(encoding="utf-8")
    assert "http://" not in html.replace("http://127.0.0.1", "") and "https://" not in html
    for api in ("/api/doc", "/api/edit", "/api/ask", "/api/asks", "/api/undo", "/api/pages", "X-Key"):
        assert api in html, api
    for word in ("고치기", "부탁하기", "되돌리기", "쪽 모양 확인"):
        assert word in html, word


def test_server_leaves_no_temp_dirs(blank, tmp_path, monkeypatch):
    """서버를 켜고 끌 때 쪽 그림용 임시 폴더를 남기지 않는다 (쪽 그림을 만들 때만 만든다)."""
    import tempfile as tf
    from hwpxkit.editor import AskQueue, EditDoc
    from hwpxkit.editor.server import make_server
    monkeypatch.setattr(tf, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    d = EditDoc(make_doc(blank, tmp_path))
    srv = make_server(d, AskQueue.for_copy(d.path), "k")
    srv.server_close()
    assert list((tmp_path / "tmp").iterdir()) == []


@pytest.mark.hangul
def test_server_pages_with_hangul(server):
    srv, _ = server
    st, r = call(srv, "POST", "/api/pages", {})
    assert st == 200 and r["pages"] and r["pages"][0].startswith("/pages/")
    st, png = call(srv, "GET", r["pages"][0])
    assert st == 200 and png[:4] == b"\x89PNG"


def test_skill_documents_edit():
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "editor.md").read_text(encoding="utf-8")
    for cmd in ("edit start", "edit watch", "edit asks", "edit apply", "edit stop"):
        assert cmd in text, cmd
    assert "reference/editor.md" in (root / "SKILL.md").read_text(encoding="utf-8")


# ---- 최종 리뷰 반영 ----

def test_undo_after_restart_restores_latest(blank, tmp_path):
    """C1: 서버를 다시 켜도(새 EditDoc) 되돌리기는 바로 앞 상태로 간다."""
    from hwpxkit.editor import EditDoc
    src = make_doc(blank, tmp_path)
    d1 = EditDoc(src)
    for k in range(3):
        d1.edit_para(d1.version, 2, f"첫 세션 {k}")
    d2 = EditDoc(src)
    d2.edit_para(d2.version, 2, "둘째 세션")
    d2.undo(d2.version)
    assert own_text(tops(d2.path)[2]) == "첫 세션 2"
    d2.undo(d2.version)
    assert own_text(tops(d2.path)[2]) == "첫 세션 1"


def test_cli_asks_uses_current_range(blank, tmp_path, capsys):
    """C2: 앞 부탁을 반영해 문단 수가 바뀌어도 뒤 부탁의 마크다운은 지금 자리에서 읽는다."""
    from hwpxkit.editor import AskQueue, EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    qu = AskQueue.for_copy(d.path)
    d.ask(qu, 1, 2, 3, "늘려줘")
    d.ask(qu, 1, 5, 6, "셋째를 줄여줘")
    d.apply(qu, "a1", "늘린 문단 하나\n\n늘린 문단 둘\n\n늘린 문단 셋\n", tmp_path)
    assert _cli("asks", src, "--json") == 0
    asks = json.loads(capsys.readouterr().out)
    assert [a["id"] for a in asks] == ["a2"] and "셋째 본문" in asks[0]["markdown"]


def _nested_doc(blank, tmp_path):
    pkg = Package.open(blank)
    outer = append_to_body(pkg, table(2, 2, texts={(1, 0): "바깥", (1, 1): "칸"}))
    inner = table(2, 2, texts={(1, 0): "안쪽"})
    first_cell = next(outer.iter(q("hp:tc")))
    first_cell.find(q("hp:subList")).append(inner)
    append_to_body(pkg, para(LONG))
    return pkg.save(tmp_path / "겹표.hwpx")


def test_edit_cell_ignores_nested_table(blank, tmp_path):
    """C3: 바깥 표 칸을 고치면 안쪽 표가 아니라 바깥 칸이 바뀐다."""
    from hwpxkit.editor import EditDoc
    d = EditDoc(_nested_doc(blank, tmp_path))
    d.edit_cell(1, 1, 1, 0, "고친 바깥")
    from hwpxkit.body import all_text
    p = tops(d.path)[1]
    assert "고친 바깥" in all_text(p) and "안쪽" in all_text(p)


def test_edit_cell_keeps_objects_in_cell(blank, tmp_path):
    """C3: 칸 안에 표·그림 문단이 있으면 그 칸 글 고치기가 개체를 지우지 않는다."""
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(_nested_doc(blank, tmp_path))
    with pytest.raises(EditError, match="표·그림"):
        d.edit_cell(1, 1, 0, 0, "덮어쓰기")
    assert sum(1 for _ in tops(d.path)[1].iter(q("hp:tbl"))) == 2


def _replace_externally(d, tmp_path, text):
    pkg = Package.open(d.path)
    [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2].find(q("hp:run")).find(q("hp:t")).text = text
    tmp = pkg.save(tmp_path / "ext.hwpx")
    time.sleep(0.05)
    tmp.replace(d.path)


def test_write_detects_external_change(blank, tmp_path):
    """I1: 화면이 새로 불러오기 전이라도 한글에서 바뀐 사본에는 옛 판으로 쓰지 않는다."""
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(make_doc(blank, tmp_path))
    _replace_externally(d, tmp_path, "한글에서 고침")
    with pytest.raises(EditError) as e:
        d.edit_para(1, 3, "옛 판에서 고침")
    assert e.value.status == 409
    assert own_text(tops(d.path)[2]) == "한글에서 고침"


def test_undo_after_external_change_keeps_rescue_copy(blank, tmp_path):
    """I2: 한글에서 고친 뒤 되돌리기를 해도 한글에서 고친 상태를 따로 남긴다."""
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    d.edit_para(1, 2, "화면에서 고침")
    _replace_externally(d, tmp_path, "한글에서 고침")
    d.doc()
    d.undo(d.version)
    rescue = list((d.history_dir / "외부").glob("*.hwpx"))
    assert len(rescue) == 1
    assert "한글에서 고침" in [own_text(p) for p in tops(rescue[0])]


def test_server_maps_file_errors_to_json(server, monkeypatch):
    """I3: 사본을 읽다 막혀도 연결을 끊지 않고 한국어 오류를 돌려준다."""
    from hwpxkit.editor import doc as docmod
    srv, _ = server

    def busy(*a, **k):
        raise PermissionError("busy")
    monkeypatch.setattr(docmod.Package, "open", busy)
    st, r = call(srv, "GET", "/api/doc")
    assert st == 423 and "잠시 뒤" in r["error"]


def test_doc_marks_paragraph_with_tabs(blank, tmp_path):
    """I4: 탭·줄바꿈이 든 문단은 고치면 사라짐을 화면이 알 수 있게 표시한다."""
    from hwpxkit.editor import EditDoc
    pkg = Package.open(blank)
    p = para("1.")
    t = p.find(q("hp:run")).find(q("hp:t"))
    tab = t.makeelement(q("hp:tab"), {})
    tab.tail = "제목"
    t.append(tab)
    append_to_body(pkg, p)
    d = EditDoc(pkg.save(tmp_path / "탭.hwpx"))
    assert next(b for b in d.doc()["blocks"] if b["i"] == 1)["flat"] is True
    html = (Path(__file__).parents[1] / "hwpxkit" / "editor" / "page.html").read_text(encoding="utf-8")
    assert "b.flat" in html


def test_state_kept_when_server_alive_but_slow(blank, tmp_path):
    """I5: 서버 프로세스가 살아 있는데 응답만 늦으면 상태 파일을 지우지 않는다."""
    import os
    from hwpxkit.cli import _edit_state
    from hwpxkit.editor import copy_path
    from hwpxkit.editor.server import state_path
    src = make_doc(blank, tmp_path)
    st = state_path(copy_path(src))
    st.write_text(json.dumps({"port": 9, "key": "k", "pid": os.getpid(), "url": "x"}), encoding="utf-8")
    with pytest.raises(Exception, match="응답"):
        _edit_state(src)
    assert st.exists()
    st.write_text(json.dumps({"port": 9, "key": "k", "pid": 999999, "url": "x"}), encoding="utf-8")
    assert _edit_state(src) is None and not st.exists()
