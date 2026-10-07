"""HWPX 패키지(zip) 읽기·쓰기.

규칙
- mimetype은 zip의 첫 항목, 무압축(STORED).
- 수정하지 않은 항목은 원본 바이트와 압축 방식을 그대로 유지한다.
- XML을 고칠 때는 edit()으로 꺼낸 트리만 고친다. edit()한 항목만 저장할 때 다시 직렬화된다.
  xml()은 읽기 전용이다(고쳐도 저장되지 않음).
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from .ns import q

MIMETYPE = b"application/hwp+zip"
HEADER = "Contents/header.xml"
CONTENT_HPF = "Contents/content.hpf"
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpg", "jpeg": "image/jpg", "bmp": "image/bmp", "gif": "image/gif"}
_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
_PARSER = etree.XMLParser(huge_tree=True, remove_blank_text=False)
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class PackageError(Exception):
    """열 수 없거나 규칙에 맞지 않는 HWPX. 메시지는 사용자용 한국어."""


class Package:
    def __init__(self, entries: dict[str, bytes], compress: dict[str, int], order: list[str], source: Path | None = None):
        self._raw = entries
        self._compress = compress
        self._order = order
        self._trees: dict[str, etree._Element] = {}
        self._dirty: set[str] = set()
        self.source = source

    @classmethod
    def open(cls, path) -> "Package":
        path = Path(path)
        with open(path, "rb") as f:
            magic = f.read(8)
        if magic == _OLE_MAGIC:
            raise PackageError("구형 한글(.hwp) 파일이에요. 먼저 .hwpx로 바꿔야 해요 (한글이 설치돼 있으면 자동으로 바꿉니다).")
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise PackageError(f"HWPX 파일이 아니에요: {path.name}") from e
        with zf:
            infos = zf.infolist()
            entries = {i.filename: zf.read(i) for i in infos}
            compress = {i.filename: i.compress_type for i in infos}
            order = [i.filename for i in infos]
        if entries.get("mimetype", b"").strip() != MIMETYPE:
            raise PackageError(f"HWPX 파일이 아니에요 (mimetype 없음 또는 다름): {path.name}")
        return cls(entries, compress, order, source=path)

    def names(self) -> list[str]:
        return list(self._order)

    def has(self, name: str) -> bool:
        return name in self._raw

    def read(self, name: str) -> bytes:
        if name in self._dirty:
            return etree.tostring(self._trees[name], xml_declaration=True, encoding="UTF-8", standalone=True)
        try:
            return self._raw[name]
        except KeyError:
            raise PackageError(f"패키지에 없는 항목이에요: {name}") from None

    def xml(self, name: str) -> etree._Element:
        """읽기용 XML 트리 (캐시됨). 고치려면 edit()을 쓴다."""
        if name not in self._trees:
            try:
                self._trees[name] = etree.fromstring(self.read(name), _PARSER)
            except etree.XMLSyntaxError as e:
                raise PackageError(f"{name} 의 XML이 깨져 있어요: {e}") from e
        return self._trees[name]

    def edit(self, name: str) -> etree._Element:
        """수정용 XML 트리. 이 항목은 저장할 때 다시 직렬화된다."""
        root = self.xml(name)
        self._dirty.add(name)
        return root

    def write(self, name: str, data: bytes, compress: int = zipfile.ZIP_DEFLATED) -> None:
        if name not in self._raw:
            self._order.append(name)
            self._compress[name] = compress
        self._raw[name] = data
        self._trees.pop(name, None)
        self._dirty.discard(name)

    def remove(self, name: str) -> None:
        """패키지에서 파일 하나를 뺀다 (매니페스트 정리는 부르는 쪽 몫)."""
        for store in (self._raw, self._compress, self._trees):
            store.pop(name, None)
        self._dirty.discard(name)
        if name in self._order:
            self._order.remove(name)

    def save(self, path) -> Path:
        path = Path(path)
        if self.source is not None and path.resolve() == self.source.resolve():
            raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
        order = ["mimetype"] + [n for n in self._order if n != "mimetype"]
        fd, tmp = tempfile.mkstemp(suffix=".hwpx.tmp", dir=path.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as zf:
                for name in order:
                    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
                    info.compress_type = (zipfile.ZIP_STORED if name == "mimetype"
                                          else self._compress.get(name, zipfile.ZIP_DEFLATED))
                    zf.writestr(info, self.read(name))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def manifest(self) -> dict[str, str]:
        return {it.get("id"): it.get("href") for it in self.xml(CONTENT_HPF).iter(q("opf:item"))}

    def section_names(self) -> list[str]:
        man = self.manifest()
        hrefs = [man.get(ref.get("idref"), "") for ref in self.xml(CONTENT_HPF).iter(q("opf:itemref"))]
        return [h for h in hrefs if h.startswith("Contents/section")]

    def add_bin(self, data: bytes, ext: str) -> str:
        """그림 데이터를 BinData에 넣고 manifest에 등록한 뒤 ID(예: 'image3')를 돌려준다."""
        ext = ext.lower().lstrip(".")
        if ext not in MEDIA_TYPES:
            raise PackageError(f"지원하지 않는 그림 형식이에요: {ext} (가능: png, jpg, bmp, gif)")
        man = self.manifest()
        n = 1
        while f"image{n}" in man:
            n += 1
        bid = f"image{n}"
        href = f"BinData/{bid}.{ext}"
        self.write(href, data, compress=zipfile.ZIP_DEFLATED if ext == "bmp" else zipfile.ZIP_STORED)
        manifest_el = self.edit(CONTENT_HPF).find(q("opf:manifest"))
        etree.SubElement(manifest_el, q("opf:item"),
                         {"id": bid, "href": href, "media-type": MEDIA_TYPES[ext], "isEmbeded": "1"})
        return bid
