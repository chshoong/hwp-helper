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
