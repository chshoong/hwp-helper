"""단위 변환과 쪽 크기 계산. HWPUNIT = 1/7200 inch."""
from __future__ import annotations

from dataclasses import dataclass

from .ns import q
from .package import Package

HWPUNIT_PER_INCH = 7200
_MM_PER_INCH = 25.4


def mm_to_hu(mm: float) -> int:
    return round(mm * HWPUNIT_PER_INCH / _MM_PER_INCH)


def hu_to_mm(hu: int) -> float:
    return hu * _MM_PER_INCH / HWPUNIT_PER_INCH


def px_to_hu(px: float, dpi: float = 96) -> int:
    return round(px * HWPUNIT_PER_INCH / dpi)


@dataclass(frozen=True)
class PageGeometry:
    width: int
    height: int
    left: int
    right: int
    top: int
    bottom: int
    header: int
    footer: int
    gutter: int
    landscape: bool

    @property
    def text_width(self) -> int:
        return self.width - self.left - self.right - self.gutter

    @property
    def text_height(self) -> int:
        return self.height - self.top - self.bottom - self.header - self.footer


def page_geometry(pkg: Package, section: str | None = None) -> PageGeometry:
    """구역의 쪽 설정. 가로 용지면 긴 변을 width로 돌려준다.

    한글은 세로 A4를 landscape="WIDELY", 가로 A4를 landscape="NARROWLY"로 저장하고,
    가로여도 width/height는 세로 기준 값 그대로 둔다(스파이크 E6에서 확인).
    """
    section = section or pkg.section_names()[0]
    page = next(pkg.xml(section).iter(q("hp:pagePr")), None)
    if page is None:
        raise ValueError(f"{section}에 쪽 설정(pagePr)이 없어요")
    m = page.find(q("hp:margin"))
    w, h = int(page.get("width")), int(page.get("height"))
    landscape = page.get("landscape") == "NARROWLY"
    if landscape:
        w, h = max(w, h), min(w, h)
    return PageGeometry(
        width=w, height=h,
        left=int(m.get("left")), right=int(m.get("right")),
        top=int(m.get("top")), bottom=int(m.get("bottom")),
        header=int(m.get("header")), footer=int(m.get("footer")),
        gutter=int(m.get("gutter", 0)), landscape=landscape,
    )


def fit_image(px_w: float, px_h: float, max_width_hu: int, *, ratio: float = 1.0, dpi: float = 96,
              max_height_hu: int | None = None) -> tuple[int, int]:
    """그림의 자연 크기(px, dpi)를 본문 폭×ratio(최대 1) 안에, 주어지면 높이 한도 안에 비율 유지로 맞춘다.
    확대하지 않는다."""
    if px_w <= 0 or px_h <= 0:
        raise ValueError("그림 크기가 0이에요")
    w, h = px_to_hu(px_w, dpi), px_to_hu(px_h, dpi)
    limit = int(max_width_hu * min(ratio, 1.0))
    if w > limit:
        h = round(h * limit / w)
        w = limit
    if max_height_hu is not None and h > max_height_hu:
        w = round(w * max_height_hu / h)
        h = max_height_hu
    return w, h


def distribute(total: int, weights) -> list[int]:
    """total을 비율대로 나눈다. 반올림 오차는 마지막 칸이 흡수해 합이 정확히 total."""
    weights = list(weights)
    if not weights or any(w <= 0 for w in weights):
        raise ValueError("열 비율은 하나 이상의 양수여야 해요")
    s = sum(weights)
    out = [int(total * w / s) for w in weights]
    out[-1] += total - sum(out)
    return out
