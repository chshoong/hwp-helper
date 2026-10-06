import pytest

from helpers import SECTION
from hwpxkit.layout import distribute, fit_image, hu_to_mm, mm_to_hu, page_geometry, px_to_hu
from hwpxkit.ns import q
from hwpxkit.package import Package


def test_unit_conversions():
    assert mm_to_hu(210) == 59528      # A4 가로 (월간보고서 pagePr width와 같음)
    assert mm_to_hu(297) == 84189
    assert hu_to_mm(7200) == pytest.approx(25.4)
    assert px_to_hu(96) == 7200
    assert px_to_hu(300, dpi=300) == 7200


def test_blank_geometry_is_a4_portrait(blank):
    g = page_geometry(Package.open(blank))
    assert (g.width, g.height) == (59528, 84186)  # 한글 2024가 만든 빈 문서 값
    assert not g.landscape
    assert g.text_width == g.width - g.left - g.right - g.gutter
    assert 140 < hu_to_mm(g.text_width) < 170


def test_landscape_uses_long_side_as_width(blank):
    pkg = Package.open(blank)
    page = next(pkg.edit(SECTION).iter(q("hp:pagePr")))
    page.set("landscape", "NARROWLY")
    g = page_geometry(pkg)
    assert g.landscape and g.width > g.height


def test_monthly_text_width(private_dir):
    g = page_geometry(Package.open(private_dir / "monthly.hwpx"))
    assert g.text_width == 59528 - 4251 - 4251


def test_fit_image_shrinks_keeping_ratio():
    w, h = fit_image(2000, 1000, max_width_hu=40000)
    assert w == 40000 and h == 20000


def test_fit_image_never_enlarges():
    assert fit_image(96, 48, max_width_hu=40000) == (7200, 3600)


def test_fit_image_ratio():
    w, h = fit_image(2000, 1000, max_width_hu=40000, ratio=0.5)
    assert (w, h) == (20000, 10000)


def test_fit_image_rejects_zero():
    with pytest.raises(ValueError):
        fit_image(0, 10, max_width_hu=1000)


def test_distribute_sums_exactly():
    cols = distribute(51026, [1, 2, 2])
    assert sum(cols) == 51026 and len(cols) == 3
    assert cols[1] == cols[2] or abs(cols[1] - cols[2]) <= 2


def test_distribute_rejects_bad_weights():
    with pytest.raises(ValueError):
        distribute(1000, [1, 0])
    with pytest.raises(ValueError):
        distribute(1000, [])


def test_fit_image_limits_height_and_clamps_ratio():
    w, h = fit_image(400, 6000, max_width_hu=42520, max_height_hu=60000)
    assert h == 60000 and w == round(400 * 75 * 60000 / (6000 * 75))
    assert fit_image(2000, 1000, max_width_hu=40000, ratio=1.5) == (40000, 20000)
