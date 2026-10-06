"""완성 문서 검토: 사람이 놓치기 쉬운 것을 찾아 '확인 필요' 목록으로 돌려준다(설계 4.3).

오류: 분명히 틀린 것(요일 불일치, 없는 날짜, 없는 표를 가리키는 참조, 번호 중복).
확인: 틀렸을 가능성이 큰 것(보고일 연도, 달 머리, 번호 건너뜀, 안내 문구, 빈 칸, 글꼴 혼용, 서식 혼용).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass

from collections import Counter

from .body import all_text, own_text, top_paragraphs
from .form import cells
from .ns import q
from .header import Header
from .package import Package
from .samples import bullet_chars, classify, heading_levels, infer

_WEEKDAYS = "월화수목금토일"
_WD = r"(?:\s*\(\s*(?P<wd>[월화수목금토일])\s*\))"
DATE_RES = [
    re.compile(r"(?<![\d.])(?P<y>\d{4})\s*[.\-/]\s*(?P<m>\d{1,2})\s*[.\-/]\s*(?P<d>\d{1,2})\.?" + _WD + "?"),
    re.compile(r"(?<![\d.(])(?P<y>\d{2})\s*\.\s*(?P<m>\d{1,2})\s*\.\s*(?P<d>\d{1,2})\.?" + _WD),
    re.compile(r"(?P<y>\d{4})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일" + _WD + "?"),
]
PERIOD_RE = re.compile(r"[‘'’]?\s*(\d{4}|\d{2})\s*년\s*(\d{1,2})\s*월")
MONTH_RE = re.compile(r"\(\s*(\d{2})\s*\.\s*(\d{1,2})\s*\.?\s*\)")
_REPORT_DATE_WORDS = re.compile(r"보\s*고\s*일|작\s*성\s*일|제\s*출\s*일")
_CURRENT = re.compile(r"금월|당월|이번\s*달")
_NEXT = re.compile(r"향후|차월|다음\s*달|익월")


@dataclass(frozen=True)
class Finding:
    level: str  # "오류" | "확인"
    code: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _tops(pkg: Package) -> list:
    """모든 구역의 최상위 문단."""
    return [p for sec in pkg.section_names() for p in top_paragraphs(pkg, sec)]


def _texts(pkg: Package) -> list[tuple[str, str]]:
    """문서의 모든 문단 (글, 문맥) — 문맥은 표 칸이면 같은 행의 왼쪽 머리를 앞에 붙인 글. 메모 내용 제외."""
    all_cells = cells(pkg)  # 목록을 붙잡아 둬야 lxml 요소 id가 바뀌지 않는다
    row_header = {id(c.tc): c.row_header for c in all_cells}
    out = []
    for sec in pkg.section_names():
        for p in pkg.xml(sec).iter(q("hp:p")):
            if any(a.tag == q("hp:fieldBegin") for a in p.iterancestors()):
                continue
            text = own_text(p).strip()
            if not text:
                continue
            tc = next((a for a in p.iterancestors() if a.tag == q("hp:tc")), None)
            out.append((text, f"{row_header.get(id(tc), '')} {text}" if tc is not None else text))
    return out


def _year(y: str) -> int:
    return int(y) + 2000 if len(y) == 2 else int(y)


def _period(texts: list[tuple[str, str]]) -> tuple[int, int] | None:
    for text, _ in texts[:40]:
        if _REPORT_DATE_WORDS.search(text):  # 보고일 줄의 달은 보고 기간이 아님
            continue
        m = PERIOD_RE.search(text)
        if m and "보고" in text:
            return _year(m.group(1)), int(m.group(2))
    return None


def _add_month(y: int, m: int, k: int) -> tuple[int, int]:
    m0 = m - 1 + k
    return y + m0 // 12, m0 % 12 + 1


def _dates(text: str):
    for regex in DATE_RES:
        for m in regex.finditer(text):
            yield m, _year(m.group("y")), int(m.group("m")), int(m.group("d")), m.group("wd")


def _check_dates(texts: list[tuple[str, str]], period) -> list[Finding]:
    out = []
    for text, context in texts:
        for m, y, mo, d, wd in _dates(text):
            try:
                day = dt.date(y, mo, d)
            except ValueError:
                out.append(Finding("오류", "bad-date", f"'{m.group(0).strip()}': 없는 날짜예요."))
                continue
            real = _WEEKDAYS[day.weekday()]
            if wd and real != wd:
                out.append(Finding("오류", "weekday", f"'{m.group(0)}': {y}년 {mo}월 {d}일은 {real}요일이에요."))
            if period and _REPORT_DATE_WORDS.search(context):
                py, pm = period
                start = dt.date(py, pm, 1)
                ny, nm = _add_month(py, pm, 1)
                end = dt.date(ny, nm, 1) - dt.timedelta(days=1)
                if not start <= day <= end + dt.timedelta(days=62):
                    out.append(Finding("확인", "report-date",
                                       f"'{m.group(0)}': 보고 대상 기간({py}년 {pm}월)과 맞지 않아요. 연도·달을 확인해 주세요."))
    return out


def _check_month_headers(pkg: Package, period) -> list[Finding]:
    if not period:
        return []
    out = []
    for c in cells(pkg):
        if c.row != 0:
            continue
        text = " ".join(c.text.split())
        m = MONTH_RE.search(text)
        if not m:
            continue
        if _CURRENT.search(text):
            want, kind = period, "이번"
        elif _NEXT.search(text):
            want, kind = _add_month(*period, 1), "다음"
        else:
            continue
        got = (_year(m.group(1)), int(m.group(2)))
        if got != want:
            label = f"({want[0] % 100:02d}. {want[1]:02d}.)"
            out.append(Finding("확인", "month-header",
                               f"[표{c.table}] '{text}': {kind} 달은 {label}이어야 해요 (보고 대상 {period[0]}년 {period[1]}월)."))
    return out


LABEL_RE = re.compile(r"^\[?\s*(표|그림)\s*(\d+|부록)(?:\s*[-.]\s*(\d+))?\s*\]?")
REF_RE = re.compile(r"\[(표|그림)\s*(\d+|부록)(?:\s*[-.]\s*(\d+))?\]")
_CAPTION_START = re.compile(r"^\[?\s*(표|그림)")


def _key(kind: str, a: str, b: str | None) -> str:
    return f"{kind}{a}-{b}" if b else f"{kind}{a}"


def _caption_targets(pkg: Package):
    """([(캡션 글을 담은 hp:t, 장 번호)], 번호를 읽을 수 없는 캡션이 있는 종류) — 문서 순서.

    최종보고서처럼 캡션 번호가 자동 번호 컨트롤([그림 -1])이면 글로 번호를 읽을 수 없으므로,
    그 종류(표/그림)는 번호·참조 검사를 건너뛴다(오탐 방지).
    """
    h = Header(pkg)
    chars = bullet_chars(h)
    chapter = 0
    out = []
    opaque: set = set()
    tops = _tops(pkg)
    levels = heading_levels(tops)
    for p in tops:
        role, _ = classify(p, h, chars, levels)
        if role == "h1":
            chapter += 1
        holders = []
        if role in ("caption_tbl", "caption_fig"):
            holders.append(p)
        holders += list(p.iter(q("hp:caption")))
        for holder in holders:
            t = next(holder.iter(q("hp:t")), None)
            text = all_text(holder).strip()
            start = _CAPTION_START.match(text)
            if t is not None and t.text and LABEL_RE.match(t.text.strip()) and next(holder.iter(q("hp:autoNum")), None) is None:
                out.append((t, max(chapter, 1)))
            elif start:
                opaque.add(start.group(1))
    return out, opaque


def _check_numbering(pkg: Package) -> list[Finding]:
    out, seen, keys = [], set(), set()
    last: dict = {}
    targets, opaque = _caption_targets(pkg)
    for t, _ in targets:
        if LABEL_RE.match(t.text.strip()).group(1) in opaque:
            continue
        m = LABEL_RE.match(t.text.strip())
        kind, a, b = m.group(1), m.group(2), m.group(3)
        key = _key(kind, a, b)
        label = m.group(0).strip()
        if key in seen:
            out.append(Finding("오류", "caption-dup", f"{label} 번호가 두 번 쓰였어요. renumber로 다시 매길 수 있어요."))
        seen.add(key)
        keys.add(key)
        group = (kind, a) if b else (kind,)
        n = int(b) if b else (int(a) if a.isdigit() else 0)
        prev = last.get(group, 0)
        if n not in (prev + 1, prev) and n != 1:
            out.append(Finding("확인", "caption-gap", f"{label}: 앞 번호가 {prev}여서 번호가 건너뛰었어요."))
        last[group] = n
    caption_ts = {id(t) for t, _ in targets}
    for p in _tops(pkg):
        first = next(p.iter(q("hp:t")), None)
        if first is not None and id(first) in caption_ts:
            continue
        for m in REF_RE.finditer(own_text(p)):
            if m.group(1) in opaque:
                continue
            if _key(m.group(1), m.group(2), m.group(3)) not in keys:
                out.append(Finding("오류", "bad-ref", f"본문이 {m.group(0)}을(를) 가리키는데 그런 {m.group(1)}이(가) 없어요."))
    return out


def _check_cells(pkg: Package) -> list[Finding]:
    out = []
    all_cells = cells(pkg)
    for table in sorted({c.table for c in all_cells}):
        body = [c for c in all_cells if c.table == table and c.row > 0 and c.col > 0]
        for col in sorted({c.col for c in body}):
            column = [c for c in body if c.col == col]
            texts = Counter(" ".join(c.text.split()) for c in column if c.text.strip())
            for text, n in texts.items():
                if (n >= 2 and len(column) >= 2 and n == len([c for c in column if c.text.strip()])
                        and len(text) <= 20 and re.search(r"[가-힣]", text)):
                    out.append(Finding("확인", "placeholder", f"[표{table}] '{text}' 안내 문구가 {n}칸에 그대로 남아 있어요."))
            if any(c.text.strip() for c in column):
                for c in column:
                    if not c.text.strip():
                        out.append(Finding("확인", "empty-cell", f"{c.label()}: 비어 있어요."))
    return out


def _check_fonts(pkg: Package) -> list[Finding]:
    h = Header(pkg)
    usage: Counter = Counter()
    sample: dict = {}
    for p in _tops(pkg):
        if next(p.iter(q("hp:tbl")), None) is not None:
            continue
        for run in p.findall(q("hp:run")):
            text = "".join(t.text or "" for t in run.findall(q("hp:t"))).strip()
            if not text:
                continue
            try:
                face = h.charpr_faces(run.get("charPrIDRef"))["HANGUL"] or "(알 수 없음)"
            except KeyError:
                continue
            usage[face] += len(text)
            sample.setdefault(face, text[:20])
    if len(usage) < 2:
        return []
    total = sum(usage.values())
    main_face = usage.most_common(1)[0][0]
    return [Finding("확인", "font-mix", f"본문에 {face} 글꼴이 섞여 있어요 (예: '{sample[face]}'). 주 글꼴은 {main_face}예요.")
            for face, n in usage.items() if face != main_face and n < 0.05 * total]


def renumber(pkg: Package) -> list[str]:
    """표·그림 캡션 번호를 문서 순서·장별로 다시 매기고, 본문·차례의 참조 글도 같이 고친다."""
    cat = infer(pkg)
    for sec in pkg.section_names():
        pkg.edit(sec)
    fmt = {"표": cat.tbl_label, "그림": cat.fig_label}
    counters: Counter = Counter()
    chapter_seen = 0
    mapping: dict[str, str] = {}
    changes: list[str] = []
    targets, opaque = _caption_targets(pkg)
    targets = [(t, c) for t, c in targets if LABEL_RE.match(t.text.strip()).group(1) not in opaque]
    bare = [t for t, _ in targets if not t.text.strip().startswith("[")]
    if bare:  # '표 2. 제목'처럼 괄호 없는 캡션은 본문 참조를 안전하게 찾을 수 없어 건드리지 않는다
        changes.append(f"괄호 없는 캡션 {len(bare)}개는 본문 참조를 찾을 수 없어 번호를 바꾸지 않았어요.")
    targets = [(t, c) for t, c in targets if t.text.strip().startswith("[")]
    for t, chapter in targets:
        m = LABEL_RE.match(t.text.strip())
        kind = m.group(1)
        if m.group(3) and m.group(2).isdigit():
            chapter = int(m.group(2))  # 장 번호는 캡션에 적힌 번호를 그대로 쓴다 ('1. 서론' 같은 장 제목 대응)
        if chapter != chapter_seen:
            chapter_seen = chapter
            for k in list(counters):
                if "{c}" in fmt[k]:
                    counters[k] = 0
        counters[kind] += 1
        new = fmt[kind].format(c=chapter, n=counters[kind])
        old = m.group(0).strip()
        mapping.setdefault(_key(kind, m.group(2), m.group(3)), new)
        if old != new:
            t.text = t.text.replace(old, new, 1)
            changes.append(f"{old} → {new}")
    caption_ts = {id(t) for t, _ in targets}

    def swap(m):
        return mapping.get(_key(m.group(1), m.group(2), m.group(3)), m.group(0))

    for sec in pkg.section_names():
        for t in pkg.xml(sec).iter(q("hp:t")):
            if id(t) not in caption_ts and t.text:
                t.text = REF_RE.sub(swap, t.text)
    return changes


def review(pkg: Package) -> list[Finding]:
    texts = _texts(pkg)
    period = _period(texts)
    notes = [Finding("확인", "mixed-format", n) for n in infer(pkg).notes
             if "섞여" in n and not n.startswith("빈 줄")]  # 빈 줄 서식 차이는 눈에 보이지 않음
    return (_check_dates(texts, period) + _check_month_headers(pkg, period) + _check_numbering(pkg)
            + _check_cells(pkg) + _check_fonts(pkg) + notes)
