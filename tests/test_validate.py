import pytest
from lxml import etree

from helpers import append_to_body, para, table
from hwpxkit import bridge
from hwpxkit.ns import q
from hwpxkit.package import CONTENT_HPF, HEADER, Package
from hwpxkit.validate import autofix, validate


def codes(issues):
    return {i.code for i in issues}


def test_blank_is_clean(blank):
    assert validate(Package.open(blank)) == []


def test_bad_charpr_ref(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para("x", char_pr="999"))
    issues = validate(pkg)
    assert "bad-ref" in codes(issues)
    assert any("999" in i.message and i.level == "error" for i in issues)


def test_bad_bin_ref(blank):
    pkg = Package.open(blank)
    p = append_to_body(pkg, para("그림"))
    p.find(q("hp:run")).append(etree.Element(q("hc:img"), binaryItemIDRef="image99"))
    assert "bad-bin-ref" in codes(validate(pkg))


def test_valid_merged_table_passes(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, spans={(0, 0): (1, 2)}, skip={(0, 1)}))
    assert validate(pkg) == []


def test_overlap_detected(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, spans={(0, 0): (1, 2)}))
    issues = validate(pkg)
    assert "table-overlap" in codes(issues)
    assert any("1행" in i.message and "2열" in i.message for i in issues)


def test_hole_detected(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, skip={(1, 1)}))
    assert "table-hole" in codes(validate(pkg))


def test_span_outside_table(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, spans={(1, 1): (2, 1)}))
    assert "table-span" in codes(validate(pkg))


def test_row_count_mismatch(blank):
    pkg = Package.open(blank)
    p = append_to_body(pkg, table(2, 2))
    p.find(f".//{q('hp:tbl')}").set("rowCnt", "3")
    assert "table-rows" in codes(validate(pkg))


def test_manifest_missing_file(blank):
    pkg = Package.open(blank)
    man = pkg.edit(CONTENT_HPF).find(q("opf:manifest"))
    etree.SubElement(man, q("opf:item"), {"id": "ghost", "href": "BinData/ghost.png", "media-type": "image/png"})
    assert "manifest-missing" in codes(validate(pkg))


def test_font_missing(blank):
    pkg = Package.open(blank)
    root = pkg.edit(HEADER)
    root.find(f".//{q('hh:charPr')}/{q('hh:fontRef')}").set("hangul", "99")
    assert "font-missing" in codes(validate(pkg))


def test_item_count_warning_and_autofix(blank):
    pkg = Package.open(blank)
    pkg.edit(HEADER).find(f".//{q('hh:charProperties')}").set("itemCnt", "1")
    issues = validate(pkg)
    assert [i.level for i in issues if i.code == "item-count"] == ["warning"]
    fixed = autofix(pkg)
    assert len(fixed) == 1 and "charProperties" in fixed[0]
    assert validate(pkg) == []


@pytest.mark.hangul
def test_valid_merged_table_opens_in_hangul(blank, tmp_path):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 3, spans={(0, 0): (1, 2), (0, 2): (2, 1)}, skip={(0, 1), (1, 2)},
                              texts={(0, 0): "병합 머리", (0, 2): "세로 병합", (1, 0): "가", (1, 1): "나"}))
    assert validate(pkg) == []
    assert bridge.check(pkg.save(tmp_path / "o.hwpx")) == 1


def test_real_reports_have_no_errors(private_dir):
    for name in ("monthly.hwpx", "final.hwpx"):
        errors = [i for i in validate(Package.open(private_dir / name)) if i.level == "error"]
        assert errors == [], (name, errors[:5])


def test_none_sentinel_id_is_allowed(blank):
    # 한글은 '참조 없음'을 4294967295(= -1)로 쓴다 (예: 글머리 paraHead의 charPrIDRef)
    pkg = Package.open(blank)
    append_to_body(pkg, para("x", char_pr="4294967295"))
    assert "bad-ref" not in codes(validate(pkg))
