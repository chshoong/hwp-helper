"""분량(쪽수·제한·배점)과 작성 요령 항목 (설계 3·4장). 판단과 고쳐 쓰기는 Claude가 한다.

쪽수는 한글이 실제 쪽마다 준 글에서 장 제목 줄을 찾아 정한다. 인쇄 쪽 번호(새 쪽 번호로 다시 시작할 수 있음)나
문단 짝 맞추기에 기대지 않는다.
"""
from __future__ import annotations

import re

from .body import own_text
from .header import Header
from .ns import q
from .package import Package
from .samples import bullet_chars, classify, heading_key, heading_levels

# '제3장'·'제 3장'·'110쪽'의 일부는 제한이 아님
_LIMIT = re.compile(r"(?<!\d)(?<!제)(?<!제\s)(\d{1,3})\s*(쪽|페이지|매|장)\s*(이내|이하|내외|까지|以內)")
_SHEET_CONTEXT = re.compile(r"A4|분량|본문|매수|보고서|전체")  # 'N장 이내'가 쪽 수일 때의 앞말 (사진 3장 이내 제외)
_EXCLUDE = re.compile(r"제외|별도|미포함|포함하지")
_WHOLE = re.compile(r"본문|전체|총\s*분량|보고서")
_SCORE = re.compile(r"[〔(\[【]\s*(?:배점\s*:?\s*)?(\d{1,3})\s*점\s*[〕)\]】]")
_HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5}
_SECTIONS_WARNING = "구역이 여러 개인 문서예요. 첫 구역만 봤어요(둘째 구역 이후의 장·작성 요령은 빠져 있어요)."


def find_limits(texts: list[str]) -> list[dict]:
    """분량 제한 글. 같은 (쪽수, 종류)는 한 번. context는 앞뒤 글, exclude는 '제외' 같은 조건이 있는지."""
    out, seen = [], set()
    for text in texts:
        for m in _LIMIT.finditer(text):
            before = text[max(0, m.start() - 15):m.start()]
            if m.group(2) == "장" and not _SHEET_CONTEXT.search(before):
                continue
            key = (int(m.group(1)), m.group(3))
            if key in seen:
                continue
            seen.add(key)
            context = text[max(0, m.start() - 20):m.end() + 20]
            out.append({"pages": key[0], "kind": key[1], "text": m.group(0), "context": context,
                        "exclude": bool(_EXCLUDE.search(context))})
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


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def heading_pages(heads, page_texts: list[str]) -> list[tuple[int | None, bool]]:
    """제목마다 (실제 쪽 번호 1부터, 그 쪽의 첫 줄인지). 제목 줄과 똑같은 줄만 찾는다(차례 줄은 쪽 번호가 붙어 다름).
    문서 순서대로, 앞 제목을 찾은 쪽부터 찾는다. 못 찾으면 (None, False)."""
    lines = [[_norm(x) for x in re.split(r"[\r\n]+", t) if _norm(x)] for t in page_texts]
    out, at = [], 0
    for _, title, _ in heads:
        key = _norm(title)
        found = next((k for k in range(at, len(lines)) if key in lines[k]), None)
        if found is None:
            out.append((None, False))
            continue
        out.append((found + 1, lines[found][0] == key))
        at = found
    return out


def sections_from_pages(heads, starts: list[tuple[int | None, bool]], total: int) -> list[dict]:
    """장 범위. 끝 = 다음 같은·높은 제목이 쪽 첫 줄이면 그 앞 쪽, 쪽 중간이면 그 쪽 (함께 씀)."""
    out = []
    for k, (i, title, lvl) in enumerate(heads):
        start, _ = starts[k]
        if start is None:
            continue
        nxt = next(((s, top) for (_, _, l2), (s, top) in zip(heads[k + 1:], starts[k + 1:])
                    if l2 <= lvl and s is not None), None)
        if nxt is None:
            end = max(start, total)
        else:
            end = max(start, nxt[0] - 1 if nxt[1] else nxt[0])
        out.append({"title": title, "level": lvl, "score": heading_score(title), "para": i,
                    "start": start, "end": end, "count": end - start + 1})
    return out


def doc_texts(pkg: Package) -> list[str]:
    return [t for sec in pkg.section_names() for p in pkg.xml(sec).iter(q("hp:p"))
            if (t := " ".join(own_text(p).split()))]


def _located_limits(pkg: Package, first_head: int | None) -> list[dict]:
    """분량 제한마다 global: 첫 장 제목 앞(표지·안내)이거나 '본문·전체·보고서'라는 말이 있으면 전체 제한."""
    out, seen = [], set()
    for i, top in enumerate(_tops(pkg)):
        texts = [t for p in top.iter(q("hp:p")) if (t := " ".join(own_text(p).split()))]
        for f in find_limits(texts):
            key = (f["pages"], f["kind"])
            if key in seen:
                continue
            seen.add(key)
            f["global"] = (first_head is None or i < first_head) or bool(_WHOLE.search(f["context"]))
            out.append(f)
    return out


def measure(pkg: Package, page_texts: list[str], total: int, *, level: int = 2, limit: int | None = None) -> dict:
    warnings = []
    if len(pkg.section_names()) > 1:
        warnings.append(_SECTIONS_WARNING)
    heads = headings(pkg, level)
    starts = heading_pages(heads, page_texts)
    missing = [title for (_, title, _), (s, _) in zip(heads, starts) if s is None]
    if missing:
        warnings.append("한글 쪽에서 찾지 못한 제목이 있어 뺐어요: " + ", ".join(missing[:5]))
    limits = _located_limits(pkg, heads[0][0] if heads else None)
    if limit is not None:
        chosen = {"pages": limit, "kind": "이내", "text": "--limit", "context": "", "exclude": False, "global": True}
    else:
        whole = [f for f in limits if f["global"]]
        chosen = whole[0] if len(whole) == 1 else None
    return {"pages": total, "limit": chosen, "limits": limits,
            "sections": sections_from_pages(heads, starts, total), "warnings": warnings}


_BOX_HEAD = re.compile(r"작성\s*(요령|방법|안내)|유의\s*사항|기재\s*요령")
_NOTE_WORDS = re.compile(r"작성|기술|기재|포함|제시|첨부|명시")


def _cells(tbl) -> list:
    """이 표의 칸만 (안쪽 표 칸 제외)."""
    return [tc for tr in tbl.findall(q("hp:tr")) for tc in tr.findall(q("hp:tc"))]


def _cell_paras(tc) -> list:
    sub = tc.find(q("hp:subList"))
    return sub.findall(q("hp:p")) if sub is not None else []


def _box_lines(tbl) -> list[str] | None:
    """작성 요령 상자(1칸 표, 또는 첫 칸이 '작성 요령' 같은 머리인 표)의 항목 줄. 상자가 아니면 None."""
    tcs = _cells(tbl)
    first = " ".join(own_text(p) for p in _cell_paras(tcs[0])).strip() if tcs else ""
    if not (len(tcs) == 1 or _BOX_HEAD.search(first)):
        return None
    out = []
    for tc in tcs:
        for p in tc.iter(q("hp:p")):
            if any(a.tag == q("hp:caption") for a in p.iterancestors()):
                continue
            text = " ".join(own_text(p).split())
            if not text or (_BOX_HEAD.search(text) and len(text) <= 12):  # 빈 줄, 머리 줄('작성 요령')
                continue
            out.append(text)
    return out


def _banner_title(tbl) -> str | None:
    """1칸 표의 글이 장 제목('제1장 서론')이면 그 글 — 상자가 아니라 장 제목 띠."""
    tcs = _cells(tbl)
    if len(tcs) != 1:
        return None
    lines = [t for p in _cell_paras(tcs[0]) if (t := " ".join(own_text(p).split()))]
    return lines[0] if len(lines) == 1 and heading_key(lines[0]) else None


def guide_items(pkg: Package) -> dict:
    """양식의 작성 요령·안내·배점을 장(h1~h2)별로. 같은 글은 장마다 한 번."""
    from .review import _GUIDE_RE
    tops = _tops(pkg)
    head_at = {i: title for i, title, _ in headings(pkg, 2)}
    sections = [{"title": "(앞부분)", "score": None, "items": []}]

    def start(title: str) -> None:
        score = heading_score(title)
        sections.append({"title": title, "score": score, "items": []})
        if score is not None:
            sections[-1]["items"].append({"kind": "배점", "text": f"{score}점"})

    def add(kind: str, text: str) -> None:
        if all(it["text"] != text for it in sections[-1]["items"]):
            sections[-1]["items"].append({"kind": kind, "text": text})

    def note(text: str) -> bool:
        return bool(text) and bool(_GUIDE_RE.search(text) or (text.startswith("※") and _NOTE_WORDS.search(text)))

    for i, p in enumerate(tops):
        if i in head_at:
            start(head_at[i])
            continue
        tbl = next((t for run in p.findall(q("hp:run")) for t in run.findall(q("hp:tbl"))), None)
        if tbl is not None:
            banner = _banner_title(tbl)
            if banner:
                start(banner)
                continue
            lines = _box_lines(tbl)
            if lines is not None:
                for line in lines:
                    add("요령", line)
                continue
            for cp in tbl.iter(q("hp:p")):  # 큰 양식 표: 칸 안의 ※ 안내
                text = " ".join(own_text(cp).split())
                if note(text):
                    add("안내", text)
            continue
        text = " ".join(own_text(p).split())
        if note(text):
            add("안내", text)
    warnings = [_SECTIONS_WARNING] if len(pkg.section_names()) > 1 else []
    return {"limits": find_limits(doc_texts(pkg)), "sections": [s for s in sections if s["items"]],
            "warnings": warnings}
