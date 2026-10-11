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
    out, _ = bridge.refresh_toc(src, tmp_path / "b.hwpx")
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


def entry_pages(pkg):
    """새로 고친 차례 칸의 항목마다 (ContentsMake, 쪽 번호 글)."""
    from hwpxkit import toc
    ps = tops(pkg)
    out = []
    for s, e, m in toc.toc_blocks(ps):
        for p in ps[s + 1:e]:
            tab = next(p.iter(q("hp:tab")), None)
            if tab is not None:
                out.append((m, (tab.tail or "").strip()))
    return out


@pytest.mark.hangul
def test_refresh_fills_page_numbers(blank, tmp_path):
    from hwpxkit import bridge, toc
    md = ("[차례]\n\n[표 목차]\n\n[그림 목차]\n\n---쪽---\n\n# 제1장 서론\n\n" + LONG + "\n\n표: 첫째 표\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n\n"
          "---쪽---\n\n# 제2장 방법\n\n## 2.1 자료\n\n" + LONG + "\n\n![첫째 그림](g.png)\n\n표: 둘째 표\n| 다 | 라 |\n|---|---|\n| 3 | 4 |\n")
    pkg = make_doc(blank, tmp_path, md=md)
    src = pkg.save(tmp_path / "before.hwpx")
    out, _ = bridge.refresh_toc(src, tmp_path / "after.hwpx")
    pages = entry_pages(Package.open(out))
    tables = [pg for m, pg in pages if m == 2]
    figures = [pg for m, pg in pages if m == 4]
    titles = [pg for m, pg in pages if m == 65]
    assert tables == ["2", "3"] and figures == ["3"]
    assert len(titles) == 3 and titles[0] == "2"


@pytest.mark.hangul
def test_crossref_number_recomputed_by_hangul(blank, tmp_path):
    from hwpxkit import bridge, toc
    pkg = make_doc(blank, tmp_path)
    toc.link_refs(pkg)
    fb = crossrefs(pkg)[0]
    shown = fb.getparent().getnext()
    shown.text = "9"  # 일부러 틀린 값
    src = pkg.save(tmp_path / "stale.hwpx")
    out = bridge.convert(src, tmp_path / "resaved.hwpx")
    fb2 = crossrefs(Package.open(out))[0]
    assert fb2.getparent().getnext().text == "2"


def test_skill_documents_toc():
    from pathlib import Path as P
    root = P(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "toc.md").read_text(encoding="utf-8")
    for word in ("hwpx.py\" toc", "[차례]", "[표 목차]", "[그림 목차]", "--refs", "차례 새로 고침"):
        assert word in text, word
    assert "reference/toc.md" in (root / "SKILL.md").read_text(encoding="utf-8")


# ---- 최종 리뷰 반영 ----

def field_balance(pkg):
    root = pkg.xml(SECTION)
    begins = {fb.get("id") for fb in root.iter(q("hp:fieldBegin"))}
    ends = {fe.get("beginIDRef") for fe in root.iter(q("hp:fieldEnd"))}
    return begins == ends


def test_other_kind_under_generic_heading_keeps_existing_block(blank, tmp_path):
    """C1: '목 차' 아래 제목 차례가 있을 때 표 목차를 넣어도 제목 차례의 시작 문단을 지우지 않는다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    pkg.edit(SECTION).insert(1, para("목 차"))
    toc.insert_toc(pkg, ["제목"])
    toc.insert_toc(pkg, ["표"])
    assert [m for _, _, m in toc.toc_blocks(tops(pkg))] == [65, 2] and field_balance(pkg)


def test_droppable_keeps_ctrl_and_page_break_paragraphs(blank, tmp_path):
    """C1: 빈 줄처럼 보여도 쪽 나누기나 개체(ctrl)가 있는 문단은 지우지 않는다."""
    from hwpxkit import toc
    pkg = Package.open(blank)
    append_to_body(pkg, para("목차"))
    brk = append_to_body(pkg, para(""))
    brk.set("pageBreak", "1")
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para(LONG))
    assert toc.find_slot(pkg, "제목")[2] == []


def _hangul_toc_in_p0(pkg):
    """한글에서 문서 맨 앞에 차례를 넣으면 시작 필드가 0번 문단(쪽 설정)에 들어간다."""
    from hwpxkit import toc
    toc.insert_toc(pkg, ["표"], at=1)
    ps = tops(pkg)
    begin_run = ps[1].find(q("hp:run"))
    p0 = ps[0]
    for el in list(begin_run):
        p0.find(q("hp:run")).append(el)
    pkg.edit(SECTION).remove(ps[1])


def test_replace_block_starting_in_p0_keeps_section(blank, tmp_path):
    """C2: 0번 문단에서 시작하는 차례 칸을 바꿔도 0번 문단(쪽 설정)은 지우지 않는다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    _hangul_toc_in_p0(pkg)
    assert toc.toc_blocks(tops(pkg))[0][0] == 0
    toc.insert_toc(pkg, ["표"])
    root = pkg.xml(SECTION)
    assert next(root.iter(q("hp:secPr")), None) is not None
    assert [m for _, _, m in toc.toc_blocks(tops(pkg))] == [2] and field_balance(pkg)
    assert any("제1장 서론" in own_text(p) for p in tops(pkg))


def test_replace_block_keeps_text_merged_into_end(blank, tmp_path):
    """C2: 끝 문단에 본문이 합쳐져 있으면 그 글은 남긴다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    s, e, _ = toc.toc_blocks(tops(pkg))[0]
    end = tops(pkg)[e]
    t = end.find(q("hp:run")).find(q("hp:t"))
    t.text = "합쳐진 본문 문단"
    toc.insert_toc(pkg, ["표"])
    assert any(own_text(p) == "합쳐진 본문 문단" for p in tops(pkg)) and field_balance(pkg)


def test_toc_inside_table_cell_is_ignored(blank, tmp_path):
    """C3: 표 칸 안의 차례 칸은 문서 차례로 보지 않는다 (표를 통째로 지우면 안 됨)."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    holder = append_to_body(pkg, table(1, 1))
    sub = next(holder.iter(q("hp:subList")))
    donor = make_doc(blank, tmp_path, name="y.hwpx")
    toc.insert_toc(donor, ["표"], at=1)
    s, e, _ = toc.toc_blocks(tops(donor))[0]
    for p in tops(donor)[s:e + 1]:
        sub.append(p)
    assert toc.toc_blocks(tops(pkg)) == []
    n_tbl = sum(1 for _ in pkg.xml(SECTION).iter(q("hp:tbl")))
    toc.insert_toc(pkg, ["표"])
    assert sum(1 for _ in pkg.xml(SECTION).iter(q("hp:tbl"))) == n_tbl


def test_link_uses_hangul_number_with_captionless_numbered_table(blank, tmp_path):
    """I1: 번호를 세는 캡션 없는 표가 앞에 있으면 한글 번호가 밀린다 — 한글이 보여 줄 번호로 맞춘다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    pkg.edit(SECTION).insert(1, table(1, 1))  # numberingType TABLE, 캡션 없음 → 한글이 1로 셈
    captioned = [t for t in pkg.xml(SECTION).iter(q("hp:tbl")) if t.find(q("hp:caption")) is not None]
    assert toc.link_refs(pkg) == (1, None)
    assert params(crossrefs(pkg)[0])["RefPath"] == f"?#{captioned[0].get('id')};"


def test_link_skips_hand_typed_caption_numbers(blank, tmp_path):
    """I1: 캡션 번호를 손으로 쓴 문서(자동 번호 없음)는 상호 참조를 만들지 않는다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    for cap in pkg.xml(SECTION).iter(q("hp:caption")):
        for ctrl in list(cap.iter(q("hp:ctrl"))):
            if ctrl.find(q("hp:autoNum")) is not None:
                ctrl.getparent().remove(ctrl)
    assert toc.link_refs(pkg) == (0, None)


def test_link_skips_text_inside_existing_field(blank, tmp_path):
    """I2: 하이퍼링크·누름틀 같은 기존 필드 안의 글은 건드리지 않는다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    p = next(p for p in tops(pkg) if "를 본다" in own_text(p))
    run = p.find(q("hp:run"))
    ids = toc._Ids(pkg)
    fb = toc._field_begin(ids, "HYPERLINK", [("integer", "Prop", "0")])
    run.insert(0, toc._ctrl(fb))
    run.append(toc._ctrl(toc._field_end(fb)))
    assert toc.link_refs(pkg) == (0, None)


def test_render_append_replaces_existing_block_and_marks_old_headings(blank, tmp_path):
    """I3: 이어 쓰기로 [표 목차]·[차례]를 넣어도 같은 종류 칸은 하나, 기존 제목도 차례에 들어간다."""
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    render_into(pkg, infer(pkg), "[표 목차]\n\n[차례]\n", mode="append", base_dir=tmp_path)
    makes = [m for _, _, m in toc.toc_blocks(tops(pkg))]
    assert makes.count(2) == 1 and makes.count(65) == 1 and field_balance(pkg)
    marked = [own_text(p) for p in tops(pkg) if next(p.iter(q("hp:titleMark")), None) is not None]
    assert "제2장 방법" in marked


def test_refresh_not_updated_is_reported(tmp_path, monkeypatch, capsys):
    """I4: 한글이 새로 고치지 못하고 저장만 했으면 성공이라고 하지 않는다."""
    from hwpxkit import bridge, cli

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        Path(dst).write_bytes(b"x")
        return {"ok": True, "updated": False}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"y")
    assert bridge.refresh_toc(src, tmp_path / "b.hwpx")[1] is False
    cli._refresh_toc_in_place(src, tmp_path)
    assert "차례 새로 고침" in capsys.readouterr().out
