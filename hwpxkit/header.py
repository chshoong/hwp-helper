"""header.xml 서식 레지스트리.

서식 ID는 모두 여기서 조회·파생한다. 서식을 '처음부터' 만들지 않는다:
derive()는 기존 항목을 복제해 일부만 바꾸고, 똑같은 항목이 이미 있으면 그 ID를 돌려준다.
"""
from __future__ import annotations

import copy
from typing import Callable

from lxml import etree

from .ns import q
from .package import HEADER, Package

KINDS = {
    "charPr": ("hh:charProperties", "hh:charPr"),
    "paraPr": ("hh:paraProperties", "hh:paraPr"),
    "borderFill": ("hh:borderFills", "hh:borderFill"),
    "style": ("hh:styles", "hh:style"),
    "tabPr": ("hh:tabProperties", "hh:tabPr"),
    "numbering": ("hh:numberings", "hh:numbering"),
    "bullet": ("hh:bullets", "hh:bullet"),
}
LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
# OWPML 스키마의 charPr 자식 순서
_CHARPR_ORDER = ["fontRef", "ratio", "spacing", "relSz", "offset", "italic", "bold", "underline",
                 "strikeout", "outline", "shadow", "emboss", "engrave", "supscript", "subscript"]


class Header:
    def __init__(self, pkg: Package):
        self.pkg = pkg

    @property
    def root(self) -> etree._Element:
        return self.pkg.xml(HEADER)

    def _container(self, kind: str, *, edit: bool = False):
        root = self.pkg.edit(HEADER) if edit else self.pkg.xml(HEADER)
        return root.find(f"{q('hh:refList')}/{q(KINDS[kind][0])}")

    def items(self, kind: str) -> list[etree._Element]:
        cont = self._container(kind)
        return [] if cont is None else cont.findall(q(KINDS[kind][1]))

    def ids(self, kind: str) -> set[str]:
        return {e.get("id") for e in self.items(kind)}

    def get(self, kind: str, id) -> etree._Element:
        for e in self.items(kind):
            if e.get("id") == str(id):
                return e
        raise KeyError(f"{kind} {id}번이 header.xml에 없어요")

    def fonts(self, lang: str = "HANGUL") -> dict[str, str]:
        for ff in self.root.iter(q("hh:fontface")):
            if ff.get("lang") == lang:
                return {f.get("id"): f.get("face") for f in ff.findall(q("hh:font"))}
        return {}

    def style_id(self, name: str) -> str | None:
        for e in self.items("style"):
            if e.get("name") == name:
                return e.get("id")
        return None

    def charpr_faces(self, charpr_id) -> dict[str, str | None]:
        ref = self.get("charPr", charpr_id).find(q("hh:fontRef"))
        return {lang: self.fonts(lang).get(ref.get(lang.lower())) for lang in LANGS}

    def derive(self, kind: str, base_id, mutate: Callable[[etree._Element], None]) -> str:
        candidate = copy.deepcopy(self.get(kind, base_id))
        mutate(candidate)
        key = _key(candidate)
        for e in self.items(kind):
            if _key(e) == key:
                return e.get("id")
        cont = self._container(kind, edit=True)
        new_id = str(max((int(i) for i in self.ids(kind)), default=-1) + 1)
        candidate.set("id", new_id)
        cont.append(candidate)
        cont.set("itemCnt", str(len(cont.findall(q(KINDS[kind][1])))))
        return new_id

    def font_ids(self, face: str) -> dict[str, str]:
        """face를 7개 언어 fontface에 등록하고 언어별 id를 돌려준다 (이미 있으면 그 id)."""
        root = self.pkg.edit(HEADER)
        ids = {}
        for ff in root.iter(q("hh:fontface")):
            fonts = ff.findall(q("hh:font"))
            found = next((f for f in fonts if f.get("face") == face), None)
            if found is None:
                found = copy.deepcopy(fonts[0])
                found.set("id", str(max(int(f.get("id")) for f in fonts) + 1))
                found.set("face", face)
                ff.append(found)
                ff.set("fontCnt", str(len(fonts) + 1))
            ids[ff.get("lang")] = found.get("id")
        return ids

    def derive_font(self, charpr_id, face: str) -> str:
        """글자 모양을 복제해 모든 언어 글꼴을 face로 바꾼다."""
        ids = self.font_ids(face)

        def mutate(e):
            ref = e.find(q("hh:fontRef"))
            for lang, fid in ids.items():
                ref.set(lang.lower(), fid)

        return self.derive("charPr", charpr_id, mutate)

    def derive_charpr(self, base_id, *, bold=None, italic=None, color=None, height=None) -> str:
        def mutate(e):
            if color is not None:
                e.set("textColor", color)
            if height is not None:
                e.set("height", str(height))
            for flag, name in ((italic, "italic"), (bold, "bold")):
                if flag is None:
                    continue
                cur = e.find(q(f"hh:{name}"))
                if flag and cur is None:
                    _insert_ordered(e, etree.Element(q(f"hh:{name}")))
                elif not flag and cur is not None:
                    e.remove(cur)

        return self.derive("charPr", base_id, mutate)


def _key(e: etree._Element) -> bytes:
    c = copy.deepcopy(e)
    c.attrib.pop("id", None)
    return etree.tostring(c, method="c14n")


def _insert_ordered(parent: etree._Element, child: etree._Element) -> None:
    rank = _CHARPR_ORDER.index(etree.QName(child).localname)
    for i, sib in enumerate(parent):
        name = etree.QName(sib).localname
        if name in _CHARPR_ORDER and _CHARPR_ORDER.index(name) > rank:
            parent.insert(i, child)
            return
    parent.append(child)
