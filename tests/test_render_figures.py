import pytest

from helpers import SECTION, report_template, tiny_png
from hwpxkit import bridge
from hwpxkit.body import all_text, own_text
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import RenderError, render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate


@pytest.fixture
def tpl(blank, tmp_path):
    pkg = Package.open(blank)
    report_template(pkg)
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "flow.png").write_bytes(tiny_png((1411, 645)))
    return pkg, infer(pkg), tmp_path


def pics(pkg):
    return list(pkg.xml(SECTION).iter(q("hp:pic")))


def test_figure_from_sample_with_caption(tpl):
    pkg, cat, base = tpl
    render_into(pkg, cat, "# 제1장 서론\n\n![매칭 흐름](figs/flow.png){#fig:flow}\n\n[@fig:flow]을 보라.",
                base_dir=base)
    (pic,) = pics(pkg)
    bid = pic.find(q("hc:img")).get("binaryItemIDRef")
    assert pkg.manifest()[bid].endswith(".png")
    assert all_text(pic.find(q("hp:caption"))) == "[그림 1-1] 매칭 흐름"
    assert pic.find(f".//{q('hp:autoNum')}") is None
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert "[그림 1-1]을 보라." in texts
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_large_image_fits_text_width(tpl):
    pkg, cat, base = tpl
    render_into(pkg, cat, "![큰 그림](figs/flow.png){width=50%}", base_dir=base)
    (pic,) = pics(pkg)
    from hwpxkit.layout import page_geometry
    w = int(pic.find(q("hp:sz")).get("width"))
    h = int(pic.find(q("hp:sz")).get("height"))
    assert w == int(page_geometry(pkg).text_width * 0.5)
    assert h == pytest.approx(w * 645 / 1411, abs=2)


def test_bmp_is_converted_to_png(tpl):
    pkg, cat, base = tpl
    (base / "figs" / "old.bmp").write_bytes(tiny_png((40, 20), fmt="BMP"))
    render_into(pkg, cat, "![옛 그림](figs/old.bmp)", base_dir=base)
    bid = pics(pkg)[0].find(q("hc:img")).get("binaryItemIDRef")
    href = pkg.manifest()[bid]
    assert href.endswith(".png") and pkg.read(href)[:4] == b"\x89PNG"


def test_missing_image_raises(tpl):
    pkg, cat, base = tpl
    with pytest.raises(RenderError, match="찾을 수 없"):
        render_into(pkg, cat, "![없음](figs/none.png)", base_dir=base)


def test_figure_ids_unique(tpl):
    pkg, cat, base = tpl
    render_into(pkg, cat, "![a](figs/flow.png)\n\n![b](figs/flow.png)", base_dir=base)
    a, b = pics(pkg)
    assert a.get("id") != b.get("id") and a.get("instid") != b.get("instid")


def test_duplicate_label_raises(tpl):
    pkg, cat, base = tpl
    with pytest.raises(RenderError, match="두 번"):
        render_into(pkg, cat, "![a](figs/flow.png){#fig:x}\n\n![b](figs/flow.png){#fig:x}", base_dir=base)


def test_fallback_without_sample_puts_hangul_caption(tpl):
    """견본 그림이 없어도 제목은 그림에 붙은 한글 캡션(아래쪽)으로 넣는다 (사용자 요청)."""
    pkg, cat, base = tpl
    cat.figure_para = None
    render_into(pkg, cat, "![대체](figs/flow.png)", base_dir=base)
    (pic,) = pics(pkg)
    cap = pic.find(q("hp:caption"))
    assert cap is not None and cap.get("side") == "BOTTOM" and all_text(cap) == "[그림 1-1] 대체"
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert "[그림 1-1] 대체" not in texts
    assert [i for i in validate(pkg) if i.level == "error"] == []


@pytest.mark.hangul
def test_figures_open_in_hangul(tpl, tmp_path):
    pkg, cat, base = tpl
    render_into(pkg, cat, "# 제1장 서론\n\n![견본 복제](figs/flow.png){width=70%}", base_dir=base)
    cat.figure_para = None
    render_into(pkg, cat, "![기본 골격](figs/flow.png){width=40%}", mode="append", base_dir=base)
    out = pkg.save(tmp_path / "figs.hwpx")
    assert bridge.check(out) >= 1
    assert bridge.page_images(out, tmp_path / "pages")


def test_bindata_path_reuses_package_image(tpl, tmp_path):
    pkg, cat, _ = tpl
    href = next(h for h in pkg.manifest().values() if h.startswith("BinData/"))
    render_into(pkg, cat, f"![다시 쓴 그림]({href})", base_dir=tmp_path / "빈 폴더")
    (pic,) = pics(pkg)
    new_href = pkg.manifest()[pic.find(q("hc:img")).get("binaryItemIDRef")]
    assert pkg.read(new_href) == pkg.read(href)


def test_tall_image_fits_page_height(tpl):
    pkg, cat, base = tpl
    (base / "figs" / "tall.png").write_bytes(tiny_png((400, 6000)))
    render_into(pkg, cat, "![긴 그림](figs/tall.png){width=150%}", base_dir=base)
    (pic,) = pics(pkg)
    from hwpxkit.layout import page_geometry
    g = page_geometry(pkg)
    assert int(pic.find(q("hp:sz")).get("height")) <= g.text_height
    assert int(pic.find(q("hp:sz")).get("width")) <= g.text_width
