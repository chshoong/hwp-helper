import pytest

from hwpxkit import bridge
from hwpxkit.form import find_cell
from hwpxkit.header import Header
from hwpxkit.package import Package
from hwpxkit.presets import listing, path
from hwpxkit.render import render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate

NAMES = ["rnd-report", "gov-brief", "paper", "progress"]
EXPECT = {
    "rnd-report": ({"h1", "h2", "h3", "h4", "bullet1", "bullet2", "bullet3", "body", "caption_tbl"}, "함초롬바탕"),
    "gov-brief": ({"h1", "h2", "bullet1", "bullet2", "bullet3", "bullet4", "caption_tbl"}, "휴먼명조"),
    "paper": ({"h1", "h2", "body", "bullet2", "bullet3", "caption_tbl"}, "함초롬바탕"),
}
DEMO = {
    "rnd-report": "# 제1장 서론\n\n## 1.1. 배경\n\n□ 주요 내용\n○ 세부\n\n본문 문장이 이어진다. 수식 $x^2$도 있다.\n\n"
                  "표: 비교 {#tbl:a}\n| 구분 | 값 |\n| a | 1 |\n\n$$ y = ax + b $$\n",
    "gov-brief": "# Ⅰ. 개요\n\n## 1. 추진 배경\n\n□ 데이터 결합 수요 증가\n○ 행정자료 활용 확대\n- 세부 사항\n\n"
                 "표: 현황\n| 구분 | 내용 |\n| 가 | 나 |\n",
    "paper": "# 1. 서론\n\n## 1.1. 배경\n\n본문 문단이다. 식 $\\hat{\\beta}$를 쓴다.\n\n표: 결과\n| 모형 | 값 |\n| A | 0.9 |\n",
}


def test_listing_has_four_presets():
    names = [p["name"] for p in listing()]
    assert names == NAMES
    assert all(p["title"] and p["description"] and p["levels"] for p in listing())
    with pytest.raises(ValueError, match="프리셋"):
        path("없는-프리셋")


@pytest.mark.parametrize("name", NAMES)
def test_preset_is_valid_and_has_preview(name):
    assert [i for i in validate(Package.open(path(name))) if i.level == "error"] == []
    assert (path(name).parent / "preview.png").is_file()


@pytest.mark.parametrize("name", list(EXPECT))
def test_preset_roles_and_fonts(name):
    roles, face = EXPECT[name]
    pkg = Package.open(path(name))
    cat = infer(pkg)
    assert roles <= set(cat.paras), roles - set(cat.paras)
    assert cat.table_para is not None and cat.figure_para is not None
    assert cat.equation is not None and cat.eq_table_para is not None
    body = cat.paras.get("body") or cat.paras["bullet1"]
    assert Header(pkg).charpr_faces(body.char_pr)["HANGUL"] == face


@pytest.mark.parametrize("name", list(EXPECT))
def test_render_into_each_preset(name, tmp_path):
    pkg = Package.open(path(name))
    render_into(pkg, infer(pkg), DEMO[name])
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_progress_preset_is_a_form():
    from hwpxkit.ns import q
    from hwpxkit.samples import style_of
    pkg = Package.open(path("progress"))
    h = Header(pkg)
    assert "금월" in find_cell(pkg, 3, 1, 2).text
    assert find_cell(pkg, 4, 2, 2).text == "상세 추진 내용"
    cell = find_cell(pkg, 3, 2, 2)
    assert any(style_of(p, h).auto_bullet for p in cell.tc.iter(q("hp:p")))


@pytest.mark.hangul
@pytest.mark.parametrize("name", NAMES)
def test_presets_open_in_hangul(name):
    assert bridge.check(path(name)) >= 1


def test_fill_accepts_preset_name(tmp_path):
    from hwpxkit.cli import main
    spec = tmp_path / "f.md"
    spec.write_text("@칸 표4 | #2 | 상세 추진 내용\n· 규칙 점검 완료\n", encoding="utf-8")
    out = tmp_path / "m.hwpx"
    assert main(["fill", "progress", str(spec), str(out)]) == 0
    assert "규칙 점검 완료" in find_cell(Package.open(out), 4, 2, 2).text


@pytest.mark.parametrize("name", NAMES)
def test_preset_metadata_has_no_author(name):
    """프리셋 문서 정보에 만든 사람 이름·날짜가 없어야 한다 (사용자 결과 문서로 퍼짐, 최종 리뷰)."""
    from hwpxkit.ns import NS
    meta = Package.open(path(name)).xml("Contents/content.hpf")
    for m in meta.iter(f"{{{NS['opf']}}}meta"):
        if m.get("name") in ("creator", "lastsaveby", "CreatedDate", "ModifiedDate", "date"):
            assert not (m.text or "").strip(), (m.get("name"), m.text)


def test_documented_fill_addresses_match_progress_preset():
    """SKILL·form.md의 '@칸' 예시는 실제 progress 프리셋 칸을 가리켜야 한다 (실제 문서 내용 금지, 최종 리뷰)."""
    import re
    from hwpxkit import form
    from pathlib import Path
    skill = Path(__file__).resolve().parent.parent / "skills" / "hwp-helper"
    text = "\n".join(p.read_text(encoding="utf-8") for p in [skill / "SKILL.md", *(skill / "reference").glob("*.md")])
    lines = sorted(set(re.findall(r"@칸 표\d+ \|[^`\n]+?(?=`|\n)", text)))
    assert lines
    for line in lines:
        pkg = Package.open(path("progress"))
        form.fill(pkg, form.parse_fill(f"@행수 표4 | 5\n{line.strip()}\n가\n"))
