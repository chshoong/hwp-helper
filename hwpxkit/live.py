"""사용자가 열어 둔 한글 창과의 실시간 연동. 화면 속 문서를 읽고 고치되 절대 저장하지 않는다.

live_hwp.ps1이 실행 중 개체 목록(ROT)의 '!HwpObject'로 사용자 한글에 붙어 동작 하나를 하고
JSON 한 줄을 돌려준다. 인자는 한글 경로·글자 문제를 피하려고 JSON 파일로 넘긴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import bridge
from .body import own_text
from .bridge import BridgeError
from .header import Header
from .ns import q
from .package import CONTENT_HPF, HEADER, Package
from .render import _caption_counts, render_into
from .review import review as _review
from .samples import bullet_chars, classify, heading_levels, infer

_PS1 = Path(__file__).with_name("live_hwp.ps1")
_runner = subprocess.run
TIMEOUT = 60
# 조각을 넣기 전 화면 문서를 남겨 두는 곳 (되살리기용 사본)
BACKUP_DIR = Path(tempfile.gettempdir()) / "hwpx-live"
# 문서를 바꾸는 동작: 도중에 시간이 초과되면 일부만 바뀌었을 수 있다
_MODIFYING = {"replace_text", "insert_file", "replace_between", "memos"}

_ERRORS = {
    "not_running": "한글에서 문서를 연 뒤 다시 말씀해 주세요.",
    "no_selection": "한글에서 고칠 부분을 드래그해 주세요.",
    "unknown_action": "내부 오류: 알 수 없는 한글 작업이에요.",
    "start_not_found": "한글 화면에서 그 제목을 찾지 못했어요. 문서가 바뀌었으면 다시 말씀해 주세요.",
    "end_not_found": "한글 화면에서 다음 제목을 찾지 못했어요. 문서가 바뀌었으면 다시 말씀해 주세요.",
    "range_unsafe": ("장 범위를 안전하게 찾지 못해 아무것도 지우지 않았어요. 제목이 표 안에도 있거나 문서가 바뀌었을 수 "
                     "있어요. 바꿀 부분을 한글에서 드래그한 뒤 '고른 부분 바꾸기'로 해 주세요."),
}
_OUTSIDE_BODY = "커서가 표 칸·각주·글상자 안에 있어요. 표·글머리 묶음은 본문에만 넣을 수 있으니, 커서를 본문으로 옮긴 뒤 다시 말씀해 주세요."


class LiveError(BridgeError):
    """열린 한글 연동 실패. 메시지는 사용자에게 그대로 보여 줄 수 있는 한국어."""


def _names(paths) -> str:
    return ", ".join(Path(p).name if p else "(저장 안 한 새 문서)" for p in paths)


def call(action: str, **params) -> dict:
    bridge._require()
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        args = Path(tmp) / "args.json"
        args.write_text(json.dumps({"action": action, **params}, ensure_ascii=False), encoding="utf-8")
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(_PS1), "-ArgsFile", str(args)]
        try:
            proc = _runner(cmd, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired as e:
            msg = "한글이 응답하지 않아요. 한글에 떠 있는 확인 창이 있으면 닫고 다시 말씀해 주세요."
            if action in _MODIFYING:
                msg += (" 고치던 도중이라 문서가 일부 바뀌었을 수 있어요. 한글에서 확인하고, 필요하면 되돌리기(Ctrl+Z)나 "
                        f"되살리기용 사본({BACKUP_DIR})을 쓰세요.")
            raise LiveError(msg) from e
    lines = proc.stdout.decode("utf-8-sig", errors="replace").strip().splitlines()
    if not lines:
        raise LiveError("한글 연동 스크립트가 결과를 돌려주지 않았어요: "
                        + proc.stderr.decode("utf-8", errors="replace")[:300])
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise LiveError(f"한글 연동 결과를 읽지 못했어요: {lines[-1][:300]}") from e
    if result.get("ok"):
        return result
    error = str(result.get("error", ""))
    if error == "doc_ambiguous":
        raise LiveError(f"여러 문서가 맞아요: {_names(result.get('docs', []))}. 문서 이름을 더 정확히 알려 주세요.")
    if error == "doc_not_found":
        raise LiveError(f"그 이름의 문서가 열려 있지 않아요. 열린 문서: {_names(result.get('docs', []))}")
    raise LiveError(_ERRORS.get(error, f"한글 작업 중 오류가 났어요: {error}"))


def status(doc: str | None = None) -> dict:
    r = call("status", doc=doc)
    return {k: r[k] for k in ("docs", "active", "modified", "selection")}


def selection(doc: str | None = None) -> dict:
    r = call("selection", doc=doc)
    if not r.get("selected"):
        return {"selected": False, "text": "", "para": -1, "list": 0, "in_table": False, "paragraphs": 0,
                "ends_break": False}
    raw = r["text"].replace("\r\n", "\n").replace("\r", "\n")
    text = raw.rstrip("\n")
    return {"selected": True, "text": text, "para": int(r["para"]), "list": int(r.get("list", 0)),
            "in_table": bool(r["in_table"]), "paragraphs": len(text.split("\n")),
            "ends_break": raw.endswith("\n")}


def export(out, doc: str | None = None) -> Path:
    """화면 속 문서(저장 안 한 수정 포함)를 .hwpx로 내보낸다. 사용자 창의 경로·수정 상태는 그대로."""
    out = Path(out)
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        raw = Path(tmp) / "screen.hwp"
        call("export", doc=doc, out=str(raw))
        bridge.convert(raw, out)
    return out


def _backup(screen: Path) -> Path:
    """조각을 넣기 전 화면 문서를 되살리기용 사본으로 남긴다."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst = BACKUP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_화면.hwpx"
    shutil.copyfile(screen, dst)
    return dst


def hwp_exe() -> Path:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID") as k:
        clsid = winreg.QueryValue(k, None)
    for base in (r"WOW6432Node\CLSID", "CLSID"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{base}\{clsid}\LocalServer32") as k:
                return Path(winreg.QueryValue(k, None).split(" -")[0].strip('"'))
        except OSError:
            continue
    raise LiveError("한글 실행 파일을 찾지 못했어요.")


_BLOCK = re.compile(r"^\s*(#|[□○◦\-·•*※]\s|\||\$\$|!\[|표:)")
last_warnings: list[str] = []


def _needs_fragment(md: str, selected_paragraphs: int) -> bool:
    """글만 바꾸면 되는지(한 문단 → 한 문장), 엔진 조각이 필요한지."""
    lines = [ln for ln in md.strip().splitlines() if ln.strip()]
    return selected_paragraphs > 1 or len(lines) != 1 or bool(_BLOCK.match(lines[0]))


def _plain(md: str) -> str:
    """한 줄 마크다운의 꾸밈 기호를 걷어 낸 글 (글자 모양은 선택 자리의 것을 그대로 쓴다)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", md.strip())
    return re.sub(r"\[\[색:[^\]]+\]\](.+?)\[\[/색\]\]", r"\1", text)


def _drop_extra_sections(pkg: Package) -> None:
    """첫 구역만 남긴다. 조각에 뒤 구역(본문 전체 등)이 딸려 들어가지 않게."""
    extra = pkg.section_names()[1:]
    if not extra:
        return
    hpf = pkg.edit(CONTENT_HPF)
    ids = {it.get("id") for it in hpf.iter(q("opf:item")) if it.get("href") in extra}
    for it in list(hpf.iter(q("opf:item"))):
        if it.get("id") in ids:
            it.getparent().remove(it)
    for ref in list(hpf.iter(q("opf:itemref"))):
        if ref.get("idref") in ids:
            ref.getparent().remove(ref)
    for name in extra:
        pkg.remove(name)
    pkg.edit(HEADER).set("secCnt", "1")


def _strip_page_controls(pkg: Package) -> None:
    """조각 첫 문단의 머리말·꼬리말·쪽 번호 같은 개체를 뺀다 (단 정의 colPr만 남김)."""
    first = next(p for p in pkg.edit(pkg.section_names()[0]) if p.tag == q("hp:p"))
    for ctrl in list(first.iter(q("hp:ctrl"))):
        if any(child.tag != q("hp:colPr") for child in ctrl):
            ctrl.getparent().remove(ctrl)


def fragment(md: str, screen: Path, *, base_dir: Path, before_para: int | None) -> Path:
    """화면 문서의 견본으로 조각(.hwpx)을 만든다. before_para 앞의 캡션 수 다음부터 번호를 매긴다."""
    global last_warnings
    pkg = Package.open(screen)
    _drop_extra_sections(pkg)
    tops = [p for p in pkg.xml(pkg.section_names()[0]) if p.tag == q("hp:p")]
    number_from = _caption_counts(tops[:before_para]) if before_para is not None else None
    last_warnings = render_into(pkg, infer(Package.open(screen)), md, mode="new", base_dir=base_dir,
                                number_from=number_from)
    _strip_page_controls(pkg)
    out = screen.with_name("fragment.hwpx")
    pkg.save(out)
    return out


def replace(md: str, doc: str | None = None, base_dir: Path = Path(".")) -> dict:
    sel = selection(doc)
    if not sel["selected"]:
        raise LiveError(_ERRORS["no_selection"])
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        if not _needs_fragment(md, sel["paragraphs"]):
            txt = Path(tmp) / "text.txt"
            # 선택이 문단 끝까지 걸쳐 있으면 문단 나눔도 함께 넣어 다음 문단과 합쳐지지 않게 한다
            txt.write_text(_plain(md) + ("\r\n" if sel["ends_break"] else ""), encoding="utf-8", newline="")
            call("replace_text", doc=doc, text_file=str(txt))
            return {"mode": "text", "warnings": [], "backup": None}
        if sel["list"] != 0:
            raise LiveError(_OUTSIDE_BODY)
        screen = export(Path(tmp) / "screen.hwpx", doc)
        backup = _backup(screen)
        frag = fragment(md, screen, base_dir=base_dir, before_para=sel["para"])
        call("insert_file", doc=doc, file=str(frag), replace_selection=True)
        return {"mode": "fragment", "warnings": list(last_warnings), "backup": str(backup)}


def insert(md: str, doc: str | None = None, base_dir: Path = Path(".")) -> dict:
    pos = call("captions_before", doc=doc)
    if int(pos.get("list", 0)) != 0:
        raise LiveError(_OUTSIDE_BODY)
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        screen = export(Path(tmp) / "screen.hwpx", doc)
        backup = _backup(screen)
        frag = fragment(md, screen, base_dir=base_dir, before_para=int(pos["para"]) + 1)
        call("insert_file", doc=doc, file=str(frag), replace_selection=False)
    return {"warnings": list(last_warnings), "backup": str(backup)}


def _review_file(path: Path):
    return _review(Package.open(path))


def review(doc: str | None = None, memo: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        findings = _review_file(export(Path(tmp) / "screen.hwpx", doc))
    if not memo:
        return {"findings": findings, "placed": 0, "missed": []}
    memos = [{"anchor": f.anchor, "text": f"[검토] {f.message}"} for f in findings if f.anchor]
    if not memos:
        return {"findings": findings, "placed": 0, "missed": []}
    r = call("memos", doc=doc, memos=memos)
    return {"findings": findings, "placed": int(r["placed"]), "missed": list(r.get("missed") or [])}


# 장 다시 쓰기에서 '장'으로 볼 역할과 단계 (작을수록 높은 단계)
_HEAD_RANK = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "bullet1": 6}


def section_bounds(screen: Path, heading: str) -> tuple[str, int, str | None, int]:
    """heading으로 시작하는 본문 제목부터, 같은 단계나 더 높은 단계의 다음 제목 앞까지.
    한글 찾기용으로 (시작 글, 등장 순번, 끝 글 또는 None, 등장 순번)을 돌려준다."""
    if not heading.strip():
        raise LiveError("바꿀 장의 제목 글자를 알려 주세요 (예: 제2장).")
    pkg = Package.open(screen)
    if len(pkg.section_names()) > 1:
        raise LiveError("구역이 여러 개인 문서는 아직 장 다시 쓰기를 지원하지 않아요. "
                        "바꿀 부분을 한글에서 드래그한 뒤 '고른 부분 바꾸기'로 해 주세요.")
    h = Header(pkg)
    chars = bullet_chars(h)
    root = pkg.xml(pkg.section_names()[0])
    tops = [p for p in root if p.tag == q("hp:p")]
    levels = heading_levels(tops)
    roles = [classify(p, h, chars, levels)[0] for p in tops]
    texts = [own_text(p).strip() for p in tops]
    rank = [_HEAD_RANK.get(r) for r in roles]

    def next_content(i: int) -> int | None:
        return next((j for j in range(i + 1, len(tops)) if texts[j] or roles[j] != "blank"), None)

    def toc_like(i: int) -> bool:  # 차례: 내용 없이 같은 단계 이상의 제목이 바로 이어짐
        j = next_content(i)
        return j is not None and rank[j] is not None and rank[j] <= rank[i]

    cands = [i for i in range(len(tops)) if rank[i] is not None and texts[i].startswith(heading)]
    if not cands:
        raise LiveError(f"'{heading}' 제목을 찾지 못했어요. 한글 화면의 제목 글자 그대로 알려 주세요.")
    start = next((i for i in cands if not toc_like(i)), cands[-1])
    end = next((i for i in range(start + 1, len(tops)) if rank[i] is not None and rank[i] <= rank[start]), None)

    order = list(root.iter(q("hp:p")))  # 한글 찾기는 표 칸 안 글까지 문서 순서대로 센다

    def occurrence(i: int) -> int:
        target, n = texts[i], 0
        for p in order:
            n += own_text(p).count(target)
            if p is tops[i]:
                return n
        return n

    return (texts[start], occurrence(start),
            texts[end] if end is not None else None, occurrence(end) if end is not None else 0)


def section(heading: str, md: str, doc: str | None = None, base_dir: Path = Path(".")) -> dict:
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        screen = export(Path(tmp) / "screen.hwpx", doc)
        start, n1, end, n2 = section_bounds(screen, heading)
        pkg = Package.open(screen)
        tops = [p for p in pkg.xml(pkg.section_names()[0]) if p.tag == q("hp:p")]
        hits = [i for i, p in enumerate(tops) if own_text(p).strip() == start]
        before = hits[-1] if hits else None
        backup = _backup(screen)
        frag = fragment(md, screen, base_dir=base_dir, before_para=before)
        call("replace_between", doc=doc, start=start, start_n=n1, end=end or "", end_n=n2, file=str(frag))
    return {"start": start, "end": end, "warnings": list(last_warnings), "backup": str(backup)}
