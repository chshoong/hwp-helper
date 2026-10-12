"""분량(쪽수·제한·배점)과 작성 요령 항목 (pages, guide)."""
import json

import pytest

from helpers import LONG, SECTION, append_to_body, para, table
from hwpxkit.ns import q
from hwpxkit.package import Package


def test_find_limits():
    from hwpxkit.fit import find_limits
    found = find_limits(["분량: 본문 10쪽 이내 (표지 제외)", "A4 5매 내외로 작성", "제3장 이내 작성",
                         "15페이지 이하", "본문 10쪽 이내 (표지 제외)"])
    assert [(f["pages"], f["kind"]) for f in found] == [(10, "이내"), (5, "내외"), (15, "이하")]
    assert found[0]["text"] == "10쪽 이내"


def test_heading_score():
    from hwpxkit.fit import heading_score
    assert heading_score("제2장 데이터 분석〔30점〕") == 30
    assert heading_score("1. 개요 (15점)") == 15
    assert heading_score("결론 [5점]") == 5
    assert heading_score("배점 30점을 받는다") is None


def _doc(blank, paras):
    pkg = Package.open(blank)
    for p in paras:
        append_to_body(pkg, para(p))
    return pkg


def guide_form(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para("※ 본문 분량은 10쪽 이내로 작성"))
    append_to_body(pkg, para("제1장 서론〔10점〕"))
    append_to_body(pkg, table(1, 1, texts={(0, 0): ["작성 요령", "", "- 연구 배경을 구체적으로 기술", "- 필요성을 제시"]}))
    append_to_body(pkg, para("※ 표·그림을 활용하여 작성"))
    append_to_body(pkg, para("※ 참고: 이 줄은 안내가 아님"))
    append_to_body(pkg, para("제2장 방법〔30점〕"))
    append_to_body(pkg, table(2, 1, texts={(0, 0): "작성 방법", (1, 0): "자료 수집 절차와 기준 기술"}))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "구분", (0, 1): "내용", (1, 0): "가", (1, 1): "나"}))
    append_to_body(pkg, para("제3장 결론"))
    append_to_body(pkg, para(LONG))
    return pkg


def test_guide_items(blank):
    from hwpxkit.fit import guide_items
    r = guide_items(guide_form(blank))
    assert [l["text"] for l in r["limits"]] == ["10쪽 이내"]
    secs = {s["title"]: s for s in r["sections"]}
    assert list(secs) == ["(앞부분)", "제1장 서론〔10점〕", "제2장 방법〔30점〕"]
    assert secs["(앞부분)"]["items"] == [{"kind": "안내", "text": "※ 본문 분량은 10쪽 이내로 작성"}]
    assert secs["제1장 서론〔10점〕"]["items"] == [
        {"kind": "배점", "text": "10점"},
        {"kind": "요령", "text": "- 연구 배경을 구체적으로 기술"},
        {"kind": "요령", "text": "- 필요성을 제시"},
        {"kind": "안내", "text": "※ 표·그림을 활용하여 작성"}]
    assert secs["제2장 방법〔30점〕"]["items"] == [{"kind": "배점", "text": "30점"},
                                              {"kind": "요령", "text": "자료 수집 절차와 기준 기술"}]
    assert secs["제2장 방법〔30점〕"]["score"] == 30


def test_guide_none(blank):
    from hwpxkit.fit import guide_items
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para(LONG))
    assert guide_items(pkg)["sections"] == []


def test_cli_pages_without_hangul(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    src = _doc(blank, ["제1장 서론", LONG]).save(tmp_path / "a.hwpx")
    monkeypatch.setattr(bridge, "available", lambda: False)
    assert main(["pages", str(src)]) == 2
    assert "한글이 있어야" in capsys.readouterr().err


def test_cli_guide(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    src = guide_form(blank).save(tmp_path / "양식.hwpx")
    assert main(["guide", str(src)]) == 0
    out = capsys.readouterr().out
    assert "제1장 서론〔10점〕" in out and "[요령] - 필요성을 제시" in out and "분량: 10쪽 이내" in out
    assert main(["guide", str(src), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sections"][1]["score"] == 10
    empty = _doc(blank, ["제1장 서론", LONG]).save(tmp_path / "b.hwpx")
    assert main(["guide", str(empty)]) == 0
    assert "찾지 못했어요" in capsys.readouterr().out


def test_skill_documents_fit():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "fit.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" pages', 'hwpx.py" guide', "--limit", "render", "--replace", "지어내지", "3번"):
        assert word in text, word
    assert "reference/fit.md" in (root / "SKILL.md").read_text(encoding="utf-8")


# ---- 최종 리뷰 반영 ----

def test_heading_pages_from_page_texts():
    """I1·I5: 쪽마다 글에서 제목 줄을 찾아 실제 쪽(몇 번째 장)을 정한다. 차례 줄(제목+쪽 번호)은 제목 줄이 아님."""
    from hwpxkit.fit import heading_pages
    heads = [(1, "제1장 서론", 1), (5, "제2장 방법", 1), (9, "제3장 결론", 1)]
    texts = ["표 지", "차 례\r\n제1장 서론\t3\r\n제2장 방법\t4\r\n제3장 결론\t5",
             "제1장 서론\r\n본문", "앞 장 이어서\r\n제2장 방법\r\n본문", "제3장 결론\r\n본문"]
    assert heading_pages(heads, texts) == [(3, True), (4, False), (5, True)]
    assert heading_pages([(0, "없는 제목", 1)], texts) == [(None, False)]


def test_sections_from_heading_pages():
    from hwpxkit.fit import sections_from_pages
    heads = [(1, "제1장 서론", 1), (5, "제2장 방법", 1), (9, "제3장 결론", 1)]
    out = sections_from_pages(heads, [(3, True), (4, False), (5, True)], 6)
    assert [(s["start"], s["end"]) for s in out] == [(3, 4), (4, 4), (5, 6)]


def test_measure_from_page_texts_warns_missing(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["제1장 서론", LONG, "제2장 방법", LONG])
    r = measure(pkg, ["제1장 서론\r\n본문"], 1)
    assert [s["title"] for s in r["sections"]] == ["제1장 서론"] and any("제2장 방법" in w for w in r["warnings"])


def test_limit_ignores_photo_count_and_spaced_chapter():
    """I2: '사진은 3장 이내', '제 3장 이내'는 분량 제한이 아님. 'A4 5장 이내'는 제한."""
    from hwpxkit.fit import find_limits
    assert find_limits(["사진은 3장 이내로 첨부", "제 3장 이내 작성"]) == []
    assert [f["pages"] for f in find_limits(["A4 5장 이내로 작성"])] == [5]


def test_limit_keeps_exclusion_context():
    """I3: '본문 10쪽 이내(표지·참고문헌 제외)'의 제외 조건을 남긴다."""
    from hwpxkit.fit import find_limits
    f = find_limits(["본문 10쪽 이내(표지·참고문헌 제외)"])[0]
    assert f["exclude"] is True and "참고문헌" in f["context"]
    assert find_limits(["10쪽이내", "10쪽 이내"]) == find_limits(["10쪽 이내"])[:1] or len(find_limits(["10쪽이내", "10쪽 이내"])) == 1


def test_cli_pages_warns_exclusion(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    src = _doc(blank, ["※ 본문 1쪽 이내(표지 제외)", "제1장 서론", LONG]).save(tmp_path / "a.hwpx")
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge, "page_map", lambda p: (2, ["표지", "제1장 서론\r\n본문"]))
    assert main(["pages", str(src)]) == 0
    assert "제외 조건" in capsys.readouterr().out


def test_chapter_limit_not_used_as_whole(blank):
    """I4: 장 안에 있는 '연구목표 (1쪽 이내)'는 전체 제한으로 고르지 않는다."""
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["제1장 연구 개요", "연구목표 (1쪽 이내)", LONG, "제2장 방법", LONG])
    r = measure(pkg, ["제1장 연구 개요\r\n제2장 방법"], 1)
    assert r["limit"] is None and len(r["limits"]) == 1 and r["limits"][0]["global"] is False


def test_multi_section_warns(blank):
    """I6: 둘째 구역 이후는 보지 않았다고 알린다."""
    from hwpxkit.fit import guide_items, measure
    from hwpxkit.package import Package as P
    pkg = _doc(blank, ["제1장 서론", LONG])
    pkg.write("Contents/section1.xml", pkg.read(SECTION))
    hpf = pkg.edit("Contents/content.hpf")
    from hwpxkit.ns import q
    item = next(i for i in hpf.iter(q("opf:item")) if i.get("href") == SECTION)
    new = item.makeelement(item.tag, dict(item.attrib, id="section1", href="Contents/section1.xml"))
    item.addnext(new)
    ref = next(hpf.iter(q("opf:itemref")))
    ref.addnext(ref.makeelement(ref.tag, dict(ref.attrib, idref="section1")))
    assert len(pkg.section_names()) == 2
    assert any("구역" in w for w in measure(pkg, ["제1장 서론"], 1)["warnings"])
    assert any("구역" in w for w in guide_items(pkg)["warnings"])


def test_guide_notes_inside_form_table_and_banner(blank):
    """I7: 큰 양식 표 칸 안의 ※ 안내도 뽑고, 1칸 장 제목 표는 상자가 아니라 제목, 같은 안내는 장마다."""
    from hwpxkit.fit import guide_items
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, texts={(0, 0): "과제명", (0, 1): "", (1, 0): "내용",
                                            (1, 1): ["", "※ 추진 배경을 포함하여 작성"]}))
    append_to_body(pkg, table(1, 1, texts={(0, 0): "제1장 서론"}))
    append_to_body(pkg, para("※ 표·그림을 활용하여 작성"))
    append_to_body(pkg, para("제2장 방법"))
    append_to_body(pkg, para("※ 표·그림을 활용하여 작성"))
    append_to_body(pkg, para(LONG))
    secs = {s["title"]: [i["text"] for i in s["items"]] for s in guide_items(pkg)["sections"]}
    assert secs["(앞부분)"] == ["※ 추진 배경을 포함하여 작성"]
    assert secs["제1장 서론"] == ["※ 표·그림을 활용하여 작성"]
    assert secs["제2장 방법"] == ["※ 표·그림을 활용하여 작성"]


def test_guide_box_with_nested_table(blank):
    """I7: 1칸 상자 안에 작은 표가 있어도 상자로 본다."""
    from hwpxkit.fit import guide_items
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    box = append_to_body(pkg, table(1, 1, texts={(0, 0): ["작성 요령", "- 배경을 기술"]}))
    next(box.iter(q("hp:subList"))).append(table(1, 2, texts={(0, 0): "예", (0, 1): "값"}))
    append_to_body(pkg, para(LONG))
    items = guide_items(pkg)["sections"][0]["items"]
    assert {"kind": "요령", "text": "- 배경을 기술"} in items


def test_sections_same_page():
    from hwpxkit.fit import sections_from_pages
    out = sections_from_pages([(0, "제1장", 1), (2, "제2장", 1)], [(3, True), (3, False)], 3)
    assert [(s["start"], s["end"]) for s in out] == [(3, 3), (3, 3)]
    assert out[0]["score"] is None and out[0]["level"] == 1


def test_measure_with_limit(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["※ 본문은 2쪽 이내로 작성", "제1장 서론〔10점〕", LONG, "제2장 방법〔30점〕", LONG])
    pages = ["※ 본문은 2쪽 이내로 작성\r\n제1장 서론〔10점〕\r\n본문", "제2장 방법〔30점〕\r\n본문", "본문 계속"]
    r = measure(pkg, pages, 3)
    assert r["pages"] == 3 and r["limit"]["pages"] == 2 and len(r["limits"]) == 1
    assert [(s["title"], s["start"], s["end"], s["score"]) for s in r["sections"]] == [
        ("제1장 서론〔10점〕", 1, 1, 10), ("제2장 방법〔30점〕", 2, 3, 30)]
    assert measure(pkg, pages, 3, limit=5)["limit"]["pages"] == 5


def test_measure_many_limits_none(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["본문 10쪽 이내", "요약 2쪽 이내", "제1장 서론", LONG])
    r = measure(pkg, ["본문 10쪽 이내\r\n요약 2쪽 이내\r\n제1장 서론"], 1)
    assert r["limit"] is None and len(r["limits"]) == 2


def test_page_map_reads_bridge(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"] = action
        return {"ok": True, "total": 2, "texts": ["가", "나"]}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"x")
    assert bridge.page_map(src) == (2, ["가", "나"]) and seen["action"] == "pagemap"


def test_cli_pages_text_and_json(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    pkg = _doc(blank, ["※ 본문은 2쪽 이내로 작성", "제1장 서론〔10점〕", LONG, "제2장 방법〔30점〕", LONG])
    src = pkg.save(tmp_path / "보고서.hwpx")
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge, "page_map", lambda p: (3, ["제1장 서론〔10점〕\r\n본문", "제2장 방법〔30점〕\r\n본문", "계속"]))
    assert main(["pages", str(src)]) == 0
    out = capsys.readouterr().out
    assert "전체 3쪽" in out and "2쪽 이내" in out and "1쪽 넘음" in out and "제2장 방법〔30점〕" in out and "2~3쪽" in out
    assert main(["pages", str(src), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pages"] == 3 and data["sections"][1]["count"] == 2


@pytest.mark.hangul
def test_page_map_with_hangul(blank, tmp_path):
    from hwpxkit import bridge
    from hwpxkit.fit import measure
    from hwpxkit.render import render_into
    from hwpxkit.samples import infer
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    md = "# 제1장 서론\n\n" + LONG + "\n\n---쪽---\n\n# 제2장 방법\n\n" + LONG + "\n\n---쪽---\n\n# 제3장 결론\n\n" + LONG + "\n"
    render_into(pkg, infer(pkg), md)
    src = pkg.save(tmp_path / "세쪽.hwpx")
    total, texts = bridge.page_map(src)
    r = measure(Package.open(src), texts, total)
    assert total == 3 and [(s["start"], s["end"]) for s in r["sections"]] == [(1, 1), (2, 2), (3, 3)]
    assert not r["warnings"]
