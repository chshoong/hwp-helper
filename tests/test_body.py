from lxml import etree

from helpers import SECTION, append_to_body, para, table
from hwpxkit.body import IdAllocator, all_text, contains, is_blank, own_text, strip_lineseg, top_paragraphs
from hwpxkit.ns import q
from hwpxkit.package import Package


def test_own_text_excludes_table_text(blank):
    pkg = Package.open(blank)
    p = append_to_body(pkg, table(1, 1, texts={(0, 0): "칸 글자"}))
    p.find(q("hp:run")).append(etree.Element(q("hp:t")))
    p.find(q("hp:run"))[-1].text = "문단 글자"
    assert own_text(p) == "문단 글자"
    assert "칸 글자" in all_text(p)
    assert contains(p, "hp:tbl") and not contains(p, "hp:pic")


def test_t_text_includes_tab_tails(blank):
    p = para("")
    t = p.find(f"{q('hp:run')}/{q('hp:t')}")
    t.text = "제1장 서론"
    tab = etree.SubElement(t, q("hp:tab"))
    tab.tail = "3"
    assert own_text(p) == "제1장 서론3"


def test_is_blank(blank):
    assert is_blank(para(""))
    assert not is_blank(para("글"))
    assert not is_blank(table(1, 1))


def test_top_paragraphs_are_direct_children(blank):
    pkg = Package.open(blank)
    n = len(top_paragraphs(pkg))
    append_to_body(pkg, table(2, 2))
    assert len(top_paragraphs(pkg)) == n + 1


def test_strip_lineseg():
    p = para("x")
    etree.SubElement(p, q("hp:linesegarray"))
    strip_lineseg(p)
    assert p.find(q("hp:linesegarray")) is None


def test_id_allocator_gives_unique_ids(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(1, 1))
    ids = IdAllocator(pkg)
    a, b = table(1, 1), table(1, 1)
    ids.refresh(a)
    ids.refresh(b)
    got = [next(x.iter(q("hp:tbl"))).get("id") for x in (a, b)]
    existing = next(pkg.xml(SECTION).iter(q("hp:tbl"))).get("id")
    assert len({*got, existing}) == 3
