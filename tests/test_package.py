import zipfile

import pytest

from helpers import SECTION
from hwpxkit import bridge
from hwpxkit.ns import q
from hwpxkit.package import CONTENT_HPF, HEADER, Package, PackageError


def test_open_lists_parts(blank):
    pkg = Package.open(blank)
    assert pkg.names()[0] == "mimetype"
    assert pkg.has(HEADER) and pkg.has(CONTENT_HPF)
    assert pkg.section_names() == [SECTION]
    assert pkg.source == blank


def test_untouched_roundtrip_is_byte_identical(blank, tmp_path):
    out = Package.open(blank).save(tmp_path / "out.hwpx")
    with zipfile.ZipFile(blank) as a, zipfile.ZipFile(out) as b:
        assert [i.filename for i in b.infolist()] == [i.filename for i in a.infolist()]
        for info in a.infolist():
            assert b.read(info.filename) == a.read(info)
            assert b.getinfo(info.filename).compress_type == info.compress_type


def test_mimetype_first_and_stored(blank, tmp_path):
    pkg = Package.open(blank)
    pkg.write("Contents/extra.xml", b"<a/>")
    out = pkg.save(tmp_path / "o.hwpx")
    with zipfile.ZipFile(out) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/hwp+zip"
        assert z.namelist()[-1] == "Contents/extra.xml"


def test_edit_persists_and_other_parts_untouched(blank, tmp_path):
    pkg = Package.open(blank)
    first_p = next(pkg.edit(SECTION).iter(q("hp:p")))
    first_p.set("pageBreak", "1")
    out = pkg.save(tmp_path / "o.hwpx")
    again = Package.open(out)
    assert next(again.xml(SECTION).iter(q("hp:p"))).get("pageBreak") == "1"
    assert again.read(HEADER) == Package.open(blank).read(HEADER)


def test_xml_without_edit_is_not_saved(blank, tmp_path):
    pkg = Package.open(blank)
    next(pkg.xml(SECTION).iter(q("hp:p"))).set("pageBreak", "1")
    out = pkg.save(tmp_path / "o.hwpx")
    assert Package.open(out).read(SECTION) == Package.open(blank).read(SECTION)


def test_add_bin_registers_manifest(blank, tmp_path):
    pkg = Package.open(blank)
    bid = pkg.add_bin(b"\x89PNG fake", "png")
    bid2 = pkg.add_bin(b"jpgdata", ".JPG")
    assert bid != bid2
    again = Package.open(pkg.save(tmp_path / "o.hwpx"))
    assert again.manifest()[bid] == f"BinData/{bid}.png"
    assert again.read(f"BinData/{bid}.png") == b"\x89PNG fake"
    assert again.manifest()[bid2] == f"BinData/{bid2}.jpg"


def test_add_bin_rejects_unknown_type(blank):
    with pytest.raises(PackageError, match="그림 형식"):
        Package.open(blank).add_bin(b"x", "tiff")


def test_old_hwp_gives_friendly_error(tmp_path):
    f = tmp_path / "old.hwp"
    f.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 100)
    with pytest.raises(PackageError, match="구형"):
        Package.open(f)


def test_not_a_zip(tmp_path):
    f = tmp_path / "x.hwpx"
    f.write_text("hello")
    with pytest.raises(PackageError, match="HWPX"):
        Package.open(f)


def test_broken_xml_names_the_part(blank):
    pkg = Package.open(blank)
    pkg.write(SECTION, b"<hs:sec")
    with pytest.raises(PackageError, match="section0.xml"):
        pkg.xml(SECTION)


def test_real_report_roundtrip_keeps_unedited_parts(private_dir, tmp_path):
    src = private_dir / "final.hwpx"
    pkg = Package.open(src)
    pkg.edit(SECTION)
    out = pkg.save(tmp_path / "f.hwpx")
    again, orig = Package.open(out), Package.open(src)
    for name in orig.names():
        if name != SECTION:
            assert again.read(name) == orig.read(name), name


@pytest.mark.hangul
def test_real_report_reserialized_opens_in_hangul(private_dir, tmp_path):
    for name in ("monthly.hwpx", "final.hwpx"):
        src = private_dir / name
        pkg = Package.open(src)
        pkg.edit(SECTION)
        pkg.edit(HEADER)
        out = pkg.save(tmp_path / name)
        assert bridge.check(out) == bridge.check(src), name


def test_save_refuses_source_path(blank):
    pkg = Package.open(blank)
    before = blank.read_bytes()
    with pytest.raises(PackageError, match="덮어쓸"):
        pkg.save(blank.parent / ".." / blank.parent.name / blank.name)
    assert blank.read_bytes() == before
