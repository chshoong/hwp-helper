"""견본 카탈로그: 역할(장 제목, 본문, □ 글머리, 표, 그림 …) → 양식 안의 실제 견본.

서식은 여기서 고른 견본에서만 가져온다(설계 3장 '견본 복제').
같은 역할의 문단이 여러 서식으로 섞여 있으면 가장 많이 쓴 것을 고르고 notes에 남긴다.
"""
from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

from lxml import etree

from .body import all_text, contains, is_blank, own_text, top_paragraphs
from .header import Header
from .mdparse import BULLETS
from .ns import q
from .package import Package

ROLE_KO = {
    "h1": "장 제목", "h2": "절 제목", "h3": "소절 제목", "h4": "항 제목", "h5": "목 제목",
    "body": "본문", "bullet1": "□ 글머리", "bullet2": "○ 글머리", "bullet3": "- 글머리", "bullet4": "· 글머리",
    "caption_tbl": "표 제목", "caption_fig": "그림 제목", "note": "주석", "blank": "빈 줄",
}
_FALLBACK = {"h5": "h4", "h4": "h3", "h3": "h2", "h2": "h1", "h1": "body",
             "bullet4": "bullet3", "bullet3": "bullet2", "bullet2": "bullet1", "bullet1": "body",
             "caption_fig": "caption_tbl", "caption_tbl": "body", "note": "body"}
# 제목 번호 형식 (위가 더 큰 단계). 문서에 실제로 쓰인 형식만 골라 순서대로 h1, h2, … 를 준다.
_HEADINGS = [
    ("jang", re.compile(r"^제\s*\d+\s*장")),
    # 영문 로마 숫자는 뒤에 한글 제목이 올 때만 (X. Wang 같은 영문 이니셜 제외)
    ("roman", re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s|[IVX]+\.\s+(?=[가-힣]))")),
    ("n", re.compile(r"^\d+\.\s")),
    ("nn", re.compile(r"^\d+\.\d+\.?\s")),
    ("nnn", re.compile(r"^\d+\.\d+\.\d+\.?\s")),
    ("paren", re.compile(r"^\d+\)\s")),
    ("ga", re.compile(r"^[가-하]\.\s")),
]
# 문맥 없이 한 문단만 볼 때의 단계 (예전 규칙과 같음)
DEFAULT_LEVELS = {"jang": "h1", "roman": "h1", "n": "h2", "nn": "h2", "nnn": "h3", "paren": "h4", "ga": "h5"}
_CAPTIONS = [("caption_tbl", re.compile(r"^(\[\s*표\s*[\d부A-Z][^\]]*\]|표\s*[\d부A-Z][\d\-.]*)(\s|$)")),
             ("caption_fig", re.compile(r"^(\[\s*그림\s*[\d부A-Z][^\]]*\]|그림\s*[\d부A-Z][\d\-.]*)(\s|$)"))]
_HEADING_MAX = 60
_BODY_MIN = 30
_TOC_END = re.compile(r"\d+\s*$")
_TOC_DOTS = re.compile(r"(\.{3,}|·{3,}|…|‥)\s*\d+\s*$")
EQ_NUMBER = re.compile(r"^\(\s*\d+(?:[-.]\d+)?\s*\)$")


# 글로 쓴 글머리·주석의 앞부분: 들여쓰기 공백 + 기호 + 뒤 공백 (양식이 공백으로 단계를 들여쓰는 경우가 많다)
_LEAD = re.compile(r"^(\s*)([□○◦❍\-–·∙•*※])(\s+)")

# 본문 견본이 없을 때 글머리만 빼고 본문으로 쓸 글머리 (개조식 양식은 ○가 보통 본문 글)
BODY_FROM = ("bullet2", "bullet1", "bullet3", "bullet4")


class SampleError(ValueError):
    """양식에서 필요한 견본을 찾지 못함. 메시지는 사용자용 한국어."""


@dataclass(frozen=True)
class ParaStyle:
    para_pr: str
    style: str
    char_pr: str
    auto_bullet: bool = False
    spacer: "ParaStyle | None" = field(default=None, compare=False)
    example: str = field(default="", compare=False)
    lead: str = field(default="", compare=False)  # 글로 쓴 글머리·주석의 앞부분 그대로 (예: '   - ', 공백 들여쓰기 포함)


@dataclass
class Catalog:
    paras: dict
    table_para: etree._Element | None = None
    figure_para: etree._Element | None = None
    fig_label: str = "[그림 {n}]"
    tbl_label: str = "[표 {n}]"
    equation: etree._Element | None = None
    eq_table_para: etree._Element | None = None
    eq_label: str = "({n})"
    notes: list = field(default_factory=list)
    bullet_spacer: "ParaStyle | None" = None  # 글머리(○·-··) 묶음 사이에 쓴 빈 줄 서식 (문서에 그런 빈 줄이 있을 때만)

    def require(self, role: str) -> ParaStyle:
        r = role
        while r is not None:
            if r in self.paras:
                return self.paras[r]
            r = _FALLBACK.get(r)
        raise SampleError(f"양식에서 '{ROLE_KO.get(role, role)}' 견본도, 대신 쓸 본문 견본도 찾지 못했어요.")

    def describe(self) -> list[str]:
        lines = []
        for role, ko in ROLE_KO.items():
            st = self.paras.get(role)
            if st is None and role == "body":
                src = next((r for r in BODY_FROM if r in self.paras), None)
                lines.append(f"{ko}: 견본 없음 → '{self.paras[src].example}' 서식을 글머리 없이 씀" if src
                             else f"{ko}: 견본 없음 → 양식의 '본문'·'바탕글' 스타일로 씀")
                continue
            if st is None:
                try:
                    alt = self.require(role)
                    lines.append(f"{ko}: 견본 없음 → '{alt.example}' 서식으로 대신 씀")
                except SampleError:
                    lines.append(f"{ko}: 견본 없음")
                continue
            extra = (", 자동 글머리" if st.auto_bullet else "") + (", 앞에 빈 줄" if st.spacer else "")
            lines.append(f"{ko}: 견본 '{st.example}' (문단모양 {st.para_pr}, 글자모양 {st.char_pr}{extra})")
        lines.append("표: " + ("견본 있음" if self.table_para is not None else "견본 없음 → 기본 실선 표"))
        lines.append("그림: " + ("견본 있음" if self.figure_para is not None else "견본 없음 → 기본 그림 + 아래 캡션 문단"))
        lines.append("수식: " + ("견본 있음" if self.equation is not None else "견본 없음 → 기본 수식 개체"))
        lines.append(f"번호 형식: {self.tbl_label} / {self.fig_label} / {self.eq_label}")
        return lines + list(self.notes)


def bullet_chars(h: Header) -> dict[str, str]:
    return {b.get("id"): b.get("char") for b in h.items("bullet")}


def style_of(p: etree._Element, h: Header) -> ParaStyle:
    runs = p.findall(q("hp:run"))
    char = next((r.get("charPrIDRef") for r in runs if any((t.text or "").strip() for t in r.findall(q("hp:t")))),
                runs[0].get("charPrIDRef") if runs else "0")
    ppr = p.get("paraPrIDRef", "0")
    head = h.get("paraPr", ppr).find(q("hh:heading"))
    auto = head is not None and head.get("type") == "BULLET"
    return ParaStyle(ppr, p.get("styleIDRef", "0"), char, auto)


def heading_key(text: str) -> str | None:
    if len(text) > _HEADING_MAX:
        return None
    return next((key for key, pat in _HEADINGS if pat.match(text)), None)


def heading_levels(paragraphs) -> dict[str, str]:
    """문서에 쓰인 제목 번호 형식으로 단계를 정한다. 기본은 DEFAULT_LEVELS이고,
    '1.'과 '1.1.'이 함께 쓰인 문서만 '1.'을 '1.1.'보다 한 단계 위로 둔다."""
    used = set()
    for p in paragraphs:
        text = own_text(p).strip()
        if contains(p, "hp:tab") and _TOC_END.search(text) or _TOC_DOTS.search(text):
            continue
        key = heading_key(text)
        if key:
            used.add(key)
    levels = dict(DEFAULT_LEVELS)
    if {"n", "nn"} <= used:  # 1. 과 1.1. 이 함께 쓰이면 1. 이 한 단계 위 (논문: 1. 서론 → 1.1. 배경)
        top = 2 if used & {"jang", "roman"} else 1
        for i, key in enumerate(("n", "nn", "nnn", "paren", "ga")):
            levels[key] = f"h{min(top + i, 5)}"
    return levels


def classify(p: etree._Element, h: Header, chars: dict[str, str], levels: dict[str, str] | None = None):
    if contains(p, "hp:tbl") or contains(p, "hp:pic"):
        return None, None
    text = own_text(p).strip()
    if (contains(p, "hp:tab") and _TOC_END.search(text)) or _TOC_DOTS.search(text):
        return None, None  # 차례 줄 (탭 또는 점선 뒤 쪽 번호)
    st = style_of(p, h)
    if not text:
        return ("blank", st) if not contains(p, "hp:equation") else (None, None)
    if st.auto_bullet:
        head = h.get("paraPr", st.para_pr).find(q("hh:heading"))
        return f"bullet{BULLETS.get(chars.get(head.get('idRef'), ''), 4)}", st
    if text[0] in BULLETS and len(text) > 1 and text[1].isspace():
        return f"bullet{BULLETS[text[0]]}", st
    if text[0] in "*※" and len(text) > 1 and text[1].isspace():
        return "note", st
    for role, pat in _CAPTIONS:
        if pat.match(text):
            return role, st
    key = heading_key(text)
    if key:
        return (levels or DEFAULT_LEVELS)[key], st
    if len(text) >= _BODY_MIN:
        return "body", st
    return None, None


def _label_format(texts: list[str], word: str, default: str) -> str:
    for t in texts:
        m = re.match(rf"^(\[?\s*{word}\s*)(\d+)\s*-\s*(\d+)(\s*\]?)", t)
        if m:
            return f"{m.group(1)}{{c}}-{{n}}{m.group(4)}"
    for t in texts:
        m = re.match(rf"^(\[?\s*{word}\s*)(\d+)(\s*\]?)", t)
        if m:
            return f"{m.group(1)}{{n}}{m.group(3)}"
    return default


def _cell_heights(tcs, h: Header) -> list[int]:
    out = []
    for tc in tcs:
        for run in tc.iter(q("hp:run")):
            t = run.find(q("hp:t"))
            if t is not None and (t.text or "").strip():
                out.append(int(h.get("charPr", run.get("charPrIDRef")).get("height", 1000)))
    return out


def _is_table_sample(p: etree._Element, h: Header) -> bool:
    """데이터 표 견본으로 쓸 만한 표인가. 표지·서명란·작성 요령 상자 같은 서식용 표는 뺀다:
    첫 행에 글자가 없거나, 한 칸이 표 너비 전체를 차지하거나, 표 안에 표가 있거나,
    머리 행 글자가 본문 칸보다 훨씬 큰 표."""
    tbl = next(p.iter(q("hp:tbl")), None)
    if tbl is None or contains(tbl, "hp:equation"):
        return False
    rows, cols = int(tbl.get("rowCnt", 0)), int(tbl.get("colCnt", 0))
    if rows < 2 or cols < 2 or sum(1 for _ in tbl.iter(q("hp:tbl"))) > 1:
        return False
    tcs = list(tbl.iter(q("hp:tc")))
    if any(int((tc.find(q("hp:cellSpan")).get("colSpan", "1") if tc.find(q("hp:cellSpan")) is not None else "1"))
           >= cols for tc in tcs):
        return False
    trs = tbl.findall(q("hp:tr"))
    head = trs[0].findall(q("hp:tc"))
    if not head or not any(all_text(tc).strip() for tc in head):
        return False
    head_h = _cell_heights(head, h)
    body_h = sorted(_cell_heights([tc for tr in trs[1:] for tc in tr.findall(q("hp:tc"))], h))
    if head_h and body_h and max(head_h) > 1.4 * body_h[len(body_h) // 2]:
        return False
    return True


def _eq_number_cell(tbl: etree._Element) -> etree._Element | None:
    return next((tc for tc in tbl.iter(q("hp:tc")) if EQ_NUMBER.match(all_text(tc).strip())), None)


def _is_eq_table(p: etree._Element) -> bool:
    tbl = next(p.iter(q("hp:tbl")), None)
    return (tbl is not None and tbl.get("rowCnt") == "1" and contains(tbl, "hp:equation")
            and _eq_number_cell(tbl) is not None)


def _eq_label_format(text: str) -> str:
    m = re.match(r"^\(\s*\d+\s*([-.])\s*\d+\s*\)$", text)
    return f"({{c}}{m.group(1)}{{n}})" if m else "({n})"


def learn(paragraphs, h: Header, chars: dict[str, str]):
    """문단 목록에서 역할별 견본을 배운다: (역할→ParaStyle, 서식 혼용 메모, 캡션 [(역할, 글)])."""
    paragraphs = list(paragraphs)
    levels = heading_levels(paragraphs)
    counts: dict[str, Counter] = defaultdict(Counter)
    before: dict[str, Counter] = defaultdict(Counter)
    examples: dict = {}
    leads: dict = {}
    last: dict = {}
    captions: list[tuple[str, str]] = []
    prev = None
    for idx, p in enumerate(paragraphs):
        role, st = classify(p, h, chars, levels)
        if role:
            counts[role][st] += 1
            last[(role, st)] = idx
            examples.setdefault((role, st), own_text(p).strip()[:30])
            m = _LEAD.match(own_text(p))
            if m and (role == "note" or role.startswith("bullet")) and not st.auto_bullet:
                leads.setdefault((role, st), m.group(0))
            if prev is not None:  # 맨 앞 문단은 앞에 빈 줄이 있을 수 없으니 간격 셈에서 뺀다
                before[role][style_of(prev, h) if is_blank(prev) else None] += 1
            if role.startswith("caption"):
                captions.append((role, own_text(p).strip()))
        for cap in p.iter(q("hp:caption")):
            kind = "caption_tbl" if cap.getparent().tag == q("hp:tbl") else "caption_fig"
            captions.append((kind, all_text(cap).strip()))
        prev = p
    paras, notes = {}, []
    for role, c in counts.items():
        # 개수가 같으면 문서 뒤쪽에서 쓴 서식 (앞쪽은 차례·표지일 가능성이 큼)
        st, n = max(c.items(), key=lambda kv: (kv[1], last[(role, kv[0])]))
        total = sum(c.values())
        spacer = (before[role].most_common(1)[0][0]
                  if role not in ("body", "blank") and before[role] else None)
        paras[role] = replace(st, spacer=spacer, example=examples[(role, st)], lead=leads.get((role, st), ""))
        if len(c) > 1 and n < 0.8 * total:
            notes.append(f"{ROLE_KO[role]}: 서식이 {len(c)}가지 섞여 있어 가장 많이 쓴 것({n}/{total})을 골랐어요.")
    return paras, notes, captions


def _bullet_spacer(tops, h: Header, chars) -> "ParaStyle | None":
    """○·-·· 글머리 바로 앞뒤에 있는 빈 줄 중 가장 많이 쓴 서식. 그런 빈 줄이 없으면 None."""
    roles = [classify(p, h, chars)[0] for p in tops]
    deep = lambda r: bool(r) and r.startswith("bullet") and r[-1] in "234"  # noqa: E731
    found: Counter = Counter()
    for i, p in enumerate(tops):
        if roles[i] == "blank" and ((i > 0 and deep(roles[i - 1])) or (i + 1 < len(tops) and deep(roles[i + 1]))):
            found[style_of(p, h)] += 1
    return found.most_common(1)[0][0] if found else None


def infer(pkg: Package, section: str | None = None) -> Catalog:
    h = Header(pkg)
    chars = bullet_chars(h)
    tops = top_paragraphs(pkg, section)
    paras, notes, captions = learn(tops, h, chars)
    if "h1" not in paras:
        notes.append(f"{ROLE_KO['h1']} 견본을 찾지 못했어요.")  # 본문은 없어도 글머리·스타일로 대신 쓴다(describe 참고)
    samples_ = [p for p in tops if _is_table_sample(p, h)]
    captioned = [p for p in samples_ if next(p.iter(q("hp:tbl"))).find(q("hp:caption")) is not None]
    table_para = copy.deepcopy((captioned or samples_)[0]) if samples_ else None
    figure_para = next((copy.deepcopy(p) for p in tops if contains(p, "hp:pic") and contains(p, "hp:caption")), None)
    cat = Catalog(paras, table_para, figure_para, notes=notes)
    cat.bullet_spacer = _bullet_spacer(tops, h, chars)
    cat.tbl_label = _label_format([t for r, t in captions if r == "caption_tbl"], "표", cat.tbl_label)
    cat.fig_label = _label_format([t for r, t in captions if r == "caption_fig"], "그림", cat.fig_label)
    eq_tables = [p for p in tops if _is_eq_table(p)]
    if eq_tables:
        cat.eq_table_para = copy.deepcopy(eq_tables[0])
        tbl = next(eq_tables[0].iter(q("hp:tbl")))
        cat.eq_label = _eq_label_format(all_text(_eq_number_cell(tbl)).strip())
    first_eq = next((e for p in tops for e in p.iter(q("hp:equation"))), None)
    cat.equation = copy.deepcopy(first_eq) if first_eq is not None else None
    return cat
