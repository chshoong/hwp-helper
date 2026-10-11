"""차례·표목차·그림목차(한글 차례 칸)와 상호 참조."""
import re

import pytest

from helpers import LONG, SECTION, append_to_body, para, table, tiny_png
from hwpxkit.body import all_text, own_text
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.samples import infer

DOC_MD = """# 제1장 서론

## 1.1 연구 배경

{long}

표: 첫째 표
| 가 | 나 |
|---|---|
| 1 | 2 |

![첫째 그림](g.png)

# 제2장 방법

{long} [표 2]를 본다.

표: 둘째 표
| 다 | 라 |
|---|---|
| 3 | 4 |
"""


def make_doc(blank, tmp_path, md=None, name="doc.hwpx"):
    (tmp_path / "g.png").write_bytes(tiny_png())
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), (md or DOC_MD).format(long=LONG), base_dir=tmp_path)
    return pkg


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def command(fb):
    return next(e.text for e in fb.iter(q("hp:stringParam")) if e.get("name") == "Command")


def test_insert_table_toc_at_position(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    warnings = toc.insert_toc(pkg, ["표"], at=1)
    assert warnings == []
    ps = tops(pkg)
    fb = next(ps[1].iter(q("hp:fieldBegin")))
    assert fb.get("type") == "TABLEOFCONTENTS" and "ContentsMake:uint:2 " in command(fb)
    assert "ContentsLevel:int:2" in command(fb) and "ContentsLeader:int:3" in command(fb)
    assert [own_text(p) for p in ps[2:4]] == ["[표 1] 첫째 표", "[표 2] 둘째 표"]
    end = next(ps[4].iter(q("hp:fieldEnd")))
    assert end.get("beginIDRef") == fb.get("id") and end.get("fieldid") == fb.get("fieldid")
    assert toc.toc_blocks(ps) == [(1, 4, 2)] and toc.has_toc(pkg)


def test_title_toc_marks_headings(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목"], at=1)
    marked = [own_text(p) for p in tops(pkg) if next(p.iter(q("hp:titleMark")), None) is not None]
    assert marked == ["제1장 서론", "1.1 연구 배경", "제2장 방법"]
    tm = next(tops(pkg)[0].getparent().iter(q("hp:titleMark")))
    assert tm.get("ignore") == "1" and tm.getparent().tag == q("hp:t")
    fb = next(tops(pkg)[1].iter(q("hp:fieldBegin")))
    assert "ContentsMake:uint:65 " in command(fb)
    assert toc.mark_titles(pkg) == 0  # 다시 해도 하나


def test_title_level_limit(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    assert toc.mark_titles(pkg, level=1) == 2


def test_all_kinds_in_order_and_warnings(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="# 제1장 서론\n\n{long}\n")
    warnings = toc.insert_toc(pkg, ["그림", "표", "제목"], at=1)
    assert len(warnings) == 2 and all("없어" in w for w in warnings)
    makes = [m for _, _, m in toc.toc_blocks(tops(pkg))]
    assert makes == [65]


def test_field_ids_unique(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목", "표", "그림"], at=1)
    ids = [fb.get("id") for fb in pkg.xml(SECTION).iter(q("hp:fieldBegin"))]
    assert len(ids) == 3 and len(set(ids)) == 3
