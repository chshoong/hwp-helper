import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import preset_kit as kit  # noqa: E402
from hwpxkit.header import Header  # noqa: E402
from hwpxkit.layout import mm_to_hu, page_geometry  # noqa: E402
from hwpxkit.ns import q  # noqa: E402
from hwpxkit.package import Package  # noqa: E402
from hwpxkit.validate import validate  # noqa: E402

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


@pytest.fixture
def h(blank):
    return Header(Package.open(blank))


def test_font_registered_in_every_language(h):
    kit.font_id(h, "휴먼명조")
    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"):
        assert "휴먼명조" in h.fonts(lang).values(), lang
    assert kit.font_id(h, "휴먼명조") == kit.font_id(h, "휴먼명조")


def test_char_shape(h):
    cid = kit.char(h, 15, bold=True, font="휴먼명조", color="#1F3864")
    el = h.get("charPr", cid)
    assert el.get("height") == "1500" and el.get("textColor") == "#1F3864"
    assert el.find(f"{HH}bold") is not None
    assert h.charpr_faces(cid)["HANGUL"] == "휴먼명조" and h.charpr_faces(cid)["LATIN"] == "휴먼명조"


def test_para_shape(h):
    pid = kit.para(h, align="CENTER", left_mm=5, indent_mm=-3, prev_pt=6, next_pt=3, line=170, keep_next=True)
    el = h.get("paraPr", pid)
    assert el.find(f"{HH}align").get("horizontal") == "CENTER"
    lefts = {m.get("value") for m in el.iter("{http://www.hancom.co.kr/hwpml/2011/core}left")}
    assert lefts == {str(mm_to_hu(5))}
    assert {s.get("value") for s in el.iter(f"{HH}lineSpacing")} == {"170"}
    assert el.find(f"{HH}breakSetting").get("keepWithNext") == "1"


def test_bullets_and_bullet_para(h):
    ids = kit.add_bullets(h, ["□", "○"])
    pid = kit.para(h, bullet=ids[1])
    head = h.get("paraPr", pid).find(f"{HH}heading")
    assert (head.get("type"), head.get("idRef")) == ("BULLET", ids[1])
    assert kit.add_bullets(h, ["□"]) == [ids[0]]


def test_page_and_table_valid(blank):
    pkg = Package.open(blank)
    h = Header(pkg)
    kit.set_page(pkg, top=20, bottom=15, left=20, right=20, header=10, footer=10)
    g = page_geometry(pkg)
    assert g.left == mm_to_hu(20) and g.top == mm_to_hu(20)
    head = (kit.para(h, align="CENTER"), kit.char(h, 10, bold=True, font="함초롬돋움"))
    body = (kit.para(h), kit.char(h, 10, font="함초롬돋움"))
    t = kit.table(2, 3, width=g.text_width, head_bf=kit.fill_border(h, "#E7E6E6"), body_bf=kit.fill_border(h, "none"),
                  head=head, body=body, texts={(0, 0): "구분"})
    pkg.edit("Contents/section0.xml").append(t)
    assert [i for i in validate(pkg) if i.level == "error"] == []
