"""양식 모양을 더 충실히: 글머리 앞 공백·기호, 묶음 사이에만 빈 줄, 제목은 다음 문단과 같은 쪽,
기본 표는 고딕, 양식 안내 문구 검토."""
from helpers import LONG, SECTION, append_to_body, para
from hwpxkit.body import is_blank, own_text
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.review import review
from hwpxkit.samples import infer


def gov_form(blank):
    """경진대회 양식처럼 공백으로 들여쓴 글머리와, '-' 앞에 빈 줄이 있는 양식."""
    pkg = Package.open(blank)
    for text in ("□ 제1장. 데이터 이해", " ◦ 견본 둘째 단계 글머리 문장", "",
                 "   - 견본 셋째 단계 글머리 문장", "       * 견본 주석 문장", "",
                 "□ 제2장. 모델 개발", " ◦ 견본 둘째 단계 글머리 문장", "",
                 "   - 견본 셋째 단계 글머리 문장", "       * 견본 주석 문장"):
        append_to_body(pkg, para(text))
    append_to_body(pkg, para(LONG))
    return pkg


def body_tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def test_bullets_keep_template_indent_and_glyph(blank):
    pkg = gov_form(blank)
    render_into(pkg, infer(pkg), "○ 분석 대상 설명\n- 세부 설명\n※ 참고 사항\n")
    texts = [own_text(p) for p in body_tops(pkg)]
    assert " ◦ 분석 대상 설명" in texts
    assert "   - 세부 설명" in texts
    assert "       ※ 참고 사항" in texts


def test_blank_line_only_between_groups(blank):
    pkg = gov_form(blank)
    render_into(pkg, infer(pkg), "○ 첫 항목\n- 세부 하나\n- 세부 둘\n- 세부 셋\n")
    seq = ["blank" if is_blank(p) else own_text(p).strip()[:1] for p in body_tops(pkg)]
    seq = seq[seq.index("◦"):]
    assert seq == ["◦", "blank", "-", "-", "-"]


def test_headings_keep_with_next(blank):
    pkg = gov_form(blank)
    render_into(pkg, infer(pkg), "□ 제3장. 결과\n○ 내용\n")
    h = Header(pkg)
    p = next(p for p in body_tops(pkg) if own_text(p).startswith("□ 제3장"))
    assert h.get("paraPr", p.get("paraPrIDRef")).find(q("hh:breakSetting")).get("keepWithNext") == "1"


def test_default_table_text_is_gothic(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), "| 구분 | 값 |\n|---|---|\n| 가 | 1 |\n")
    h = Header(pkg)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    for tc in tbl.iter(q("hp:tc")):
        run = next(r for r in tc.iter(q("hp:run")) if r.find(q("hp:t")) is not None)
        face = h.charpr_faces(run.get("charPrIDRef"))["HANGUL"]
        assert face in ("맑은 고딕", "함초롬돋움", "한양중고딕", "나눔고딕", "돋움", "굴림"), face


def test_review_finds_leftover_guide_text(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("※ 추가적으로 기술할 내용은 자유롭게 작성 가능"))
    append_to_body(pkg, para("예 시"))
    found = [f for f in review(pkg) if f.code == "guide-text"]
    assert len(found) == 2


def test_review_finds_empty_cover_fields(blank):
    """표지처럼 '항목 | 값' 두 열 표의 값 칸이 모두 비어 있어도 알린다."""
    from helpers import table
    pkg = Package.open(blank)
    append_to_body(pkg, table(4, 2, spans={(0, 0): (1, 2)}, skip={(0, 1)},
                              texts={(0, 0): "경진대회 보고서", (1, 0): "프로젝트명", (2, 0): "팀명", (3, 0): "내용요약"}))
    append_to_body(pkg, para(LONG))
    msgs = [f.message for f in review(pkg) if f.code == "empty-cell"]
    assert len(msgs) == 3 and any("프로젝트명" in m for m in msgs)


def test_heading_font_is_not_font_mix(blank):
    """제목에만 쓰는 글꼴(HY헤드라인M 등)은 글꼴 혼용으로 알리지 않는다."""
    pkg = Package.open(blank)
    head = Header(pkg).derive_font("0", "HY헤드라인M")
    append_to_body(pkg, para("□ 제1장. 데이터 이해 및 진단", char_pr=head))
    for _ in range(4):
        append_to_body(pkg, para(LONG * 3))
    assert [f for f in review(pkg) if f.code == "font-mix"] == []
