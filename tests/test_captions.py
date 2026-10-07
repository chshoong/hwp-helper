"""표·그림 제목은 한글 캡션(개체에 붙은 hp:caption)으로, 번호는 가능하면 한글 자동 번호로 넣는다."""
from helpers import LONG, SECTION, append_to_body, para, report_template, table, tiny_png
from hwpxkit.body import all_text, own_text
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.reader import to_markdown
from hwpxkit.render import render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate

TABLE_MD = "표: 평가 지표 {#tbl:m}\n| 지표 | 정의 |\n|---|---|\n| 탐지율 | 경보 비율 |\n\n[@tbl:m]에 정리했다.\n"


def plain(blank):
    """캡션 견본도 장 번호도 없는 양식 (번호 형식은 기본 '[표 {n}]')."""
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para(LONG))
    return pkg


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def test_table_caption_is_hangul_caption_with_autonum(blank):
    pkg = plain(blank)
    render_into(pkg, infer(pkg), TABLE_MD)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    cap = tbl.find(q("hp:caption"))
    assert cap is not None and cap.get("side") == "TOP"
    num = next(cap.iter(q("hp:autoNum")))
    assert num.get("numType") == "TABLE" and num.get("num") == "1"
    assert all_text(cap) == "[표 ] 평가 지표"
    assert not any("평가 지표" in own_text(p) for p in tops(pkg))  # 따로 떨어진 제목 문단 없음
    assert any("[표 1]에 정리했다" in own_text(p) for p in tops(pkg))
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_figure_caption_is_hangul_caption_with_autonum(blank, tmp_path):
    pkg = plain(blank)
    (tmp_path / "f.png").write_bytes(tiny_png((400, 200)))
    render_into(pkg, infer(pkg), "![매칭 흐름](f.png)\n", base_dir=tmp_path)
    pic = next(pkg.xml(SECTION).iter(q("hp:pic")))
    cap = pic.find(q("hp:caption"))
    assert cap is not None and cap.get("side") == "BOTTOM"
    num = next(cap.iter(q("hp:autoNum")))
    assert num.get("numType") == "PICTURE" and num.get("num") == "1"
    assert all_text(cap) == "[그림 ] 매칭 흐름"
    assert not any("매칭 흐름" in own_text(p) for p in tops(pkg))


def test_chapter_numbers_stay_text_inside_caption(blank):
    """장별 번호([표 1-1])는 한글 자동 번호로 못 만들므로 캡션 안에 글자로 넣는다."""
    pkg = Package.open(blank)
    report_template(pkg)
    render_into(pkg, infer(pkg), "# 제1장 서론\n\n" + TABLE_MD)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    cap = tbl.find(q("hp:caption"))
    assert cap is not None and cap.get("side") == "TOP"
    assert next(cap.iter(q("hp:autoNum")), None) is None
    assert all_text(cap) == "[표 1-1] 평가 지표"
    assert not any("평가 지표" in own_text(p) for p in tops(pkg))


def test_caption_reads_back(blank, tmp_path):
    pkg = plain(blank)
    (tmp_path / "f.png").write_bytes(tiny_png((400, 200)))
    render_into(pkg, infer(pkg), TABLE_MD + "\n![매칭 흐름](f.png)\n", base_dir=tmp_path)
    md = to_markdown(pkg)
    assert "표: 평가 지표" in md and "![매칭 흐름]" in md


def test_cover_like_table_is_not_a_table_sample(blank):
    """표지처럼 첫 행이 표 너비 전체를 차지하는 서식용 표는 데이터 표 견본으로 쓰지 않는다."""
    pkg = plain(blank)
    append_to_body(pkg, table(3, 2, spans={(0, 0): (1, 2)}, skip={(0, 1)},
                              texts={(0, 0): "경진대회 보고서", (1, 0): "프로젝트명", (2, 0): "팀명"}))
    assert infer(pkg).table_para is None


def test_header_much_larger_than_body_is_not_a_table_sample(blank):
    pkg = plain(blank)
    big = Header(pkg).derive_charpr("0", height=2400, bold=True)
    tp = table(2, 2, texts={(0, 0): "지표", (0, 1): "정의", (1, 0): "a", (1, 1): "b"})
    for t in [tc for tc in tp.iter(q("hp:tc"))][:2]:
        for run in t.iter(q("hp:run")):
            run.set("charPrIDRef", big)
    append_to_body(pkg, tp)
    assert infer(pkg).table_para is None


def test_data_table_is_still_a_sample(blank):
    pkg = plain(blank)
    append_to_body(pkg, table(2, 3, texts={(0, 0): "구분", (0, 1): "계획", (0, 2): "실적"}))
    assert infer(pkg).table_para is not None


def test_default_table_without_body_sample(blank):
    """본문 견본이 없는(글머리만 있는) 양식에서도 기본 표를 만든다."""
    pkg = Package.open(blank)
    for text in ("□ 제1장 데이터 이해", "○ 휴먼명조 14, 줄간격 160", "- 휴먼명조 14, 줄간격 160"):
        append_to_body(pkg, para(text))
    render_into(pkg, infer(pkg), "○ 설명\n\n" + TABLE_MD.split("\n\n")[0])  # 본문 문장 없이 표만
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert tbl.get("rowCnt") == "2" and tbl.find(q("hp:caption")) is not None
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_captionless_objects_do_not_take_numbers(blank):
    """표지·작성 요령처럼 캡션 없는 표는 한글 자동 번호를 세지 않게 한다 (첫 표가 '표 2'가 되던 문제)."""
    pkg = plain(blank)
    append_to_body(pkg, table(3, 2, spans={(0, 0): (1, 2)}, skip={(0, 1)}, texts={(0, 0): "표지"}))
    render_into(pkg, infer(pkg), TABLE_MD, mode="append")
    cover, ours = list(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert cover.get("numberingType") == "NONE"
    assert ours.get("numberingType") == "TABLE"
    assert next(ours.iter(q("hp:autoNum"))).get("num") == "1"


def test_numbers_continue_after_existing_captions(blank):
    """앞에 캡션 달린 표가 있으면 그다음 번호부터 매기고 본문 참조도 맞춘다."""
    pkg = plain(blank)
    render_into(pkg, infer(pkg), TABLE_MD + "\n" + LONG + "\n")
    render_into(pkg, infer(pkg), TABLE_MD.replace("평가 지표", "둘째 표"), mode="append")
    nums = [an.get("num") for an in pkg.xml(SECTION).iter(q("hp:autoNum"))]
    assert nums == ["1", "2"]
    assert any("[표 2]에 정리했다" in own_text(p) for p in tops(pkg))


def test_default_table_is_tidy(blank):
    """기본 표: 머리 행 음영·굵게, 모든 칸 가운데 정렬·들여쓰기 없음, 글자 10pt 이하."""
    pkg = Package.open(blank)
    h = Header(pkg)
    big = h.derive_charpr("0", height=1500)
    indent = h.derive("paraPr", "0", lambda e: [m.set("value", "2000") for m in e.iter(q("hc:intent"))])
    for _ in range(2):
        append_to_body(pkg, para(LONG, para_pr=indent, char_pr=big))
    render_into(pkg, infer(pkg), TABLE_MD.split("\n\n")[0])
    h = Header(pkg)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    rows = tbl.findall(q("hp:tr"))
    head, body = rows[0].find(q("hp:tc")), rows[1].find(q("hp:tc"))
    assert h.get("borderFill", head.get("borderFillIDRef")).find(".//" + q("hc:winBrush")) is not None
    for tc in (head, body):
        p = tc.find(q("hp:subList")).find(q("hp:p"))
        pp = h.get("paraPr", p.get("paraPrIDRef"))
        assert pp.find(q("hh:align")).get("horizontal") == "CENTER"
        assert all(m.get("value") == "0" for m in pp.iter(q("hc:intent")))
        run = p.find(q("hp:run"))
        assert int(h.get("charPr", run.get("charPrIDRef")).get("height")) <= 1000
    head_run = head.find(q("hp:subList")).find(q("hp:p")).find(q("hp:run"))
    assert h.get("charPr", head_run.get("charPrIDRef")).find(q("hh:bold")) is not None


def test_default_table_has_room_in_cells(blank):
    """칸 위아래 여백 1mm 이상 (글자가 선에 붙어 보이던 문제)."""
    pkg = plain(blank)
    render_into(pkg, infer(pkg), TABLE_MD)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    m = tbl.find(q("hp:inMargin"))
    assert int(m.get("top")) >= 283 and int(m.get("bottom")) >= 283


def test_chapter_number_comes_from_heading_text(blank):
    """첫 장이 '제2장'이면 표 번호는 [표 2-1] (장 수를 세지 않고 제목의 번호를 쓴다)."""
    from helpers import report_template
    pkg = Package.open(blank)
    report_template(pkg)
    render_into(pkg, infer(pkg), "# 제2장 연구 수행 결과\n\n" + TABLE_MD)
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert all_text(tbl.find(q("hp:caption"))) == "[표 2-1] 평가 지표"
    assert any("[표 2-1]에 정리했다" in own_text(p) for p in tops(pkg))


def test_caption_follows_body_font_when_no_caption_sample(blank):
    """캡션 견본이 없으면 한글 기본 '캡션' 스타일(함초롬바탕) 대신 본문 글꼴로 맞춘다."""
    pkg = Package.open(blank)
    body = Header(pkg).derive_font("0", "휴먼명조")
    append_to_body(pkg, para(LONG, char_pr=body))
    append_to_body(pkg, para(LONG, char_pr=body))
    render_into(pkg, infer(pkg), TABLE_MD)
    h = Header(pkg)
    cap = next(pkg.xml(SECTION).iter(q("hp:caption")))
    run = next(cap.iter(q("hp:run")))
    assert h.charpr_faces(run.get("charPrIDRef"))["HANGUL"] == "휴먼명조"
