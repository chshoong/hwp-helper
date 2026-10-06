"""한글(한컴오피스) 연동. Windows + 한글이 설치된 경우에만 동작한다.

PowerShell로 HWPFrame.HwpObject COM을 호출하므로 pywin32가 필요 없다.
호출마다 한글을 새로 띄우고 끝나면 닫는다(상태를 남기지 않음).

한글은 경로가 260자 안팎을 넘으면 파일을 열지 못한다. 그래서 입력·출력은 항상
짧은 임시 폴더(src.hwpx, out.pdf …)를 거쳐 주고받는다.
"""
from __future__ import annotations

import contextlib
import functools
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_PS1 = Path(__file__).with_name("bridge_hwp.ps1")
FORMATS = {".hwp": "HWP", ".hwpx": "HWPX", ".pdf": "PDF"}
DEFAULT_TIMEOUT = 300

_ERRORS = {
    "no_hwp": "한글 프로그램을 실행하지 못했어요.",
    "open_failed": "한글이 파일을 열지 못했어요. 파일이 손상됐거나 다른 프로그램에서 열려 있을 수 있어요.",
    "unknown_action": "내부 오류: 알 수 없는 한글 작업이에요.",
}


class BridgeError(RuntimeError):
    """한글 연동 실패. 메시지는 사용자에게 그대로 보여줄 수 있는 한국어."""


# 앞서 띄운 한글이 닫히는 중일 때 새로 연결하면 나는 COM 오류 (잠시 뒤 다시 하면 됨)
_RETRYABLE = ("0x800706BA", "0x80010108", "0x800706BE")
_EXIT_WAIT = 20.0


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """한글 COM 객체가 등록된 Windows인지."""
    if os.name != "nt":
        return False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "HWPFrame.HwpObject"))
        return True
    except OSError:
        return False


@contextlib.contextmanager
def _workdir():
    work = Path(tempfile.mkdtemp(prefix="hx"))
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _require() -> None:
    if not available():
        raise BridgeError("한글(한컴오피스)이 설치된 Windows에서만 할 수 있는 작업이에요.")


def _stage(src, work: Path) -> Path:
    """원본을 짧은 경로로 복사한다 (긴 경로·특수문자 문제 회피)."""
    src = Path(src)
    if not src.is_file():
        raise BridgeError(f"파일을 찾을 수 없어요: {src}")
    staged = work / ("src" + src.suffix.lower())
    shutil.copyfile(src, staged)
    return staged


def _kill_started(pid_file: Path) -> None:
    """시간 초과 시, 이번 호출이 띄운 한글 프로세스만 종료한다."""
    try:
        pids = [p for p in pid_file.read_text().strip().split(",") if p.strip().isdigit()]
    except OSError:
        return
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid.strip(), "/T", "/F"], capture_output=True)


def _pids(pid_file: Path) -> list[str]:
    try:
        return [p.strip() for p in pid_file.read_text().split(",") if p.strip().isdigit()]
    except OSError:
        return []


def _alive(pid: str) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True).stdout
    return pid in out.decode("utf-8", errors="replace")


def _wait_exit(pid_file: Path) -> None:
    """이번 호출이 띄운 한글이 완전히 닫힐 때까지 기다린다 (다음 호출이 닫히는 한글에 붙지 않도록)."""
    deadline = time.monotonic() + _EXIT_WAIT
    for pid in _pids(pid_file):
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.3)


def _run(action: str, work: Path, *, src=None, dst=None, fmt=None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    _require()
    for attempt in (1, 2):
        result = _run_once(action, work, src=src, dst=dst, fmt=fmt, timeout=timeout)
        error = str(result.get("error", ""))
        if result.get("ok") or attempt == 2 or not any(code in error for code in _RETRYABLE):
            break
        time.sleep(2)
    if not result.get("ok"):
        raise BridgeError(_ERRORS.get(error, f"한글 작업 중 오류가 났어요: {error}"))
    return result


def _run_once(action: str, work: Path, *, src, dst, fmt, timeout: int) -> dict:
    pid_file = work / "hwp.pid"
    pid_file.unlink(missing_ok=True)
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(_PS1), "-Action", action, "-PidFile", str(pid_file)]
    if src is not None:
        cmd += ["-Src", str(src)]
    if dst is not None:
        cmd += ["-Dst", str(dst)]
    if fmt is not None:
        cmd += ["-Format", fmt]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        _kill_started(pid_file)
        raise BridgeError(
            f"한글이 {timeout}초 안에 응답하지 않아 작업을 멈췄어요. "
            "파일이 매우 크거나 한글 안에서 확인 창이 떴을 수 있어요. 한글에서 직접 한 번 열어 확인해 주세요."
        ) from e
    _wait_exit(pid_file)
    lines = proc.stdout.decode("utf-8-sig", errors="replace").strip().splitlines()
    if not lines:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BridgeError(f"한글 연동 스크립트가 결과를 돌려주지 않았어요: {err[:300]}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise BridgeError(f"한글 연동 결과를 읽지 못했어요: {lines[-1][:300]}") from e


def check(path) -> int:
    """한글로 열어 보고 쪽 수를 돌려준다. 열리지 않으면 BridgeError."""
    _require()
    with _workdir() as work:
        return int(_run("check", work, src=_stage(path, work))["pages"])


def convert(src, dst) -> Path:
    """한글로 열어 dst 확장자 형식(.hwp/.hwpx/.pdf)으로 저장한다."""
    dst = Path(dst)
    fmt = FORMATS.get(dst.suffix.lower())
    if fmt is None:
        raise ValueError(f"지원하지 않는 형식이에요: {dst.suffix} (가능: {', '.join(FORMATS)})")
    if Path(src).resolve() == dst.resolve():
        raise ValueError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    _require()
    with _workdir() as work:
        out = work / ("out" + dst.suffix.lower())
        _run("convert", work, src=_stage(src, work), dst=out, fmt=fmt)
        if not out.exists():
            raise BridgeError(f"변환 결과 파일이 만들어지지 않았어요: {dst.name}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dst)
    return dst


def refresh_equations(src, dst) -> tuple[Path, int]:
    """모든 수식에 같은 스크립트를 다시 적용해 한글이 크기를 계산하게 하고 dst(.hwpx)로 저장한다."""
    dst = Path(dst)
    if dst.suffix.lower() != ".hwpx":
        raise ValueError(f"수식 크기를 맞춘 결과는 .hwpx로 저장해요: {dst.name}")
    if Path(src).resolve() == dst.resolve():
        raise ValueError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    _require()
    with _workdir() as work:
        out = work / "out.hwpx"
        result = _run("refresh", work, src=_stage(src, work), dst=out)
        if not out.exists():
            raise BridgeError("수식 크기를 맞춘 파일이 만들어지지 않았어요.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dst)
    return dst, int(result.get("count", 0))


def page_images(path, out_dir) -> list[Path]:
    """쪽마다 PNG(96dpi)를 out_dir/page001.png … 로 만든다."""
    from PIL import Image

    _require()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with _workdir() as work:
        pages_dir = work / "pages"
        pages_dir.mkdir()
        files = _run("pages", work, src=_stage(path, work), dst=pages_dir)["files"]
        if isinstance(files, str):
            files = [files]
        # 한글의 CreatePageImage는 형식 인자와 무관하게 BMP를 만든다 → PNG로 바꾼다.
        pngs = []
        for f in map(Path, files):
            png = out_dir / (f.stem + ".png")
            with Image.open(f) as im:
                im.save(png)
            pngs.append(png)
    return pngs


def new_blank(dst) -> Path:
    """한글 기본 서식의 빈 문서를 HWPX로 만든다 (fixture 생성용)."""
    dst = Path(dst)
    with _workdir() as work:
        out = work / "blank.hwpx"
        _run("blank", work, dst=out)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dst)
    return dst
