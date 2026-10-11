"""차례·표목차·그림목차(한글 차례 칸)와 상호 참조."""
import re
from pathlib import Path

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


def test_slot_existing_block_and_reinsert(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    assert toc.find_slot(pkg, "표") == (1, "기존 차례 칸", [1, 2, 3, 4])


def test_insert_twice_keeps_one_block(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목", "표"])
    toc.insert_toc(pkg, ["제목", "표"])
    makes = [m for _, _, m in toc.toc_blocks(tops(pkg))]
    assert makes == [65, 2]


def test_slot_template_heading_drops_blank_and_empty_table(blank, tmp_path):
    from hwpxkit import toc
    pkg = Package.open(blank)
    append_to_body(pkg, para("표 지"))
    append_to_body(pkg, para("목 차"))
    append_to_body(pkg, para(""))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "…"}))
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para(LONG))
    assert toc.find_slot(pkg, "제목") == (3, "양식 목차 자리", [3, 4])
    toc.insert_toc(pkg, ["제목"])
    texts = [own_text(p) for p in tops(pkg)]
    assert texts[2] == "목 차" and next(tops(pkg)[3].iter(q("hp:fieldBegin"))).get("type") == "TABLEOFCONTENTS"
    assert sum(1 for _ in pkg.xml(SECTION).iter(q("hp:tbl"))) == 0


def test_slot_kind_specific_heading(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    root = pkg.edit(SECTION)
    root.insert(2, para("표 목차"))
    root.insert(2, para("목차"))
    at, reason, drop = toc.find_slot(pkg, "표")
    assert reason == "양식 표 목차 자리" and own_text(tops(pkg)[at - 1]) == "표 목차"
    assert toc.find_slot(pkg, "그림")[1] == "양식 목차 자리"


def test_slot_after_cover_page(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    ps = tops(pkg)
    k = next(i for i, p in enumerate(ps) if own_text(p).startswith("제2장"))  # 제1장은 0번 문단에 합쳐짐
    ps[k].set("pageBreak", "1")
    assert toc.find_slot(pkg, "표") == (k, "표지 다음", [])
    toc.insert_toc(pkg, ["제목", "표"])
    ps = tops(pkg)
    starts = [s for s, _, _ in toc.toc_blocks(ps)]
    assert ps[starts[0]].get("pageBreak") == "1" and ps[starts[1]].get("pageBreak") == "0"
    after = toc.toc_blocks(ps)[-1][1] + 1
    assert own_text(ps[after]).endswith("제2장 방법") and ps[after].get("pageBreak") == "1"


def test_slot_document_start(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    assert toc.find_slot(pkg, "표") == (1, "문서 처음", [])


def crossrefs(pkg):
    return [fb for fb in pkg.xml(SECTION).iter(q("hp:fieldBegin")) if fb.get("type") == "CROSSREF"]


def params(fb):
    return {e.get("name"): e.text for e in fb.find(q("hp:parameters"))}


def test_link_number_becomes_crossref(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    n, why = toc.link_refs(pkg)
    assert (n, why) == (1, None)
    fb = crossrefs(pkg)[0]
    tbl2 = [t for t in pkg.xml(SECTION).iter(q("hp:tbl")) if t.find(q("hp:caption")) is not None][1]
    pr = params(fb)
    assert pr["Command"] == f"?#{tbl2.get('id')};0;1;0;0;" and pr["RefType"] == "TARGET_TABLE"
    assert pr["RefContentType"] == "OBJECT_TYPE_NUMBER" and pr["RefPath"] == f"?#{tbl2.get('id')};"
    p = next(p for p in tops(pkg) if "를 본다" in own_text(p))
    assert own_text(p).endswith("[표 2]를 본다.")
    run = fb.getparent().getparent()
    i = [el.tag for el in run].index(q("hp:ctrl"))
    assert run[i + 1].text == "2" and run[i + 2].find(q("hp:fieldEnd")) is not None
    assert toc.link_refs(pkg) == (0, None)  # 다시 해도 같음


def test_link_picture(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="# 제1장\n\n![그림](g.png)\n\n그림 1에서 보듯이 결과가 좋다. " + LONG + "\n")
    assert toc.link_refs(pkg) == (1, None)
    pr = params(crossrefs(pkg)[0])
    assert pr["RefType"] == "TARGET_PICTURE" and ";1;1;0;0;" in pr["Command"]


def test_link_skips_missing_and_chapter_like(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md=DOC_MD.replace("[표 2]를 본다.", "[표 5]와 표 2-1, 도표 1을 본다."))
    assert toc.link_refs(pkg) == (0, None)


def test_link_skips_cells_captions_and_toc(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md=DOC_MD.replace("| 1 | 2 |", "| 표 1 | 2 |").replace("[표 2]를 본다.", "본다."))
    toc.insert_toc(pkg, ["표"], at=1)
    assert toc.link_refs(pkg) == (0, None)


def test_chapter_numbered_document_untouched(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    cap = next(pkg.xml(SECTION).iter(q("hp:caption")))
    t = next(cap.iter(q("hp:t")))
    t.text = "[표 1-1] 첫째 표"
    assert toc.uses_chapter_numbers(pkg) is True
    assert toc.link_refs(pkg) == (0, "chapter")


def test_cli_toc_without_hangul(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src = make_doc(blank, tmp_path).save(tmp_path / "보고서.hwpx")
    out = tmp_path / "차례.hwpx"
    assert main(["toc", str(src), str(out), "--kinds", "제목,표", "--refs"]) == 0
    text = capsys.readouterr().out
    assert "차례 새로 고침" in text and "상호 참조" in text
    from hwpxkit import toc
    pkg = Package.open(out)
    assert [m for _, _, m in toc.toc_blocks(tops(pkg))] == [65, 2]


def test_save_without_hangul_explains_toc(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    md = tmp_path / "새.md"
    (tmp_path / "g.png").write_bytes(tiny_png())
    md.write_text("[차례]\n\n" + DOC_MD.format(long=LONG), encoding="utf-8")
    out = tmp_path / "결과.hwpx"
    assert main(["render", str(blank), str(md), str(out)]) == 0
    text = capsys.readouterr().out
    assert out.exists() and "차례 새로 고침" in text


def test_render_links_refs(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    md = tmp_path / "새.md"
    (tmp_path / "g.png").write_bytes(tiny_png())
    md.write_text(DOC_MD.format(long=LONG), encoding="utf-8")
    out = tmp_path / "결과.hwpx"
    assert main(["render", str(blank), str(md), str(out)]) == 0
    assert "상호 참조로 연결" in capsys.readouterr().out
    assert crossrefs(Package.open(out))


def test_cli_toc_bad_kind(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    src = make_doc(blank, tmp_path).save(tmp_path / "보고서.hwpx")
    assert main(["toc", str(src), str(tmp_path / "o.hwpx"), "--kinds", "수식"]) == 2
    assert "제목·표·그림" in capsys.readouterr().err


def test_refresh_toc_uses_bridge_action(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"] = action
        Path(dst).write_bytes(b"x")
        return {"ok": True}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"y")
    out = bridge.refresh_toc(src, tmp_path / "b.hwpx")
    assert seen["action"] == "toc" and out.read_bytes() == b"x"
    with pytest.raises(ValueError):
        bridge.refresh_toc(src, src)


def test_review_flags_stale_toc(blank, tmp_path):
    from hwpxkit import toc
    from hwpxkit.review import review
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    assert [f.code for f in review(pkg)].count("toc-stale") == 1


def test_parse_toc_lines():
    from hwpxkit.mdparse import Toc, parse
    blocks = parse("[차례]\n[ 표 목차 ]\n[그림 차례]\n[목차]\n")
    assert [b.kind for b in blocks] == ["제목", "표", "그림", "제목"] and all(isinstance(b, Toc) for b in blocks)


def test_render_toc_blocks_in_place(blank, tmp_path):
    from hwpxkit import toc
    md = "# 제1장 서론\n\n[차례]\n\n[표 목차]\n\n---쪽---\n\n" + DOC_MD.split("\n", 2)[2]
    pkg = make_doc(blank, tmp_path, md=md)
    ps = tops(pkg)
    blocks = toc.toc_blocks(ps)
    assert [m for _, _, m in blocks] == [65, 2]
    assert own_text(ps[blocks[0][0] - 1]).endswith("제1장 서론")
    after = blocks[-1][1] + 1
    assert ps[after].get("pageBreak") == "1"
    marked = [own_text(p) for p in ps if next(p.iter(q("hp:titleMark")), None) is not None]
    assert "제1장 서론" in marked and "1.1 연구 배경" in marked


def test_toc_block_first_in_document(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="[차례]\n\n" + DOC_MD)
    blocks = toc.toc_blocks(tops(pkg))
    assert [m for _, _, m in blocks] == [65] and blocks[0][0] == 1
