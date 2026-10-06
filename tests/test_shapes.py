import pytest

from helpers import report_template
from hwpxkit import bridge, shapes
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.validate import validate


def test_solid_border_fill_is_solid_and_reused(blank):
    h = Header(Package.open(blank))
    a = shapes.solid_border_fill(h)
    assert shapes.solid_border_fill(h) == a
    bf = h.get("borderFill", a)
    for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        assert bf.find(q(f"hh:{side}")).get("type") == "SOLID"


def test_new_picture_geometry():
    pic = shapes.new_picture("image7", 1411, 645, 41550, 18993, "흐름.png")
    assert pic.find(q("hc:img")).get("binaryItemIDRef") == "image7"
    assert pic.find(q("hp:imgDim")).get("dimwidth") == str(1411 * 75)
    assert pic.find(q("hp:sz")).get("width") == "41550"
    assert pic.find(q("hp:curSz")).get("height") == "18993"
    assert pic.find(q("hp:pos")).get("treatAsChar") == "1"
    sca = pic.find(f"{q('hp:renderingInfo')}/{q('hc:scaMatrix')}")
    assert float(sca.get("e1")) == pytest.approx(41550 / (1411 * 75), rel=1e-4)
    assert "흐름.png" in pic.findtext(q("hp:shapeComment"))


def test_set_caption_replaces_autonum():
    cap = shapes.new_caption("[그림 1-1] 옛 제목", 9000, "0", "0", "0")
    run = cap.find(f".//{q('hp:run')}")
    run.append(shapes.etree.Element(q("hp:ctrl")))
    shapes.set_caption(cap, "[그림 2-3] 새 제목", 12000)
    assert cap.find(f".//{q('hp:ctrl')}") is None
    assert "".join(cap.itertext()) == "[그림 2-3] 새 제목"
    assert cap.get("lastWidth") == "12000"


def test_report_template_is_valid(blank):
    pkg = Package.open(blank)
    report_template(pkg)
    assert [i for i in validate(pkg) if i.level == "error"] == []


@pytest.mark.hangul
def test_report_template_opens_in_hangul(blank, tmp_path):
    pkg = Package.open(blank)
    report_template(pkg)
    out = pkg.save(tmp_path / "견본.hwpx")
    assert bridge.check(out) >= 1
