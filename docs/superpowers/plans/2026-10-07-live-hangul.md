# 열린 한글 창 실시간 연동(live) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 열어 둔 한글 창의 문서를 Claude가 저장 없이 그 자리에서 읽고(선택·문맥·내보내기), 고치고(선택 바꾸기·커서 뒤 끼워 넣기·장 다시 쓰기), 검토 결과를 한글 메모로 다는 `hwpx.py live …` 명령을 만든다.

**Architecture:** `hwpxkit/live_hwp.ps1`이 실행 중 개체 목록(ROT)의 `!HwpObject`로 사용자 한글에 붙어 동작 하나를 하고 JSON 한 줄을 돌려준다(인자는 JSON 파일로 받음). `hwpxkit/live.py`가 그 스크립트를 부르고, 화면 속 문서를 `GetTextFile("HWP")`로 내보내 기존 엔진(`samples`·`render`·`review`)으로 조각을 만들거나 검토한 뒤, 조각은 `InsertFile`로 끼워 넣는다. CLI `live` 하위 명령과 스킬 안내를 더한다.

**Tech Stack:** Python 3.10+, lxml, Pillow, PowerShell 5.1, 한글 2024 COM(HWPFrame.HwpObject), pytest

**Spec:** `docs/superpowers/specs/2026-10-07-live-hangul-design.md`

## Global Constraints

- 사용자 한글 창의 문서를 절대 저장하지 않는다(`Save`·`SaveAs` 호출 금지). 내보내기는 `GetTextFile("HWP", "")`만 쓴다.
- 사용자 창·문서를 닫지 않는다. 테스트가 연 시험 문서만 닫는다.
- 모든 사용자 메시지는 한국어, 쉬운 말.
- 원문에 없는 수치·사실을 넣지 않는다(스킬 지침).
- 한글이 없는 환경에서는 `BridgeError("한글(한컴오피스)이 설치된 Windows에서만 할 수 있는 작업이에요.")`와 같은 문구 체계를 쓴다.
- 새 파이썬 의존성 없음.
- 한글 실제 테스트는 `@pytest.mark.hangul`(한글 없으면 자동 건너뜀).

## Review Focus

1. 한글이 열려 있지 않거나 문서가 하나도 없을 때 — "한글에서 문서를 연 뒤 다시 말씀해 주세요." 로 끝나야 하고 새 한글을 띄우면 안 된다. → Task 1 `test_status_not_running_message`
2. 문서가 여러 개 열려 있는데 `--doc`이 여러 문서에 걸리거나 아무것도 안 걸릴 때 — 후보 목록과 함께 멈춘다. → Task 1 `test_doc_ambiguous_message`, `test_doc_not_found_message`
3. 선택 없이 `replace`를 부를 때 — "한글에서 고칠 부분을 드래그해 주세요."로 멈추고 문서를 바꾸지 않는다. → Task 2 `test_replace_without_selection_refuses`
4. 메모 위치 글자를 문서에서 못 찾을 때 — 못 단 항목을 알려 주고 나머지는 단다. → Task 3 `test_memo_reports_missed_anchors`
5. `live section`의 제목이 차례(목차)에도 있어 여러 번 나올 때 — 본문 쪽 제목(마지막 등장이 아니라 차례 줄이 아닌 등장)을 고른다. → Task 4 `test_section_skips_toc_line`

---

### Task 1: 연결·상태·선택·내보내기

**Files:**
- Create: `hwpxkit/live_hwp.ps1`, `hwpxkit/live.py`, `tests/test_live.py`
- Modify: `tests/conftest.py` (시험용 한글 문서 fixture)

**Interfaces:**
- Produces:
  - `live.LiveError(BridgeError)` — 사용자용 한국어 메시지
  - `live.call(action: str, **params) -> dict` — ps1 실행, `ok`가 아니면 `LiveError`
  - `live.status(doc: str | None = None) -> dict` — `{"docs": [str], "active": str, "modified": bool, "selection": bool}`
  - `live.selection(doc=None) -> dict` — `{"selected": bool, "text": str, "para": int, "in_table": bool, "paragraphs": int}`
  - `live.export(out: Path, doc=None) -> Path` — 화면 속 문서를 .hwpx로
  - `live.hwp_exe() -> Path` — Hwp.exe 경로(레지스트리)
  - 내부 `live._runner` — 테스트에서 바꿔 끼우는 실행기 (`subprocess.run` 호환)

- [ ] **Step 1: 실패하는 테스트 작성 (가짜 실행기)**

`tests/test_live.py`:
```python
import json
import subprocess
from pathlib import Path

import pytest

from hwpxkit import bridge, live


class FakeRunner:
    """ps1 대신 정해 둔 JSON을 돌려주고, 받은 인자를 기록한다."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd, capture_output=True, timeout=None):
        args = json.loads(Path(cmd[cmd.index("-ArgsFile") + 1]).read_text(encoding="utf-8"))
        self.calls.append(args)
        out = json.dumps(self.results.pop(0), ensure_ascii=False).encode("utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=b"")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: True)

    def install(*results):
        runner = FakeRunner(*results)
        monkeypatch.setattr(live, "_runner", runner)
        return runner
    return install


def test_status_passes_action_and_doc(fake):
    r = fake({"ok": True, "docs": ["C:/a/보고서.hwp"], "active": "C:/a/보고서.hwp", "modified": True,
              "selection": False})
    st = live.status(doc="보고서")
    assert r.calls[0]["action"] == "status" and r.calls[0]["doc"] == "보고서"
    assert st["active"].endswith("보고서.hwp") and st["modified"] is True


def test_status_not_running_message(fake):
    fake({"ok": False, "error": "not_running"})
    with pytest.raises(live.LiveError, match="한글에서 문서를 연 뒤"):
        live.status()


def test_doc_ambiguous_message(fake):
    fake({"ok": False, "error": "doc_ambiguous", "docs": ["C:/a/보고서1.hwp", "C:/a/보고서2.hwp"]})
    with pytest.raises(live.LiveError, match="보고서1.hwp.*보고서2.hwp"):
        live.status(doc="보고서")


def test_doc_not_found_message(fake):
    fake({"ok": False, "error": "doc_not_found", "docs": ["C:/a/계획서.hwp"]})
    with pytest.raises(live.LiveError, match="열린 문서: 계획서.hwp"):
        live.status(doc="보고서")


def test_selection_counts_paragraphs(fake):
    fake({"ok": True, "selected": True, "text": "첫 줄\r\n둘째 줄\r\n", "para": 7, "in_table": False})
    sel = live.selection()
    assert sel["paragraphs"] == 2 and sel["text"] == "첫 줄\n둘째 줄"


def test_no_hangul_environment(monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: False)
    with pytest.raises(bridge.BridgeError, match="Windows에서만"):
        live.status()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_live.py -q`
Expected: FAIL — `ImportError: cannot import name 'live'`

- [ ] **Step 3: ps1 작성**

`hwpxkit/live_hwp.ps1`:
```powershell
# 사용자가 열어 둔 한글에 붙어 동작 하나를 하고 JSON 한 줄을 출력한다. 절대 저장하지 않는다.
param([Parameter(Mandatory = $true)][string]$ArgsFile)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Emit($obj) { [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress -Depth 6)) }

Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Runtime.InteropServices.ComTypes;
public static class HwpRot {
  [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int r, out IRunningObjectTable t);
  [DllImport("ole32.dll")] static extern int CreateBindCtx(int r, out IBindCtx c);
  public static List<object> All() {
    var res = new List<object>(); IRunningObjectTable rot; GetRunningObjectTable(0, out rot);
    IEnumMoniker en; rot.EnumRunning(out en); var m = new IMoniker[1]; IBindCtx ctx; CreateBindCtx(0, out ctx);
    while (en.Next(1, m, IntPtr.Zero) == 0) { string n; m[0].GetDisplayName(ctx, null, out n);
      if (n.StartsWith("!HwpObject")) { object o; rot.GetObject(m[0], out o); res.Add(o); } }
    return res; } }
'@

$a = Get-Content -Raw -Encoding UTF8 $ArgsFile | ConvertFrom-Json
$all = [HwpRot]::All()
if ($all.Count -eq 0) { Emit @{ ok = $false; error = "not_running" }; exit 0 }
$h = $all[0]
$docs = @(); for ($i = 0; $i -lt $h.XHwpDocuments.Count; $i++) { $docs += [string]$h.XHwpDocuments.Item($i).FullName }
if ($docs.Count -eq 0) { Emit @{ ok = $false; error = "not_running" }; exit 0 }

if ($a.doc) {
  $hit = @(); for ($i = 0; $i -lt $docs.Count; $i++) { if ($docs[$i] -like "*$($a.doc)*") { $hit += $i } }
  if ($hit.Count -eq 0) { Emit @{ ok = $false; error = "doc_not_found"; docs = $docs }; exit 0 }
  if ($hit.Count -gt 1) { Emit @{ ok = $false; error = "doc_ambiguous"; docs = @($hit | ForEach-Object { $docs[$_] }) }; exit 0 }
  $null = $h.XHwpDocuments.Item($hit[0]).SetActive_XHwpDocument()
}

function Find-Text($text, $times) {
  $set = $h.HParameterSet.HFindReplace
  $null = $h.HAction.GetDefault("RepeatFind", $set.HSet)
  $set.FindString = $text; $set.Direction = 0; $set.IgnoreMessage = 1
  for ($k = 0; $k -lt $times; $k++) { if (-not $h.HAction.Execute("RepeatFind", $set.HSet)) { return $false } }
  return $true
}

try {
  switch ($a.action) {
    "status" {
      Emit @{ ok = $true; docs = $docs; active = [string]$h.Path; modified = [bool]$h.IsModified;
              selection = ($h.SelectionMode -ne 0) }
    }
    "selection" {
      if ($h.SelectionMode -eq 0) { Emit @{ ok = $true; selected = $false }; break }
      $pos = $h.GetPosBySet()
      $inTable = $false; try { $inTable = ($h.ParentCtrl.CtrlID -eq "tbl") } catch {}
      Emit @{ ok = $true; selected = $true; text = [string]$h.GetTextFile("TEXT", "saveblock");
              para = [int]$pos.Item("Para"); list = [int]$pos.Item("List"); in_table = $inTable }
    }
    "export" {
      $b64 = $h.GetTextFile("HWP", "")
      [System.IO.File]::WriteAllBytes($a.out, [Convert]::FromBase64String($b64))
      Emit @{ ok = $true; out = $a.out }
    }
    default { Emit @{ ok = $false; error = "unknown_action" } }
  }
} catch { Emit @{ ok = $false; error = $_.Exception.Message } }
```

- [ ] **Step 4: live.py 작성**

`hwpxkit/live.py`:
```python
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
```

- [ ] **Step 5: 가짜 실행기 테스트 통과 확인**

Run: `python -m pytest tests/test_live.py -q`
Expected: 6 passed

- [ ] **Step 6: 한글 실제 테스트 fixture와 테스트 추가**

`tests/conftest.py` 끝에 추가:
```python
@pytest.fixture
def live_doc(tmp_path_factory):
    """사람이 연 것처럼 시험 문서를 한글로 연다(문서 이름 고유). 끝나면 그 문서만 닫는다."""
    import subprocess as sp
    import time
    from hwpxkit import live
    from hwpxkit.presets import path as preset_path
    folder = tmp_path_factory.mktemp("live")
    name = f"livetest_{int(time.time() * 1000)}.hwpx"
    doc = folder / name
    shutil.copyfile(preset_path("gov-brief"), doc)
    sp.Popen([str(live.hwp_exe()), str(doc)])
    for _ in range(40):
        time.sleep(0.5)
        try:
            if any(name in d for d in live.status()["docs"]):
                break
        except live.LiveError:
            pass
    yield name, doc
    try:
        live.call("close_doc", doc=name)
    except live.LiveError:
        pass
```

`live_hwp.ps1`의 `switch`에 시험 정리용 동작 추가(`default` 앞):
```powershell
    "close_doc" {
      # 시험 정리용: --doc으로 고른 시험 문서만 저장하지 않고 닫는다. 남은 문서가 없으면 한글을 끈다.
      $null = $h.XHwpDocuments.Active_XHwpDocument.Close($false)
      if ($h.XHwpDocuments.Count -eq 1 -and -not [string]$h.XHwpDocuments.Item(0).FullName) { $null = $h.Quit() }
      Emit @{ ok = $true }
    }
```

`tests/test_live.py` 끝에 추가:
```python
@pytest.mark.hangul
def test_live_status_selection_export(live_doc, tmp_path):
    from hwpxkit.package import Package
    from hwpxkit.reader import to_markdown
    name, _ = live_doc
    st = live.status(doc=name)
    assert st["active"].endswith(name)
    live.call("select_test", doc=name, para=1, start=0, end=4)
    sel = live.selection(doc=name)
    assert sel["selected"] and sel["paragraphs"] == 1 and len(sel["text"]) == 4
    out = live.export(tmp_path / "screen.hwpx", doc=name)
    assert "견본" in to_markdown(Package.open(out))
    assert live.status(doc=name)["active"].endswith(name)  # 내보내기 뒤에도 창의 문서 경로 그대로
```

`live_hwp.ps1`의 `switch`에 시험용 선택 동작 추가:
```powershell
    "select_test" {
      # 시험용: 사람이 드래그한 것처럼 para 문단의 start~end 글자를 선택한다.
      $null = $h.SetPos(0, [int]$a.para, 0)
      Emit @{ ok = [bool]$h.SelectText([int]$a.para, [int]$a.start, [int]$a.para, [int]$a.end) }
    }
```

- [ ] **Step 7: 한글 실제 테스트 확인**

Run: `python -m pytest tests/test_live.py -q`
Expected: 7 passed (한글 없는 PC는 1 skipped)

- [ ] **Step 8: Commit**

```bash
git add hwpxkit/live.py hwpxkit/live_hwp.ps1 tests/test_live.py tests/conftest.py
git commit -m "feat: 열린 한글 창 연결 — 상태·선택·화면 속 문서 내보내기 (live)"
```

---

### Task 2: 선택 바꾸기·커서 뒤 끼워 넣기

**Files:**
- Modify: `hwpxkit/live_hwp.ps1`, `hwpxkit/live.py`, `hwpxkit/render.py` (`render_into(..., number_from=None)`)
- Test: `tests/test_live.py`, `tests/test_captions.py`

**Interfaces:**
- Consumes: `live.call`, `live.selection`, `live.export` (Task 1)
- Produces:
  - `render.render_into(pkg, catalog, md, *, mode="new", replace=None, base_dir=Path("."), section=None, number_from: dict[str, int] | None = None) -> list[str]` — `number_from={"tbl": n, "fig": n}`이면 그 수 다음부터 번호를 매긴다(넣을 자리 앞 캡션 수)
  - `live.fragment(md: str, screen: Path, *, base_dir: Path, before_para: int | None) -> Path` — 화면 문서 견본으로 조각 .hwpx 생성, 경고는 `live.last_warnings`
  - `live.replace(md: str, doc=None, base_dir=Path(".")) -> dict` — `{"mode": "text"|"fragment", "warnings": [...]}`
  - `live.insert(md: str, doc=None, base_dir=Path(".")) -> dict` — `{"warnings": [...]}`

- [ ] **Step 1: render_into number_from 실패 테스트**

`tests/test_captions.py` 끝에 추가:
```python
def test_number_from_continues_numbers(blank):
    """끼워 넣을 자리 앞에 캡션 표가 2개 있으면 새 표는 3번, 본문 참조도 3번."""
    pkg = plain(blank)
    render_into(pkg, infer(pkg), TABLE_MD, number_from={"tbl": 2, "fig": 0})
    assert next(pkg.xml(SECTION).iter(q("hp:autoNum"))).get("num") == "3"
    assert any("[표 3]에 정리했다" in own_text(p) for p in tops(pkg))
```

Run: `python -m pytest tests/test_captions.py -k number_from -q`
Expected: FAIL — `TypeError: render_into() got an unexpected keyword argument 'number_from'`

- [ ] **Step 2: render_into에 number_from 추가**

`hwpxkit/render.py`의 `render_into` 서명에 `number_from: dict[str, int] | None = None`을 더하고, Renderer를 만드는 줄을 바꾼다:
```python
    start = number_from if number_from is not None else _caption_counts(before)
    r = Renderer(pkg, catalog, base_dir=base_dir, start=start)
```

Run: `python -m pytest tests/test_captions.py -q`
Expected: all passed

- [ ] **Step 3: live 바꾸기·끼워 넣기 실패 테스트 (가짜 실행기)**

`tests/test_live.py` 끝에 추가:
```python
def test_replace_without_selection_refuses(fake):
    r = fake({"ok": True, "selected": False})
    with pytest.raises(live.LiveError, match="드래그해 주세요"):
        live.replace("새 문장")
    assert [c["action"] for c in r.calls] == ["selection"]  # 바꾸기 동작은 부르지 않음


def test_replace_single_paragraph_uses_text(fake):
    r = fake({"ok": True, "selected": True, "text": "옛 문장", "para": 3, "in_table": False},
             {"ok": True})
    result = live.replace("새 **문장**")
    assert result["mode"] == "text"
    assert r.calls[1]["action"] == "replace_text"
    assert Path(r.calls[1]["text_file"]).name.endswith(".txt")


def test_markdown_block_needs_fragment():
    assert live._needs_fragment("○ 개조식 줄", 1)
    assert live._needs_fragment("| a | b |\n|---|---|\n| 1 | 2 |", 1)
    assert live._needs_fragment("첫 줄\n둘째 줄", 1)
    assert live._needs_fragment("한 줄", 2)
    assert not live._needs_fragment("그냥 한 문장", 1)
```

Run: `python -m pytest tests/test_live.py -q`
Expected: FAIL — `AttributeError: module 'hwpxkit.live' has no attribute 'replace'`

- [ ] **Step 4: ps1 동작 추가**

`live_hwp.ps1`의 `switch`에 추가:
```powershell
    "replace_text" {
      if ($h.SelectionMode -eq 0) { Emit @{ ok = $false; error = "no_selection" }; break }
      $set = $h.HParameterSet.HInsertText
      $null = $h.HAction.GetDefault("InsertText", $set.HSet)
      $set.Text = [System.IO.File]::ReadAllText($a.text_file, [System.Text.Encoding]::UTF8)
      Emit @{ ok = [bool]$h.HAction.Execute("InsertText", $set.HSet) }
    }
    "insert_file" {
      # replace_selection이면 선택을 지우고 그 자리에, 아니면 커서가 있는 문단 다음에 새 문단을 만들어 넣는다.
      if ($a.replace_selection) {
        if ($h.SelectionMode -eq 0) { Emit @{ ok = $false; error = "no_selection" }; break }
        $null = $h.HAction.Run("Delete")
      } else {
        $null = $h.HAction.Run("MoveParaEnd")
      }
      $null = $h.HAction.Run("BreakPara")
      $set = $h.HParameterSet.HInsertFile
      $null = $h.HAction.GetDefault("InsertFile", $set.HSet)
      $set.FileName = $a.file; $set.FileFormat = "HWPX"
      $set.KeepSection = 0; $set.KeepCharshape = 1; $set.KeepParashape = 1; $set.KeepStyle = 1
      Emit @{ ok = [bool]$h.HAction.Execute("InsertFile", $set.HSet) }
    }
    "captions_before" {
      # 커서 문단 앞에 있는 캡션 달린 표·그림 수 (번호를 이어 매기기 위해)
      $pos = $h.GetPosBySet(); Emit @{ ok = $true; para = [int]$pos.Item("Para") }
    }
```

- [ ] **Step 5: live.py에 바꾸기·끼워 넣기 추가**

`hwpxkit/live.py` 끝에 추가:
```python
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
```

Run: `python -m pytest tests/test_live.py -q`
Expected: all passed (hangul 표시 제외 시 skipped 포함)

- [ ] **Step 6: 한글 실제 테스트**

`tests/test_live.py` 끝에 추가:
```python
@pytest.mark.hangul
def test_live_replace_and_insert_keep_format(live_doc, tmp_path):
    from hwpxkit.body import all_text, own_text
    from hwpxkit.header import Header
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    name, _ = live_doc
    live.call("select_test", doc=name, para=1, start=0, end=2)
    assert live.replace("바뀐 글", doc=name)["mode"] == "text"
    live.insert("□ 끼워 넣은 항목\n○ 세부 내용\n\n표: 끼워 넣은 표\n| 구분 | 값 |\n|---|---|\n| 가 | 1 |\n", doc=name)
    pkg = Package.open(live.export(tmp_path / "after.hwpx", doc=name))
    texts = [own_text(p) for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p")]
    assert any("바뀐 글" in t for t in texts)
    assert any(t.endswith("끼워 넣은 항목") for t in texts)
    caps = [all_text(c) for c in pkg.xml(pkg.section_names()[0]).iter(q("hp:caption"))]
    assert any("끼워 넣은 표" in c for c in caps)
    h = Header(pkg)
    faces = {h.charpr_faces(r.get("charPrIDRef"))["HANGUL"]
             for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p") and "끼워 넣은 항목" in own_text(p)
             for r in p.findall(q("hp:run")) if r.find(q("hp:t")) is not None}
    assert faces == {"휴먼명조"}  # gov-brief 글머리 글꼴 그대로
```

Run: `python -m pytest tests/test_live.py -q`
Expected: all passed. 끼워 넣은 뒤 빈 문단이 하나 더 생기면(BreakPara 때문) 허용하되, 다음 문단이 끼워 넣은 내용과 합쳐지면 안 된다 — 합쳐지면 Ruling으로 `BreakPara` 위치를 조정한다.

- [ ] **Step 7: Commit**

```bash
git add hwpxkit/live.py hwpxkit/live_hwp.ps1 hwpxkit/render.py tests/test_live.py tests/test_captions.py
git commit -m "feat: 열린 한글에서 선택 바꾸기·커서 뒤 끼워 넣기 (서식은 화면 문서 견본)"
```

---

### Task 3: 검토 결과를 한글 메모로

**Files:**
- Modify: `hwpxkit/review.py` (`Finding.anchor`), `hwpxkit/live_hwp.ps1`, `hwpxkit/live.py`
- Test: `tests/test_review.py`, `tests/test_live.py`

**Interfaces:**
- Produces:
  - `review.Finding(level, code, message, anchor="")` — `anchor`는 문서 안에서 그대로 찾을 수 있는 글(비교에서 제외, `field(default="", compare=False)`)
  - `live.review(doc=None, memo=False) -> dict` — `{"findings": [Finding], "placed": int, "missed": [str]}`

- [ ] **Step 1: anchor 실패 테스트**

`tests/test_review.py` 끝에 추가:
```python
def test_findings_carry_anchor_text(blank):
    from helpers import LONG, append_to_body, para
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("보고일: 2026.05.06.(목)"))
    append_to_body(pkg, para("※ 추가적으로 기술할 내용은 자유롭게 작성 가능"))
    found = {f.code: f.anchor for f in review(pkg)}
    assert found["weekday"] == "2026.05.06.(목)"
    assert found["guide-text"].startswith("※ 추가적으로")
```

Run: `python -m pytest tests/test_review.py -k anchor -q`
Expected: FAIL — `AttributeError: 'Finding' object has no attribute 'anchor'`

- [ ] **Step 2: Finding.anchor 추가와 검사별 anchor 채우기**

`hwpxkit/review.py`:
```python
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Finding:
    level: str  # "오류" | "확인"
    code: str
    message: str
    anchor: str = field(default="", compare=False)  # 문서에서 그대로 찾을 수 있는 글 (한글 메모 위치)
```
그리고 각 검사에서 anchor를 넣는다:
- `_check_dates`: `Finding("오류", "bad-date", …, anchor=m.group(0).strip())`, `weekday`·보고일 연도 검사도 `anchor=m.group(0).strip()`
- `_check_guide_text`: `anchor=text[:30]` (공백 정리 전 `own_text(p).strip()[:30]` — 문서 글 그대로)
- `_check_numbering`의 `bad-ref`: `anchor=m.group(0)`, `caption-dup`·`caption-gap`: `anchor=label`
- `_check_fonts`의 `font-mix`: `anchor=sample[face]`
- `_check_cells`의 `placeholder`: `anchor=text`, `empty-cell`: `anchor=c.row_header` (빈 칸 대신 같은 행 머리 칸에 단다)

Run: `python -m pytest tests/test_review.py -q`
Expected: all passed

- [ ] **Step 3: 메모 실패 테스트 (가짜 실행기)**

`tests/test_live.py` 끝에 추가:
```python
def test_memo_reports_missed_anchors(fake, monkeypatch, tmp_path):
    from hwpxkit import review as rv
    monkeypatch.setattr(live, "export", lambda out, doc=None: Path(out))
    monkeypatch.setattr(live, "_review_file", lambda path: [
        rv.Finding("오류", "weekday", "요일이 틀려요", anchor="2026.05.06.(목)"),
        rv.Finding("확인", "font-mix", "글꼴 섞임", anchor=""),
        rv.Finding("확인", "guide-text", "안내 문구", anchor="없는 글")])
    r = fake({"ok": True, "placed": 1, "missed": ["없는 글"]})
    result = live.review(memo=True)
    memos = r.calls[0]["memos"]
    assert [m["anchor"] for m in memos] == ["2026.05.06.(목)", "없는 글"]  # anchor 없는 항목은 메모로 안 단다
    assert memos[0]["text"].startswith("[검토] ")
    assert result["placed"] == 1 and result["missed"] == ["없는 글"]
```

Run: `python -m pytest tests/test_live.py -k memo -q`
Expected: FAIL — `AttributeError: module 'hwpxkit.live' has no attribute 'review'`

- [ ] **Step 4: ps1 메모 동작과 live.review**

`live_hwp.ps1` `switch`에 추가:
```powershell
    "memos" {
      $saved = $h.GetPosBySet(); $placed = 0; $missed = @()
      foreach ($m in $a.memos) {
        $null = $h.MovePos(2, 0, 0)
        if (Find-Text $m.anchor 1) {
          $null = $h.HAction.Run("InsertFieldMemo")
          $set = $h.HParameterSet.HInsertText
          $null = $h.HAction.GetDefault("InsertText", $set.HSet); $set.Text = $m.text
          $null = $h.HAction.Execute("InsertText", $set.HSet)
          $null = $h.HAction.Run("CloseEx")
          $placed++
        } else { $missed += $m.anchor }
      }
      $null = $h.HAction.Run("Cancel"); $null = $h.SetPosBySet($saved)
      Emit @{ ok = $true; placed = $placed; missed = $missed }
    }
```

`hwpxkit/live.py` 끝에 추가:
```python
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
```

Run: `python -m pytest tests/test_live.py -q`
Expected: all passed

- [ ] **Step 5: 한글 실제 테스트**

`tests/test_live.py` 끝에 추가:
```python
@pytest.mark.hangul
def test_live_review_places_memo(live_doc, tmp_path):
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    name, _ = live_doc
    live.call("select_test", doc=name, para=1, start=0, end=0)
    live.insert("보고일: 2026.05.06.(목)\n", doc=name)
    result = live.review(doc=name, memo=True)
    assert result["placed"] >= 1
    pkg = Package.open(live.export(tmp_path / "memo.hwpx", doc=name))
    memos = [fb for fb in pkg.xml(pkg.section_names()[0]).iter(q("hp:fieldBegin")) if fb.get("type") == "MEMO"]
    assert any("요일" in "".join(t.text or "" for t in fb.iter(q("hp:t"))) for fb in memos)
```

Run: `python -m pytest tests/test_live.py -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add hwpxkit/review.py hwpxkit/live.py hwpxkit/live_hwp.ps1 tests/test_review.py tests/test_live.py
git commit -m "feat: 열린 문서 검토 결과를 해당 자리에 한글 메모로 (live review --memo)"
```

---

### Task 4: 장 다시 쓰기 (live section)

**Files:**
- Modify: `hwpxkit/live_hwp.ps1`, `hwpxkit/live.py`
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: `samples.heading_levels`, `samples.classify`, `samples.bullet_chars`, `header.Header`, `body.own_text`
- Produces:
  - `live.section_bounds(screen: Path, heading: str) -> tuple[str, int, str | None, int]` — (시작 제목 글, 시작 등장 순번(1부터), 다음 같은 단계 제목 글 또는 None, 그 등장 순번)
  - `live.section(heading: str, md: str, doc=None, base_dir=Path(".")) -> dict` — `{"start": str, "end": str | None, "warnings": [...]}`

- [ ] **Step 1: 범위 계산 실패 테스트 (파일)**

`tests/test_live.py` 끝에 추가:
```python
def make_report(blank, tmp_path):
    from helpers import LONG, append_to_body, para
    from hwpxkit.header import Header
    from hwpxkit.package import Package
    pkg = Package.open(blank)
    big = Header(pkg).derive_charpr("0", height=1600, bold=True)
    for text, cp in (("제1장 서론", big), (LONG, "0"), ("제2장 방법", big), (LONG, "0"), (LONG, "0"),
                     ("제3장 결과", big), (LONG, "0")):
        append_to_body(pkg, para(text, char_pr=cp))
    return pkg.save(tmp_path / "r.hwpx")


def test_section_bounds_to_next_same_level(blank, tmp_path):
    start, n1, end, n2 = live.section_bounds(make_report(blank, tmp_path), "제2장")
    assert (start, n1, end, n2) == ("제2장 방법", 1, "제3장 결과", 1)


def test_section_bounds_last_chapter_runs_to_end(blank, tmp_path):
    assert live.section_bounds(make_report(blank, tmp_path), "제3장")[2] is None


def test_section_skips_toc_line(blank, tmp_path):
    """차례에 '제2장 방법 ···· 3'이 먼저 나와도 본문 제목을 고르고, 찾기 순번은 2번째 등장."""
    from helpers import append_to_body, para
    from hwpxkit.package import Package
    path = make_report(blank, tmp_path)
    pkg = Package.open(path)
    sec = pkg.edit(pkg.section_names()[0])
    toc = para("제2장 방법 ········ 3")
    sec.insert(1, toc)
    path2 = pkg.save(tmp_path / "toc.hwpx")
    start, n1, end, n2 = live.section_bounds(path2, "제2장")
    assert (start, n1) == ("제2장 방법", 2)


def test_section_unknown_heading(blank, tmp_path):
    with pytest.raises(live.LiveError, match="제목을 찾지 못했어요"):
        live.section_bounds(make_report(blank, tmp_path), "제9장")
```

Run: `python -m pytest tests/test_live.py -k section -q`
Expected: FAIL — `AttributeError: ... 'section_bounds'`

- [ ] **Step 2: section_bounds 구현**

`hwpxkit/live.py` 끝에 추가:
```python
from .body import own_text  # noqa: E402
from .header import Header  # noqa: E402
from .samples import bullet_chars, classify, heading_levels  # noqa: E402


def section_bounds(screen: Path, heading: str) -> tuple[str, int, str | None, int]:
    """heading으로 시작하는 본문 제목부터 같은 단계의 다음 제목 앞까지. 한글 찾기용으로 (글, 등장 순번)을 돌려준다."""
    pkg = Package.open(screen)
    h = Header(pkg)
    chars = bullet_chars(h)
    tops = [p for p in pkg.xml(pkg.section_names()[0]) if p.tag.endswith("}p")]
    levels = heading_levels(tops)
    roles = [classify(p, h, chars, levels)[0] for p in tops]
    texts = [own_text(p).strip() for p in tops]
    start = next((i for i, (t, r) in enumerate(zip(texts, roles))
                  if t.startswith(heading) and r and (r.startswith("h") or r == "bullet1")), None)
    if start is None:
        raise LiveError(f"'{heading}' 제목을 찾지 못했어요. 한글 화면의 제목 글자 그대로 알려 주세요.")
    role = roles[start]
    end = next((i for i in range(start + 1, len(tops)) if roles[i] == role), None)

    def occurrence(i: int) -> int:  # 한글 찾기는 문서 앞에서부터 같은 글을 센다(차례 줄 포함)
        return sum(1 for t in texts[:i + 1] if texts[i] in t)

    return (texts[start], occurrence(start),
            texts[end] if end is not None else None, occurrence(end) if end is not None else 0)
```

Run: `python -m pytest tests/test_live.py -k section -q`
Expected: 4 passed

- [ ] **Step 3: ps1 범위 바꾸기 동작**

`live_hwp.ps1` `switch`에 추가:
```powershell
    "replace_between" {
      $null = $h.MovePos(2, 0, 0)
      if (-not (Find-Text $a.start $a.start_n)) { Emit @{ ok = $false; error = "start_not_found" }; break }
      $null = $h.HAction.Run("Cancel"); $null = $h.HAction.Run("MoveParaBegin"); $s = $h.GetPosBySet()
      if ($a.end) {
        $null = $h.MovePos(2, 0, 0)
        if (-not (Find-Text $a.end $a.end_n)) { Emit @{ ok = $false; error = "end_not_found" }; break }
        $null = $h.HAction.Run("Cancel"); $null = $h.HAction.Run("MoveParaBegin"); $e = $h.GetPosBySet()
      } else { $null = $h.MovePos(3, 0, 0); $e = $h.GetPosBySet() }
      $null = $h.SelectText([int]$s.Item("Para"), 0, [int]$e.Item("Para"), [int]$e.Item("Pos"))
      $null = $h.HAction.Run("Delete")
      $set = $h.HParameterSet.HInsertFile
      $null = $h.HAction.GetDefault("InsertFile", $set.HSet)
      $set.FileName = $a.file; $set.FileFormat = "HWPX"
      $set.KeepSection = 0; $set.KeepCharshape = 1; $set.KeepParashape = 1; $set.KeepStyle = 1
      Emit @{ ok = [bool]$h.HAction.Execute("InsertFile", $set.HSet) }
    }
```

`_ERRORS`에 추가:
```python
    "start_not_found": "한글 화면에서 그 제목을 찾지 못했어요. 문서가 바뀌었으면 다시 말씀해 주세요.",
    "end_not_found": "한글 화면에서 다음 제목을 찾지 못했어요. 문서가 바뀌었으면 다시 말씀해 주세요.",
```

`hwpxkit/live.py` 끝에 추가:
```python
def section(heading: str, md: str, doc: str | None = None, base_dir: Path = Path(".")) -> dict:
    with tempfile.TemporaryDirectory(prefix="hl") as tmp:
        screen = export(Path(tmp) / "screen.hwpx", doc)
        start, n1, end, n2 = section_bounds(screen, heading)
        tops_before = next(i for i, p in enumerate(
            [p for p in Package.open(screen).xml(Package.open(screen).section_names()[0]) if p.tag.endswith("}p")])
            if own_text(p).strip() == start)
        frag = fragment(md, screen, base_dir=base_dir, before_para=tops_before)
        call("replace_between", doc=doc, start=start, start_n=n1, end=end or "", end_n=n2, file=str(frag))
    return {"start": start, "end": end, "warnings": list(last_warnings)}
```

- [ ] **Step 4: 한글 실제 테스트**

`tests/test_live.py` 끝에 추가:
```python
@pytest.mark.hangul
def test_live_section_rewrite(live_doc, tmp_path):
    from hwpxkit.package import Package
    from hwpxkit.reader import to_markdown
    name, _ = live_doc
    before = to_markdown(Package.open(live.export(tmp_path / "b.hwpx", doc=name)))
    first = next(ln for ln in before.splitlines() if ln.startswith("# "))[2:]
    live.section(first.split()[0], f"# {first}\n\n□ 새로 쓴 장 내용\n○ 세부\n", doc=name)
    after = to_markdown(Package.open(live.export(tmp_path / "a.hwpx", doc=name)))
    assert "새로 쓴 장 내용" in after and after.count(first) == 1
```

Run: `python -m pytest tests/test_live.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/live.py hwpxkit/live_hwp.ps1 tests/test_live.py
git commit -m "feat: 열린 문서의 장 하나를 다시 쓴 내용으로 바꾸기 (live section)"
```

---

### Task 5: CLI·스킬·문서

**Files:**
- Modify: `hwpxkit/cli.py`, `skills/hwp-helper/SKILL.md`, `skills/hwp-helper/reference/troubleshooting.md`, `tests/test_plugin_files.py`, `README.md`, `.claude-plugin/plugin.json`
- Create: `skills/hwp-helper/reference/live.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `live.status/selection/replace/insert/export/review/section`
- Produces: `hwpx.py live {status,selection,replace,insert,export,review,section} [--doc 이름] [--json] [--memo]`

- [ ] **Step 1: CLI 실패 테스트**

`tests/test_cli.py` 끝에 추가:
```python
def test_live_status_cli(monkeypatch, capsys):
    from hwpxkit import live
    monkeypatch.setattr(live, "status", lambda doc=None: {
        "docs": ["C:/a/보고서.hwp"], "active": "C:/a/보고서.hwp", "modified": True, "selection": False})
    assert main(["live", "status"]) == 0
    out = capsys.readouterr().out
    assert "보고서.hwp" in out and "수정됨" in out


def test_live_replace_cli_reads_file(monkeypatch, tmp_path, capsys):
    from hwpxkit import live
    seen = {}
    monkeypatch.setattr(live, "replace", lambda md, doc=None, base_dir=None: seen.update(md=md) or {"mode": "text", "warnings": []})
    f = tmp_path / "new.md"
    f.write_text("새 문장", encoding="utf-8")
    assert main(["live", "replace", str(f)]) == 0
    assert seen["md"] == "새 문장" and "바꿨어요" in capsys.readouterr().out


def test_live_error_is_user_error(monkeypatch, capsys):
    from hwpxkit import live
    def boom(doc=None):
        raise live.LiveError("한글에서 문서를 연 뒤 다시 말씀해 주세요.")
    monkeypatch.setattr(live, "status", boom)
    assert main(["live", "status"]) == 2
    assert "한글에서 문서를 연 뒤" in capsys.readouterr().err
```

Run: `python -m pytest tests/test_cli.py -k live -q`
Expected: FAIL — argparse `invalid choice: 'live'` (exit 2 → assert 0 실패)

- [ ] **Step 2: CLI 구현**

`hwpxkit/cli.py`에 추가(`_parser`의 `presets` 뒤, 함수는 `_cmd_presets` 근처):
```python
def _cmd_live(args, workdir) -> int:
    from . import live
    act, doc = args.live_action, args.doc
    if act == "status":
        st = live.status(doc)
        if args.json:
            print(json.dumps(st, ensure_ascii=False))
            return 0
        print(f"지금 문서: {Path(st['active']).name}" + (" (수정됨, 저장 안 함)" if st["modified"] else ""))
        if len(st["docs"]) > 1:
            print("열린 문서: " + ", ".join(Path(d).name for d in st["docs"]))
        print("선택한 부분: " + ("있음" if st["selection"] else "없음"))
        return 0
    if act == "selection":
        sel = live.selection(doc)
        if args.json:
            print(json.dumps(sel, ensure_ascii=False))
        elif not sel["selected"]:
            print("선택한 부분이 없어요.")
        else:
            where = "표 칸 안" if sel["in_table"] else "본문"
            print(f"[{where} · {sel['paragraphs']}문단 · {sel['para']}번째 문단]\n{sel['text']}")
        return 0
    if act == "export":
        print(f"내보냈어요(창은 그대로): {live.export(Path(args.target), doc)}")
        return 0
    if act == "review":
        r = live.review(doc, memo=args.memo)
        for f in r["findings"]:
            print(f"[{f.level}] {f.message}")
        if not r["findings"]:
            print("확인할 것이 없어요.")
        if args.memo:
            print(f"한글 메모 {r['placed']}개를 달았어요." + (f" 위치를 못 찾은 것: {', '.join(r['missed'])}" if r["missed"] else ""))
        return 0
    md_path = Path(args.target)
    if not md_path.is_file():
        raise PackageError(f"내용 파일을 찾을 수 없어요: {md_path}")
    md = md_path.read_text(encoding="utf-8-sig")
    if act == "replace":
        r = live.replace(md, doc, base_dir=md_path.parent)
        print("선택한 부분을 바꿨어요." + (" (여러 문단: 양식 서식으로)" if r["mode"] == "fragment" else ""))
    elif act == "insert":
        r = live.insert(md, doc, base_dir=md_path.parent)
        print("커서가 있는 문단 다음에 넣었어요.")
    else:  # section
        r = live.section(args.heading, md, doc, base_dir=md_path.parent)
        print(f"'{r['start']}' 장을 바꿨어요." + (f" ('{r['end']}' 앞까지)" if r["end"] else " (문서 끝까지)"))
    for w in r["warnings"]:
        print(f"[주의] {w}")
    print("저장은 하지 않았어요. 한글에서 확인 후 저장하거나, 되돌리기(Ctrl+Z)로 취소할 수 있어요.")
    return 0
```
`_parser`에 추가:
```python
    s = sub.add_parser("live", help="열린 한글 창의 문서를 저장 없이 읽고 고치기 (한글 필요)")
    s.add_argument("live_action", choices=["status", "selection", "replace", "insert", "export", "review", "section"])
    s.add_argument("target", nargs="?", default="", help="내용 .md (replace/insert/section) 또는 결과 .hwpx (export)")
    s.add_argument("--heading", default="", help="section: 바꿀 장의 제목 글 (예: 제2장)")
    s.add_argument("--doc", default=None, help="열린 문서가 여러 개일 때 문서 이름 일부")
    s.add_argument("--memo", action="store_true", help="review: 지적 사항을 한글 메모로 달기")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_live)
```

Run: `python -m pytest tests/test_cli.py -q`
Expected: all passed

- [ ] **Step 3: 스킬·참고 문서**

`skills/hwp-helper/reference/live.md` 생성:
````markdown
# 열린 한글 창에서 바로 고치기 (live)

사용자가 한글에서 열어 둔 문서를 저장 없이 그 자리에서 읽고 고친다. 한글이 설치된 Windows에서만 된다.

| 사용자가 말하면 | 명령 |
|---|---|
| 지금 열린 문서가 뭐야 | `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" live status` |
| 고른 부분 다듬어줘·줄여줘·늘려줘·개조식으로 | `live selection` → 새 글을 `.md`로 쓰고 `live replace <새글.md>` |
| 커서 있는 데 표·그림·글머리 넣어줘 | 내용을 `.md`로 쓰고 `live insert <내용.md>` (커서가 있는 문단 다음에 들어감) |
| 열린 문서 검토해줘 | `live review --memo` (지적 사항이 해당 자리 한글 메모로) |
| 2장만 다시 써줘 | `live export <화면.hwpx>` → `read`로 그 장을 읽고 새로 쓴 `.md`로 `live section <새장.md> --heading "제2장"` |
| 지금 화면 그대로 파일로 | `live export <결과.hwpx>` |

- 시작할 때 `live status`로 문서 이름과 "수정됨" 여부를 사용자에게 한 줄로 알린다. 문서가 여러 개면 `--doc 이름일부`.
- 바꾸기 전에 "바꿀 글 → 새 글"을 대화에 보여 준다. 한두 문장은 바로, 장 단위는 확인받고 한다.
- 다듬기·줄이기·늘리기에서 원문에 없는 수치·사실·고유명사를 넣지 않는다. 필요하면 `( )`로 비우고 알린다.
- 저장하지 않는다. 끝나면 "한글에서 확인 후 저장하거나 Ctrl+Z로 되돌릴 수 있어요"라고 알린다.
- 선택이 표 칸 안이면(`selection`의 `표 칸 안`) 한 문단 글 바꾸기만 한다.
````

`skills/hwp-helper/SKILL.md`의 `## 7. 전달` 앞에 절 추가:
```markdown
## 6-1. 열린 한글 창에서 바로 고치기

사용자가 "한글에서 고른 부분", "지금 열어 둔 문서", "커서 있는 데"처럼 열린 한글 창을 말하면 파일 대신 `live` 명령을 쓴다. 절차와 주의는 `reference/live.md`.
```

`skills/hwp-helper/reference/troubleshooting.md` 표에 줄 추가:
```markdown
| "한글에서 문서를 연 뒤 다시 말씀해 주세요" (live) | 한글이 안 열려 있거나 문서가 없음 | 사용자에게 한글에서 문서를 열어 달라고 요청 |
| "한글에서 고칠 부분을 드래그해 주세요" (live) | 선택 없이 바꾸기를 부름 | 사용자에게 고칠 부분을 드래그해 달라고 요청 |
```

`tests/test_plugin_files.py`의 허용 옵션 튜플에 `"--doc", "--memo", "--heading"`을 더한다.

`README.md` 엔진 명령 표에 줄 추가:
```markdown
| `live status·selection·replace·insert·export·review·section` | 열린 한글 창의 문서를 저장 없이 읽고 고치기, 검토 결과를 한글 메모로 | 예 |
```

`.claude-plugin/plugin.json`의 `version`을 `"0.2.0"`으로 올린다.

Run: `python -m pytest tests/test_plugin_files.py tests/test_skill_zip.py -q`
Expected: all passed

- [ ] **Step 4: 전체 테스트**

Run: `python -m pytest -q`
Expected: failed 0

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/cli.py skills README.md .claude-plugin/plugin.json tests/test_cli.py tests/test_plugin_files.py
git commit -m "feat: live 명령(열린 한글 창 편집)과 스킬 안내, 0.2.0"
```

---

### Task 6: 실제 사용 확인

**Files:** 없음 (확인만)

- [ ] **Step 1:** 시험 문서를 한글로 열고(사용자 문서와 별개) CLI로 차례대로 실행해 화면을 확인한다: `live status` → (사용자 대신 `select_test`로 선택) `live selection` → `live replace` → `live insert` → `live review --memo` → `live section` → 한글에서 Ctrl+Z 되돌리기. 각 단계 뒤 `live status`의 문서 경로가 그대로인지 본다.
- [ ] **Step 2:** 사용자에게 실제 창에서 한 번 해 보자고 요청한다(선택은 사용자가 드래그).
- [ ] **Step 3:** 발견한 문제는 Ruling 또는 수정 커밋으로 남긴다.
