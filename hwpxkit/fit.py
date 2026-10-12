"""분량(쪽수·제한·배점)과 작성 요령 항목 (설계 3·4장). 판단과 고쳐 쓰기는 Claude가 한다."""
from __future__ import annotations

import re

from .body import own_text
from .header import Header
from .ns import q
from .package import Package
from .samples import bullet_chars, classify, heading_levels

_LIMIT = re.compile(r"(?<![제\d])(\d{1,3})\s*(쪽|페이지|매|장)\s*(이내|이하|내외|까지|以內)")
_SCORE = re.compile(r"[〔(\[]\s*(\d{1,3})\s*점\s*[〕)\]]\s*$")
_HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5}


def find_limits(texts: list[str]) -> list[dict]:
    out, seen = [], set()
    for text in texts:
        for m in _LIMIT.finditer(text):
            key = m.group(0)
            if key not in seen:
                seen.add(key)
                out.append({"pages": int(m.group(1)), "kind": m.group(3), "text": key})
    return out


def heading_score(text: str) -> int | None:
    m = _SCORE.search(text.strip())
    return int(m.group(1)) if m else None


def _tops(pkg: Package) -> list:
    return [p for p in pkg.xml(pkg.section_names()[0]) if p.tag == q("hp:p")]


def headings(pkg: Package, level: int = 2) -> list[tuple[int, str, int]]:
    h = Header(pkg)
    chars = bullet_chars(h)
    tops = _tops(pkg)
    levels = heading_levels(tops)
    out = []
    for i, p in enumerate(tops):
        lvl = _HEAD.get(classify(p, h, chars, levels)[0])
        if lvl is not None and lvl <= level:
            out.append((i, own_text(p).strip(), lvl))
    return out


def sections_from_pages(heads, pages: list[int], total: int) -> list[dict]:
    out = []
    for k, (i, title, lvl) in enumerate(heads):
        if i >= len(pages):
            break
        start = pages[i]
        nxt = next((j for j, _, l2 in heads[k + 1:] if l2 <= lvl and j < len(pages)), None)
        end = max(start, pages[nxt] - 1) if nxt is not None else max(start, total)
        out.append({"title": title, "level": lvl, "score": heading_score(title), "para": i,
                    "start": start, "end": end, "count": end - start + 1})
    return out


def doc_texts(pkg: Package) -> list[str]:
    return [t for sec in pkg.section_names() for p in pkg.xml(sec).iter(q("hp:p"))
            if (t := " ".join(own_text(p).split()))]


def measure(pkg: Package, pages: list[int], total: int, *, level: int = 2, limit: int | None = None) -> dict:
    warnings = []
    n_tops = len(_tops(pkg))
    if len(pages) != n_tops:
        warnings.append(f"한글이 센 문단 수({len(pages)})와 문서 문단 수({n_tops})가 달라 앞쪽부터 맞췄어요. "
                        "장 쪽수가 조금 다를 수 있어요.")
        pages = pages[:n_tops]
    limits = find_limits(doc_texts(pkg))
    if limit is not None:
        chosen = {"pages": limit, "kind": "이내", "text": "--limit"}
    else:
        chosen = limits[0] if len(limits) == 1 else None
    return {"pages": total, "limit": chosen, "limits": limits,
            "sections": sections_from_pages(headings(pkg, level), pages, total), "warnings": warnings}
