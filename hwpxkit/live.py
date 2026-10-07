"""사용자가 열어 둔 한글 창과의 실시간 연동. 화면 속 문서를 읽고 고치되 절대 저장하지 않는다.

live_hwp.ps1이 실행 중 개체 목록(ROT)의 '!HwpObject'로 사용자 한글에 붙어 동작 하나를 하고
JSON 한 줄을 돌려준다. 인자는 한글 경로·글자 문제를 피하려고 JSON 파일로 넘긴다.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from . import bridge
from .bridge import BridgeError

_PS1 = Path(__file__).with_name("live_hwp.ps1")
_runner = subprocess.run
TIMEOUT = 60

_ERRORS = {
    "not_running": "한글에서 문서를 연 뒤 다시 말씀해 주세요.",
    "no_selection": "한글에서 고칠 부분을 드래그해 주세요.",
    "unknown_action": "내부 오류: 알 수 없는 한글 작업이에요.",
}


class LiveError(BridgeError):
    """열린 한글 연동 실패. 메시지는 사용자에게 그대로 보여 줄 수 있는 한국어."""


def _names(paths) -> str:
    return ", ".join(Path(p).name for p in paths)


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
            raise LiveError("한글이 응답하지 않아요. 한글에 떠 있는 확인 창이 있으면 닫고 다시 말씀해 주세요.") from e
    lines = proc.stdout.decode("utf-8-sig", errors="replace").strip().splitlines()
    if not lines:
        raise LiveError("한글 연동 스크립트가 결과를 돌려주지 않았어요: "
                        + proc.stderr.decode("utf-8", errors="replace")[:300])
    result = json.loads(lines[-1])
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
        return {"selected": False, "text": "", "para": -1, "in_table": False, "paragraphs": 0}
    text = r["text"].replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return {"selected": True, "text": text, "para": int(r["para"]), "in_table": bool(r["in_table"]),
            "paragraphs": len(text.split("\n"))}


def export(out, doc: str | None = None) -> Path:
    """화면 속 문서(저장 안 한 수정 포함)를 .hwpx로 내보낸다. 사용자 창의 경로·수정 상태는 그대로."""
    out = Path(out)
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        raw = Path(tmp) / "screen.hwp"
        call("export", doc=doc, out=str(raw))
        bridge.convert(raw, out)
    return out


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


import re  # noqa: E402

from .package import Package  # noqa: E402
from .render import _caption_counts, render_into  # noqa: E402
from .samples import infer  # noqa: E402

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


def fragment(md: str, screen: Path, *, base_dir: Path, before_para: int | None) -> Path:
    """화면 문서의 견본으로 조각(.hwpx)을 만든다. before_para 앞의 캡션 수 다음부터 번호를 매긴다."""
    global last_warnings
    pkg = Package.open(screen)
    tops = [p for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p")]
    number_from = _caption_counts(tops[:before_para]) if before_para is not None else None
    last_warnings = render_into(pkg, infer(Package.open(screen)), md, mode="new", base_dir=base_dir,
                                number_from=number_from)
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
            txt.write_text(_plain(md), encoding="utf-8")
            call("replace_text", doc=doc, text_file=str(txt))
            return {"mode": "text", "warnings": []}
        screen = export(Path(tmp) / "screen.hwpx", doc)
        frag = fragment(md, screen, base_dir=base_dir, before_para=sel["para"])
        call("insert_file", doc=doc, file=str(frag), replace_selection=True)
        return {"mode": "fragment", "warnings": list(last_warnings)}


def insert(md: str, doc: str | None = None, base_dir: Path = Path(".")) -> dict:
    para = int(call("captions_before", doc=doc)["para"])
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        screen = export(Path(tmp) / "screen.hwpx", doc)
        frag = fragment(md, screen, base_dir=base_dir, before_para=para + 1)
        call("insert_file", doc=doc, file=str(frag), replace_selection=False)
    return {"warnings": list(last_warnings)}


from .review import review as _review  # noqa: E402


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
