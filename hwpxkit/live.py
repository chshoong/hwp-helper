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
