"""분량(쪽수·제한·배점)과 작성 요령 항목 (pages, guide)."""
import json

import pytest

from helpers import LONG, SECTION, append_to_body, para, table
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


def test_sections_from_pages():
    from hwpxkit.fit import sections_from_pages
    heads = [(1, "제1장 서론〔10점〕", 1), (3, "1.1 배경", 2), (5, "제2장 방법", 1)]
    out = sections_from_pages(heads, [1, 1, 1, 2, 2, 3, 3], 4)
    assert [(s["title"], s["start"], s["end"], s["count"]) for s in out] == [
        ("제1장 서론〔10점〕", 1, 2, 2), ("1.1 배경", 2, 2, 1), ("제2장 방법", 3, 4, 2)]
    assert out[0]["score"] == 10 and out[1]["score"] is None and out[1]["level"] == 2


def test_sections_same_page():
    from hwpxkit.fit import sections_from_pages
    out = sections_from_pages([(0, "제1장", 1), (2, "제2장", 1)], [3, 3, 3], 3)
    assert [(s["start"], s["end"]) for s in out] == [(3, 3), (3, 3)]


def _doc(blank, paras):
    pkg = Package.open(blank)
    for p in paras:
        append_to_body(pkg, para(p))
    return pkg


def test_measure_with_limit(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["※ 본문은 2쪽 이내로 작성", "제1장 서론〔10점〕", LONG, "제2장 방법〔30점〕", LONG])
    r = measure(pkg, [1, 1, 1, 1, 2, 3], 3)
    assert r["pages"] == 3 and r["limit"]["pages"] == 2 and len(r["limits"]) == 1
    assert [(s["title"], s["start"], s["end"]) for s in r["sections"]] == [("제1장 서론〔10점〕", 1, 1),
                                                                            ("제2장 방법〔30점〕", 2, 3)]
    assert measure(pkg, [1, 1, 1, 1, 2, 3], 3, limit=5)["limit"] == {"pages": 5, "kind": "이내", "text": "--limit"}


def test_measure_many_limits_none(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["본문 10쪽 이내", "요약 2쪽 이내", "제1장 서론", LONG])
    r = measure(pkg, [1, 1, 1, 1, 1], 1)
    assert r["limit"] is None and len(r["limits"]) == 2


def test_measure_mismatch_warns(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["제1장 서론", LONG, "제2장 방법", LONG])
    r = measure(pkg, [1, 1, 1], 2)  # 한글이 문단 하나를 덜 셈
    assert r["warnings"] and r["sections"][0]["start"] == 1


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


def test_page_map_reads_bridge(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"] = action
        return {"ok": True, "total": 3, "paras": [1, 1, 2, 3]}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"x")
    assert bridge.page_map(src) == (3, [1, 1, 2, 3]) and seen["action"] == "pagemap"


def test_cli_pages_text_and_json(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    pkg = _doc(blank, ["※ 본문은 2쪽 이내로 작성", "제1장 서론〔10점〕", LONG, "제2장 방법〔30점〕", LONG])
    src = pkg.save(tmp_path / "보고서.hwpx")
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge, "page_map", lambda p: (3, [1, 1, 1, 1, 2, 3]))
    assert main(["pages", str(src)]) == 0
    out = capsys.readouterr().out
    assert "전체 3쪽" in out and "2쪽 이내" in out and "1쪽 넘음" in out and "제2장 방법〔30점〕" in out and "2~3쪽" in out
    assert main(["pages", str(src), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pages"] == 3 and data["sections"][1]["count"] == 2


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
    total, paras = bridge.page_map(src)
    r = measure(Package.open(src), paras, total)
    assert total == 3 and [s["start"] for s in r["sections"]] == [1, 2, 3] and not r["warnings"]


def test_skill_documents_fit():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "fit.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" pages', 'hwpx.py" guide', "--limit", "render", "--replace", "지어내지", "3번"):
        assert word in text, word
    assert "reference/fit.md" in (root / "SKILL.md").read_text(encoding="utf-8")


def test_section_ends_where_next_heading_starts_mid_page():
    """앞 장은 다음 제목 바로 앞 문단의 쪽까지 (다음 장이 쪽 중간에서 시작하면 그 쪽을 함께 씀)."""
    from hwpxkit.fit import sections_from_pages
    out = sections_from_pages([(0, "가", 1), (3, "나", 1)], [1, 1, 2, 2, 3], 3)
    assert [(s["start"], s["end"]) for s in out] == [(1, 2), (2, 3)]
