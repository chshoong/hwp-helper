import pytest
from lxml import etree

from helpers import append_to_body, para
from hwpxkit import bridge
from hwpxkit.header import Header
from hwpxkit.package import Package


def names(el):
    return [etree.QName(c).localname for c in el]


def test_blank_has_basic_refs(blank):
    h = Header(Package.open(blank))
    for kind in ("charPr", "paraPr", "style"):
        assert "0" in h.ids(kind), kind
    assert "1" in h.ids("borderFill")
    assert "함초롬바탕" in h.fonts("HANGUL").values()
    assert h.style_id("바탕글") == "0"
    assert h.style_id("없는 스타일") is None


def test_get_unknown_id_raises(blank):
    with pytest.raises(KeyError):
        Header(Package.open(blank)).get("charPr", "9999")


def test_derive_identity_returns_base(blank):
    h = Header(Package.open(blank))
    assert h.derive("charPr", "0", lambda e: None) == "0"


def test_derive_bold_creates_once_and_reuses(blank):
    h = Header(Package.open(blank))
    n = len(h.ids("charPr"))
    a = h.derive_charpr("0", bold=True)
    b = h.derive_charpr("0", bold=True)
    assert a == b
    assert len(h.ids("charPr")) == n + 1
    el = h.get("charPr", a)
    assert names(el).index("bold") == names(el).index("offset") + 1
    assert el.getparent().get("itemCnt") == str(n + 1)


def test_derive_italic_goes_before_bold(blank):
    h = Header(Package.open(blank))
    el = h.get("charPr", h.derive_charpr("0", bold=True, italic=True))
    assert names(el).index("italic") < names(el).index("bold")


def test_derive_color_keeps_fonts(blank):
    h = Header(Package.open(blank))
    cid = h.derive_charpr("0", color="#0000FF", height=1200)
    el = h.get("charPr", cid)
    assert el.get("textColor") == "#0000FF" and el.get("height") == "1200"
    assert h.charpr_faces(cid) == h.charpr_faces("0")


def test_unbold_removes_tag(blank):
    h = Header(Package.open(blank))
    bold = h.derive_charpr("0", bold=True)
    assert h.derive_charpr(bold, bold=False) == "0"


def test_derived_header_survives_save(blank, tmp_path):
    pkg = Package.open(blank)
    cid = Header(pkg).derive_charpr("0", bold=True)
    again = Header(Package.open(pkg.save(tmp_path / "o.hwpx")))
    assert "bold" in names(again.get("charPr", cid))


@pytest.mark.hangul
def test_derived_charpr_opens_in_hangul(blank, tmp_path):
    pkg = Package.open(blank)
    cid = Header(pkg).derive_charpr("0", bold=True, color="#0000FF")
    append_to_body(pkg, para("파란 굵은 글씨", char_pr=cid))
    assert bridge.check(pkg.save(tmp_path / "o.hwpx")) == 1
