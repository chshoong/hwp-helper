"""본문(section) 공통 도구: 최상위 문단, 글자 추출, 빈 문단 판정, 줄배치 캐시 제거, 개체 ID."""
from __future__ import annotations

from lxml import etree

from .ns import q
from .package import Package

_OBJECTS = ("hp:tbl", "hp:pic", "hp:equation")


def section_of(pkg: Package, section: str | None = None) -> str:
    return section or pkg.section_names()[0]


def top_paragraphs(pkg: Package, section: str | None = None) -> list[etree._Element]:
    return [p for p in pkg.xml(section_of(pkg, section)) if p.tag == q("hp:p")]


def t_text(t: etree._Element) -> str:
    """hp:t의 글자. 안쪽 hp:tab 등의 뒤 글자(tail)까지 포함한다."""
    return "".join(t.itertext())


def own_text(p: etree._Element) -> str:
    """문단 자신의 글자 (표·그림 안의 글자는 빼고)."""
    return "".join(t_text(t) for run in p.findall(q("hp:run")) for t in run.findall(q("hp:t")))


def all_text(el: etree._Element) -> str:
    return "".join(t_text(t) for t in el.iter(q("hp:t")))


def contains(el: etree._Element, tag: str) -> bool:
    return next(el.iter(q(tag)), None) is not None


def is_blank(p: etree._Element) -> bool:
    return not own_text(p).strip() and not any(contains(p, t) for t in _OBJECTS)


def strip_lineseg(el: etree._Element) -> None:
    """줄배치 캐시를 지운다. 한글이 열 때 다시 계산한다 (스파이크 E1)."""
    for arr in list(el.iter(q("hp:linesegarray"))):
        arr.getparent().remove(arr)


class IdAllocator:
    """표·그림·수식 개체 ID를 문서 안에서 겹치지 않게 새로 준다."""

    _START = 1_000_000_000

    def __init__(self, pkg: Package):
        self._used: set[int] = set()
        for sec in pkg.section_names():
            for tag in _OBJECTS:
                for obj in pkg.xml(sec).iter(q(tag)):
                    for attr in ("id", "instid"):
                        v = obj.get(attr)
                        if v and v.isdigit():
                            self._used.add(int(v))
        self._next = self._START

    def take(self) -> str:
        while self._next in self._used:
            self._next += 1
        self._used.add(self._next)
        return str(self._next)

    def refresh(self, el: etree._Element) -> None:
        for tag in _OBJECTS:
            for obj in el.iter(q(tag)):
                obj.set("id", self.take())
                if obj.get("instid") is not None:
                    obj.set("instid", self.take())
