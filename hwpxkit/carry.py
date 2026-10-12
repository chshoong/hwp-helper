"""매달 이어받기: 지난달 월간보고서 → 이번 달 fill 지시문 초안과 확인할 것 (설계 3장).

문서는 바꾸지 않는다. 숫자(누적·진행률)·새 계획·보고일은 지어내지 않고 확인할 것으로 알린다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .form import FormError, cells, replace_text
from .ns import q
from .package import Package
from .review import _CURRENT, _NEXT, _REPORT_DATE_WORDS, _add_month, _period, _texts, _year

_WEEK = "월화수목금토일"
_YM = re.compile(r"([‘'’]?\s*)(\d{4}|\d{2})(\s*년\s*)(\d{1,2})(\s*월)")
_PAREN = re.compile(r"\(\s*(\d{2})(\s*\.\s*)(\d{1,2})(\s*\.?\s*)\)")
_RANGE = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*~\s*(?:(\d{4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?")
_DOT = re.compile(r"(?<![\d.])(\d{4})(\s*\.\s*)(\d{1,2})(\s*\.?)(?![\s.]*\d)")
_HEAD = re.compile(r"(?<![\d(])(\d{1,2})(\s*월)(\s*)(실적|계획|분|추진|현황|말|중|초)")
_YMD_KO = re.compile(r"(\d{4}|\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_YEAR_BEFORE = re.compile(r"(\d{2,4}\s*년\s*|[‘'’]\d{2}\s*)$")
_MONTH_IN = re.compile(r"(\d{1,2})\s*월")
_REPORT_DAY = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(?:\(\s*[월화수목금토일]\s*\))?")


class CarryError(ValueError):
    """이어받기 오류. 메시지는 사용자용 한국어."""


def _pad(old: str, new: int) -> str:
    return f"{new:02d}" if len(old) == 2 and old.startswith("0") else str(new)


def _year_text(old: str, y: int) -> str:
    return f"{y % 100:02d}" if len(old) == 2 else str(y)


def _last(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _replacements(texts: list[str], frm: tuple[int, int]) -> list[tuple[str, str, list]]:
    """지난달(M)·다음 달(M+1)이 들어간 글 → 한 달 뒤 글. 뒤 달 먼저, 같은 달은 긴 글 먼저.
    (옛 글, 새 글, 찾은 자리 [(문단 글, 시작, 끝)]) 목록."""
    nxt = _add_month(*frm, 1)
    found: dict[str, tuple[str, int]] = {}  # 옛 글 → (새 글, 0=M+1 / 1=M)
    where: dict[str, list] = {}

    def put(old: str, new: str, ym: tuple[int, int], text: str, start: int) -> None:
        if ym not in (frm, nxt):
            return
        found.setdefault(old, (new, 0 if ym == nxt else 1))
        s = text.find(old, start)
        where.setdefault(old, []).append((text, s, s + len(old)))

    for text in texts:
        for m in _RANGE.finditer(text):
            y, mo = int(m.group(1)), int(m.group(2))
            if (y, mo) not in (frm, nxt):
                continue
            y2, m2 = (int(m.group(4)) if m.group(4) else y), int(m.group(5))
            ny, nm = _add_month(y, mo, 1)
            ny2, nm2 = _add_month(y2, m2, 1)
            d1, d2 = int(m.group(3)), int(m.group(6))
            whole = d1 == 1 and (y2, m2) == (y, mo) and d2 == _last(y, mo)
            nd1 = 1 if whole else min(d1, _last(ny, nm))
            nd2 = _last(ny2, nm2) if whole else min(d2, _last(ny2, nm2))
            end = (f"{ny2}. " if m.group(4) or ny2 != ny else "") + f"{nm2}. {nd2}."
            put(m.group(0).strip(), f"{ny}. {nm}. {nd1}. ~ {end}", (y, mo), text, m.start())
        for m in _YM.finditer(text):
            if re.match(r"\s*\d{1,2}\s*일", text[m.end():]):  # 일까지 쓴 날짜는 확인할 것으로
                continue
            y, mo = _year(m.group(2)), int(m.group(4))
            ny, nm = _add_month(y, mo, 1)
            new = f"{m.group(1)}{_year_text(m.group(2), ny)}{m.group(3)}{_pad(m.group(4), nm)}{m.group(5)}"
            put(m.group(0).strip(), new.strip(), (y, mo), text, m.start())
        for m in _PAREN.finditer(text):
            y, mo = _year(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"({_year_text(m.group(1), ny)}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)})", (y, mo),
                text, m.start())
        for m in _DOT.finditer(text):
            y, mo = int(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"{ny}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)}", (y, mo), text, m.start())
        for m in _HEAD.finditer(text):
            if _YEAR_BEFORE.search(text[:m.start()]):  # 연도가 붙은 달은 연월 꼴이 맡는다 (다른 해 보호)
                continue
            mo = int(m.group(1))
            for ym in (frm, nxt):
                if ym[1] == mo:
                    nm = _add_month(*ym, 1)[1]
                    put(m.group(0), f"{nm}{m.group(2)}{m.group(3)}{m.group(4)}", ym, text, m.start())
    return [(old, new, where[old]) for old, (new, _) in sorted(found.items(), key=lambda kv: (kv[1][1], -len(kv[0])))]


def _clone(pkg: Package) -> Package:
    return Package({n: pkg.read(n) for n in pkg.names()}, dict(pkg._compress), list(pkg._order))


def _hits(pkg: Package, old: str, new: str) -> tuple[int, Package]:
    probe = _clone(pkg)
    try:
        return replace_text(probe, old, new), probe
    except FormError:
        return 0, probe


def _safe_lines(pkg: Package, pairs) -> tuple[list[str], list[dict]]:
    """바꾸기 줄을 실제 문서에 차례로 대 보고, 찾은 자리보다 많이 바뀌는 줄(다른 날짜·보고일·다른 해까지 건드림)은
    앞뒤 글을 붙여 그 자리만 바꾸게 한다. 그래도 안 되면 빼고 확인할 것으로 올린다."""
    current, lines, ask = _clone(pkg), [], []
    for old, new, spots in pairs:
        n, probe = _hits(current, old, new)
        if n == 0:  # 앞 줄이 이미 바꿈 (겹치는 글)
            continue
        if n <= len(spots):
            current = probe
            lines.append(f"@바꾸기 {old} => {new}")
            continue
        for text, s, e in spots:
            done = False
            for left, right in [(0, k) for k in range(1, 13)] + [(k, 0) for k in range(1, 13)] + [(k, k) for k in range(1, 13)]:
                if s - left < 0 or e + right > len(text):
                    continue
                ext_old = text[s - left:e + right]
                if ext_old != ext_old.strip():  # 지시문은 앞뒤 공백을 잘라 읽는다
                    continue
                ext_new = text[s - left:s] + new + text[e:e + right]
                want = sum(1 for t2, s2, e2 in spots if t2[s2 - left:e2 + right] == ext_old)
                n2, probe2 = _hits(current, ext_old, ext_new)
                if n2 == want and n2 > 0:
                    current = probe2
                    if f"@바꾸기 {ext_old} => {ext_new}" not in lines:
                        lines.append(f"@바꾸기 {ext_old} => {ext_new}")
                    done = True
                    break
            if not done:
                ask.append({"kind": "manual", "where": text[:40], "address": "", "current": old, "suggest": new,
                            "message": "다른 날짜와 겹쳐서 자동으로 바꾸지 않았어요. 이 자리는 직접 확인해 주세요"})
    return lines, ask


def _full_dates(texts: list[str], frm: tuple[int, int]) -> list[dict]:
    """'2026년 9월 30일'처럼 일까지 쓴 날짜는 바꾸지 않고 확인할 것으로 (없는 날짜·반쪽 기간 방지)."""
    nxt = _add_month(*frm, 1)
    out = []
    for text in texts:
        for m in _YMD_KO.finditer(text):
            if (_year(m.group(1)), int(m.group(2))) in (frm, nxt):
                out.append({"kind": "date", "where": text[:40], "address": "", "current": m.group(0), "suggest": "",
                            "message": "일까지 쓴 날짜라 자동으로 바꾸지 않았어요. 이번 달 날짜를 알려 주세요"})
    return out


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


_NUM_HEAD = re.compile(r"누적|진행률|진척률|달성률|공정률|집행률|%")
_NUM_TEXT = re.compile(r"^[-+]?[\d,]*\.?\d+\s*%?$")
_OBJ = ("hp:tbl", "hp:pic", "hp:equation")


def _has_object(tc) -> bool:
    sub = tc.find(q("hp:subList"))
    return any(next(p.iter(q(t)), None) is not None for p in sub.findall(q("hp:p")) for t in _OBJ)


def _months(head: str) -> set[int]:
    return {int(x) for x in _MONTH_IN.findall(head)}


def _is_current(head: str, frm: tuple[int, int]) -> bool:
    """이번 달(보고 달) 열: '금월·당월·이번 달' 또는 보고 달 'N월'이 머리에 있음. 달 표시 없는 '실적'은 아님."""
    nxt = _add_month(*frm, 1)
    cur = bool(_CURRENT.search(head)) or frm[1] in _months(head)
    return cur and not (_NEXT.search(head) or nxt[1] in _months(head))


def _is_next(head: str, frm: tuple[int, int]) -> bool:
    nxt = _add_month(*frm, 1)
    n = bool(_NEXT.search(head)) or nxt[1] in _months(head)
    return n and not (_CURRENT.search(head) or frm[1] in _months(head))


def _addr(t: int, r: int, c: int) -> str:
    """바꾸기 줄이 머리 글을 바꿔도 맞는 칸을 가리키도록 번호 주소."""
    return f"@칸 표{t} | #{r + 1} | #{c + 1}"


def _plan_moves(pkg: Package, frm: tuple[int, int]) -> tuple[list[str], list[dict]]:
    """금월 실적 ← 차월 계획 (같은 표·같은 행), 차월 계획 칸은 비움."""
    all_cells = cells(pkg)
    lines, ask = [], []
    for t in sorted({c.table for c in all_cells}):
        tc = [c for c in all_cells if c.table == t]
        heads = {c.col: c.text for c in tc if c.row == 0 and c.colspan == 1}
        cur = [col for col, h in heads.items() if _is_current(h, frm)]
        nxt = [col for col, h in heads.items() if _is_next(h, frm)]
        if not cur and not nxt:
            if any("계획" in h or "실적" in h for h in heads.values()):  # 목표 대비 실적 같은 표
                ask.append({"kind": "plan-columns", "where": f"표{t}", "address": "", "current": "", "suggest": "",
                            "message": "계획·실적 열에 달 표시가 없어 옮기지 않았어요. 이 표는 직접 확인해 주세요."})
            continue
        if len(cur) != 1 or len(nxt) != 1:
            ask.append({"kind": "plan-columns", "where": f"표{t}", "address": "", "current": "", "suggest": "",
                        "message": "계획·실적 열을 정확히 찾지 못했어요. 이 표는 직접 확인해 주세요."})
            continue
        grid = {(c.row, c.col): c for c in tc}
        for r in sorted({c.row for c in tc if c.row > 0}):
            src, dst = grid.get((r, nxt[0])), grid.get((r, cur[0]))
            if src is None or dst is None or src.rowspan != 1 or dst.rowspan != 1:
                continue
            if not src.text or _has_object(src.tc) or _has_object(dst.tc):
                continue
            a_dst, a_src = _addr(t, r, cur[0]), _addr(t, r, nxt[0])
            lines += [a_dst, src.text, "", a_src, "", ""]
            ask.append({"kind": "next-plan", "where": f"표{t} {src.row_header or f'{r + 1}행'}", "address": a_src,
                        "current": "", "suggest": "", "message": "다음 달 계획을 새로 알려 주세요"})
    return lines, ask


def _numbers(pkg: Package) -> list[dict]:
    out = []
    for c in cells(pkg):
        if c.row == 0 or c.col == 0:
            continue
        text = c.text.strip()
        if _NUM_HEAD.search(f"{c.row_header} {c.col_header}") and _NUM_TEXT.match(text):
            out.append({"kind": "number", "where": c.label(), "address": _addr(c.table, c.row, c.col),
                        "current": text, "suggest": "", "message": "이번 달 값이 필요해요"})
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
    lines, manual = _safe_lines(pkg, _replacements(plain, frm))
    moves, move_ask = _plan_moves(pkg, frm)
    lines += [""] + moves if moves else []
    ask = _report_dates(texts) + manual + _full_dates(plain, frm) + move_ask + _numbers(pkg)
    spec = "\n".join(lines) + "\n" if lines else ""
    return {"from": frm, "to": to, "spec": spec, "ask": ask, "warnings": warnings}
