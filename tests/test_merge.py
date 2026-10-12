"""이전 판 비교(compare)와 의견 합치기(merge)."""
import json
import shutil

import pytest

from helpers import LONG, SECTION, append_to_body, memo_run, para, table
from hwpxkit.ns import q
from hwpxkit.package import Package


def base_doc(blank, tmp_path, name="보고서.hwpx"):
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para("연구 배경을 설명하는 첫 문단이다. " + LONG))
    append_to_body(pkg, para("연구 목적을 설명하는 둘째 문단이다. " + LONG))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "구분", (0, 1): "값", (1, 0): "표본", (1, 1): "120명"}))
    append_to_body(pkg, para("제2장 방법"))
    append_to_body(pkg, para("해당 없음"))
    append_to_body(pkg, para("자료 수집 절차를 설명한다. " + LONG))
    append_to_body(pkg, para("해당 없음"))
    return pkg.save(tmp_path / name)


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def edited(src, dst, change):
    """src 사본을 만들고 change(pkg)로 고쳐 dst에 저장."""
    shutil.copy(src, dst)
    pkg = Package.open(dst)
    change(pkg)
    out = dst.with_name(dst.stem + ".tmp.hwpx")
    pkg.save(out)
    out.replace(dst)
    return dst


def set_text(pkg, i, text):
    from hwpxkit.editor.doc import _set_text
    _set_text([p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][i], text)


def test_units_and_where(blank, tmp_path):
    from hwpxkit.compare import units
    us = units(Package.open(base_doc(blank, tmp_path)))
    keys = [u.key for u in us]
    assert ("p", 2) in keys and ("c", 4, 1, 1, 1, 0) in keys
    cell = next(u for u in us if u.key == ("c", 4, 1, 1, 1, 0))
    assert cell.text == "120명" and cell.where == "제1장 서론 · 표1 2행 2열"
    assert next(u for u in us if u.key == ("p", 7)).where == "제2장 방법"
    assert all(u.text for u in us)


def test_diff_edit_add_del(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        set_text(pkg, 3, "연구 목적을 설명하는 둘째 문단이며 조금 고쳤다. " + LONG)
        root = pkg.edit(SECTION)
        ps = [p for p in root if p.tag == q("hp:p")]
        root.remove(ps[7])  # 자료 수집 절차 문단 삭제
        root.insert(root.index(ps[2]) + 1, para("새로 넣은 문단이다."))
        from hwpxkit.editor.doc import _set_text
        cell = [tc for tc in root.iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "150명")
    new = edited(src, tmp_path / "새판.hwpx", change)
    changes = diff(units(Package.open(src)), units(Package.open(new)))
    kinds = sorted((c["kind"], c.get("new", c.get("old"))) for c in changes)
    assert ("add", "새로 넣은 문단이다.") in kinds
    assert any(k == "del" and t.startswith("자료 수집 절차를") for k, t in kinds)
    edits = {c["old"][:6]: c for c in changes if c["kind"] == "edit"}
    assert set(edits) == {"연구 목적을", "120명"}
    assert edits["120명"]["new"] == "150명" and edits["120명"]["where"] == "제1장 서론 · 표1 2행 2열"
    add = next(c for c in changes if c["kind"] == "add")
    assert add["after_key"] == ("p", 2)


def test_memos_read(blank, tmp_path):
    from hwpxkit.compare import memos
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        p.append(memo_run("메모가 붙은 글", "근거를 더 쓰세요"))
    out = edited(src, tmp_path / "메모.hwpx", change)
    ms = memos(Package.open(out))
    assert ms == [{"text": "근거를 더 쓰세요", "anchor": "메모가 붙은 글", "where": "제1장 서론"}]


def test_memo_text_not_in_units(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        run = memo_run("", "근거를 더 쓰세요")
        for el in list(run):
            if el.tag == q("hp:t"):
                run.remove(el)
        p.insert(0, run)
    out = edited(src, tmp_path / "메모만.hwpx", change)
    assert diff(units(Package.open(src)), units(Package.open(out))) == []
