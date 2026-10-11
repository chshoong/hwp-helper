"""매달 이어받기: 지난달 월간보고서 → 이번 달 fill 지시문 초안과 확인할 것 (설계 3장).

문서는 바꾸지 않는다. 숫자(누적·진행률)·새 계획·보고일은 지어내지 않고 확인할 것으로 알린다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .package import Package
from .review import _REPORT_DATE_WORDS, _add_month, _period, _texts, _year

_WEEK = "월화수목금토일"
_YM = re.compile(r"([‘'’]?\s*)(\d{4}|\d{2})(\s*년\s*)(\d{1,2})(\s*월)")
_PAREN = re.compile(r"\(\s*(\d{2})(\s*\.\s*)(\d{1,2})(\s*\.?\s*)\)")
_RANGE = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*~\s*(?:(\d{4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?")
_DOT = re.compile(r"(?<![\d.])(\d{4})(\s*\.\s*)(\d{1,2})(\s*\.?)(?![\s.]*\d)")
_HEAD = re.compile(r"(?<![\d(])(\d{1,2})(\s*월)(\s*)(실적|계획|분|추진|현황|말|중|초)")
_REPORT_DAY = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(?:\(\s*[월화수목금토일]\s*\))?")


class CarryError(ValueError):
    """이어받기 오류. 메시지는 사용자용 한국어."""


def _pad(old: str, new: int) -> str:
    return f"{new:02d}" if len(old) == 2 and old.startswith("0") else str(new)


def _year_text(old: str, y: int) -> str:
    return f"{y % 100:02d}" if len(old) == 2 else str(y)


def _last(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _replacements(texts: list[str], frm: tuple[int, int]) -> list[tuple[str, str]]:
    """지난달(M)·다음 달(M+1)이 들어간 글 → 한 달 뒤 글. 뒤 달 먼저, 같은 달은 긴 글 먼저."""
    nxt = _add_month(*frm, 1)
    found: dict[str, tuple[str, int]] = {}  # 옛 글 → (새 글, 0=M+1 / 1=M)

    def put(old: str, new: str, ym: tuple[int, int]) -> None:
        if ym == nxt:
            found.setdefault(old, (new, 0))
        elif ym == frm:
            found.setdefault(old, (new, 1))

    for text in texts:
        for m in _RANGE.finditer(text):
            y, mo = int(m.group(1)), int(m.group(2))
            if (y, mo) not in (frm, nxt):
                continue
            ny, nm = _add_month(y, mo, 1)
            d1, d2 = int(m.group(3)), int(m.group(6))
            whole = d1 == 1 and d2 == _last(y, int(m.group(5)))
            nd1, nd2 = (1, _last(ny, nm)) if whole else (min(d1, _last(ny, nm)), min(d2, _last(ny, nm)))
            put(m.group(0).strip(), f"{ny}. {nm}. {nd1}. ~ {nm}. {nd2}.", (y, mo))
        for m in _YM.finditer(text):
            y, mo = _year(m.group(2)), int(m.group(4))
            ny, nm = _add_month(y, mo, 1)
            new = f"{m.group(1)}{_year_text(m.group(2), ny)}{m.group(3)}{_pad(m.group(4), nm)}{m.group(5)}"
            put(m.group(0).strip(), new.strip(), (y, mo))
        for m in _PAREN.finditer(text):
            y, mo = _year(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"({_year_text(m.group(1), ny)}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)})", (y, mo))
        for m in _DOT.finditer(text):
            y, mo = int(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"{ny}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)}", (y, mo))
        for m in _HEAD.finditer(text):
            mo = int(m.group(1))
            for ym in (frm, nxt):
                if ym[1] == mo:
                    nm = _add_month(*ym, 1)[1]
                    put(m.group(0), f"{nm}{m.group(2)}{m.group(3)}{m.group(4)}", ym)
    return [(old, new) for old, (new, _) in sorted(found.items(), key=lambda kv: (kv[1][1], -len(kv[0])))]


def _report_dates(texts: list[str]) -> list[dict]:
    out = []
    for text in texts:
        if not _REPORT_DATE_WORDS.search(text):
            continue
        for m in _REPORT_DAY.finditer(text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            day = dt.date(ny, nm, min(d, _last(ny, nm)))
            out.append({"kind": "report-date", "where": text[:40], "address": "", "current": m.group(0).strip(),
                        "suggest": f"{day.year}. {day.month}. {day.day}.({_WEEK[day.weekday()]})",
                        "message": "이번 달 보고일을 알려 주세요"})
    return out


def carry(pkg: Package, to: tuple[int, int] | None = None) -> dict:
    texts_ctx = _texts(pkg)
    found = _period(texts_ctx)
    warnings: list[str] = []
    if to is not None:
        frm = _add_month(*to, -1)
        if found and found != frm:
            warnings.append(f"문서의 보고 기간은 {found[0]}년 {found[1]}월인데 {frm[0]}년 {frm[1]}월 기준으로 만들었어요.")
    elif found:
        frm, to = found, _add_month(*found, 1)
    else:
        raise CarryError("지난달 보고 기간을 찾지 못했어요. --to 2026-10처럼 이번 달을 알려 주세요.")
    texts = [t for t, _ in texts_ctx]
    plain = [t for t, ctx in texts_ctx if not _REPORT_DATE_WORDS.search(ctx)]
    lines = [f"@바꾸기 {old} => {new}" for old, new in _replacements(plain, frm)]
    ask = _report_dates(texts)
    return {"from": frm, "to": to, "spec": "\n".join(lines) + ("\n" if lines else ""), "ask": ask,
            "warnings": warnings}
