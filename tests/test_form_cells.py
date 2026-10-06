import pytest

from helpers import monthly_form
from hwpxkit import bridge
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.samples import infer
from hwpxkit.validate import validate


@pytest.fixture
def form(blank):
    pkg = Package.open(blank)
    ids = monthly_form(pkg)
    return pkg, ids


def test_monthly_fixture_is_valid(form):
    pkg, _ = form
    assert [i for i in validate(pkg) if i.level == "error"] == []
    assert len(list(pkg.xml("Contents/section0.xml").iter(q("hp:tbl")))) == 3


def test_infer_unchanged_after_learn_split(form):
    pkg, _ = form
    cat = infer(pkg)
    assert "body" in cat.paras or "blank" in cat.paras


@pytest.mark.hangul
def test_monthly_fixture_opens_in_hangul(form, tmp_path):
    pkg, _ = form
    assert bridge.check(pkg.save(tmp_path / "m.hwpx")) >= 1


from hwpxkit.form import FormError, cells, find_cell


def test_cells_have_headers(form):
    pkg, _ = form
    t2 = [c for c in cells(pkg) if c.table == 2]
    target = next(c for c in t2 if (c.row, c.col) == (1, 1))
    assert target.row_header.startswith("가상 분야")
    assert target.col_header == "금월 추진실적(26. 02.)"
    assert "기초 자료 점검 및 정리" in target.text
    assert target.label() == "[표2] 가상 분야 표본 데이터 모델 개발 및 품질 평가 × 금월 추진실적(26. 02.)"


def test_find_cell_by_partial_headers(form):
    pkg, _ = form
    c = find_cell(pkg, 2, "가상 분야", "금월 추진실적")
    assert (c.row, c.col) == (1, 1)
    c = find_cell(pkg, 2, "요청 사항", None)
    assert (c.row, c.col, c.colspan) == (3, 1, 2)


def test_find_cell_by_numbers(form):
    pkg, _ = form
    c = find_cell(pkg, 1, 2, 1)
    assert c.text == "12.5%"
    c = find_cell(pkg, 2, 1, 2)
    assert c.text == "금월 추진실적(26. 02.)"


def test_ambiguous_key_lists_candidates(form):
    pkg, _ = form
    with pytest.raises(FormError, match="여러 칸") as e:
        find_cell(pkg, 2, "가상", "향후")
    assert "가상 분야" in str(e.value) and "활용 서비스" in str(e.value)


def test_unknown_table_and_cell(form):
    pkg, _ = form
    with pytest.raises(FormError, match="표9"):
        find_cell(pkg, 9, 1, 1)
    with pytest.raises(FormError, match="맞는 칸이 없어요"):
        find_cell(pkg, 2, "없는 행", "금월")


def test_real_monthly_cells(private_dir, expected):
    pkg = Package.open(private_dir / "monthly.hwpx")
    c = find_cell(pkg, 3, expected["monthly_row"], "금월 추진실적")
    assert expected["monthly_first_item"] in c.text
    c = find_cell(pkg, 4, 2, "상세 추진 내용")
    assert c.text == "상세 추진 내용"
