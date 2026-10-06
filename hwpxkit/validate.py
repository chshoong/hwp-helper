"""깨짐 검사. 한글에서 열리지 않거나 서식이 틀어지는 원인을 저장 전에 찾는다.

메시지는 사용자에게 그대로 보여줄 쉬운 한국어로 쓴다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from lxml import etree

from .header import KINDS, LANGS, Header
from .ns import q
from .package import CONTENT_HPF, HEADER, Package, PackageError


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    code: str
    message: str
    part: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_KIND_KO = {"charPr": "글자모양", "paraPr": "문단모양", "style": "스타일", "borderFill": "테두리/배경", "tabPr": "탭"}
_SECTION_REFS = (("charPrIDRef", "charPr"), ("paraPrIDRef", "paraPr"), ("styleIDRef", "style"),
                 ("borderFillIDRef", "borderFill"))
# 한글이 '참조 없음'에 쓰는 값 (unsigned -1)
_NONE_ID = "4294967295"
_HEADER_REFS = (("charPrIDRef", "charPr"), ("paraPrIDRef", "paraPr"), ("borderFillIDRef", "borderFill"),
                ("tabPrIDRef", "tabPr"))


def validate(pkg: Package) -> list[Issue]:
    try:
        issues = _check_package(pkg)
        sections = pkg.section_names()
    except PackageError as e:
        return [Issue("error", "xml", str(e), CONTENT_HPF)]
    header = Header(pkg)
    try:
        header.root
    except PackageError as e:
        return issues + [Issue("error", "xml", str(e), HEADER)]
    issues += _check_header(header)
    bin_ids = set(pkg.manifest())
    for sec in sections:
        try:
            root = pkg.xml(sec)
        except PackageError as e:
            issues.append(Issue("error", "xml", str(e), sec))
            continue
        issues += _check_refs(root, header, sec, _SECTION_REFS)
        issues += _check_bin_refs(root, bin_ids, sec)
        issues += _check_tables(root, sec)
    return issues


def autofix(pkg: Package) -> list[str]:
    """안전하게 자동으로 고칠 수 있는 문제를 고치고, 고친 내용을 돌려준다."""
    fixed = []
    root = pkg.xml(HEADER)
    for cont_tag, item_tag in KINDS.values():
        cont = root.find(f"{q('hh:refList')}/{q(cont_tag)}")
        if cont is None or cont.get("itemCnt") is None:
            continue
        n = len(cont.findall(q(item_tag)))
        if int(cont.get("itemCnt")) != n:
            pkg.edit(HEADER)
            fixed.append(f"{etree.QName(cont).localname} 개수 표시를 {cont.get('itemCnt')} → {n}(으)로 고쳤어요.")
            cont.set("itemCnt", str(n))
    return fixed


def _check_package(pkg: Package) -> list[Issue]:
    out = []
    if pkg.names()[0] != "mimetype":
        out.append(Issue("warning", "mimetype-order", "mimetype이 맨 앞에 있지 않아요 (저장하면 자동으로 고쳐져요)."))
    man = pkg.manifest()
    for href in man.values():
        if not pkg.has(href):
            out.append(Issue("error", "manifest-missing", f"목록(content.hpf)에 있는 '{href}' 파일이 없어요.", CONTENT_HPF))
    listed = set(man.values())
    for name in pkg.names():
        if name.startswith("BinData/") and name not in listed:
            out.append(Issue("warning", "bin-unlisted", f"'{name}' 그림이 목록에 없어 한글에서 안 보일 수 있어요.", CONTENT_HPF))
    return out


def _check_header(h: Header) -> list[Issue]:
    root = h.root
    out = _check_refs(root, h, HEADER, _HEADER_REFS)
    fonts = {lang: set(h.fonts(lang)) for lang in LANGS}
    for cp in h.items("charPr"):
        ref = cp.find(q("hh:fontRef"))
        if ref is None:
            continue
        for lang in LANGS:
            fid = ref.get(lang.lower())
            if fid is not None and fid not in fonts[lang]:
                out.append(Issue("error", "font-missing",
                                 f"글자모양 {cp.get('id')}번이 정의되지 않은 {lang} 글꼴({fid}번)을 가리켜요.", HEADER))
    for cont_tag, item_tag in KINDS.values():
        cont = root.find(f"{q('hh:refList')}/{q(cont_tag)}")
        if cont is None or cont.get("itemCnt") is None:
            continue
        n = len(cont.findall(q(item_tag)))
        if int(cont.get("itemCnt")) != n:
            out.append(Issue("warning", "item-count",
                             f"{etree.QName(cont).localname} 개수 표시({cont.get('itemCnt')})가 실제({n})와 달라요.", HEADER))
    return out


def _check_refs(root, h: Header, part: str, pairs) -> list[Issue]:
    ids = {kind: h.ids(kind) for _, kind in pairs}
    out, seen = [], set()
    for el in root.iter(etree.Element):
        for attr, kind in pairs:
            v = el.get(attr)
            if v is None or v == _NONE_ID or v in ids[kind] or (attr, v) in seen:
                continue
            seen.add((attr, v))
            out.append(Issue("error", "bad-ref", f"{_KIND_KO[kind]} {v}번을 쓰는데 정의되어 있지 않아요.", part))
    return out


def _check_bin_refs(root, bin_ids: set[str], part: str) -> list[Issue]:
    out = []
    for el in root.iter(etree.Element):
        v = el.get("binaryItemIDRef")
        if v is not None and v not in bin_ids:
            out.append(Issue("error", "bad-bin-ref", f"그림 '{v}'을(를) 쓰는데 파일 목록에 없어요.", part))
    return out


def _check_tables(root, part: str) -> list[Issue]:
    out = []
    for n, tbl in enumerate(root.iter(q("hp:tbl")), 1):
        label = f"{n}번째 표"
        rows, cols = int(tbl.get("rowCnt", 0)), int(tbl.get("colCnt", 0))
        trs = tbl.findall(q("hp:tr"))
        if len(trs) != rows:
            out.append(Issue("error", "table-rows", f"{label}: 행 수 표시({rows})와 실제 행({len(trs)})이 달라요.", part))
            continue
        grid = [[0] * cols for _ in range(rows)]
        broken = False
        for tr in trs:
            for tc in tr.findall(q("hp:tc")):
                addr, span = tc.find(q("hp:cellAddr")), tc.find(q("hp:cellSpan"))
                if addr is None:
                    out.append(Issue("error", "table-cell", f"{label}: 위치 정보가 없는 칸이 있어요.", part))
                    broken = True
                    continue
                r, c = int(addr.get("rowAddr")), int(addr.get("colAddr"))
                rs, cs = (1, 1) if span is None else (int(span.get("rowSpan")), int(span.get("colSpan")))
                if r < 0 or c < 0 or r + rs > rows or c + cs > cols:
                    out.append(Issue("error", "table-span", f"{label}: ({r + 1}행, {c + 1}열) 칸이 표 밖으로 나가요.", part))
                    broken = True
                    continue
                for i in range(r, r + rs):
                    for j in range(c, c + cs):
                        grid[i][j] += 1
        if broken:
            continue
        overlaps = [(i, j) for i in range(rows) for j in range(cols) if grid[i][j] > 1]
        holes = [(i, j) for i in range(rows) for j in range(cols) if grid[i][j] == 0]
        if overlaps:
            i, j = overlaps[0]
            out.append(Issue("error", "table-overlap", f"{label}: ({i + 1}행, {j + 1}열)에서 칸이 겹쳐요. 병합 범위를 확인해 주세요.", part))
        if holes:
            i, j = holes[0]
            out.append(Issue("error", "table-hole", f"{label}: ({i + 1}행, {j + 1}열) 칸이 빠져 있어요. 병합 범위를 확인해 주세요.", part))
    return out
