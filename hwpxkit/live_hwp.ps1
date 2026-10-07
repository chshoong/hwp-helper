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
# 실행 중 개체 목록에는 사용자 한글 말고도 변환용 한글(창 없음)이 같은 이름으로 있을 수 있다.
# 창이 보이고 이름 있는 문서를 연 한글만 사용자 한글로 본다. --doc이 있으면 그 문서를 연 한글.
function DocsOf($x) { $d = @(); for ($i = 0; $i -lt $x.XHwpDocuments.Count; $i++) { $d += [string]$x.XHwpDocuments.Item($i).FullName }; return $d }
$cands = @()
foreach ($x in [HwpRot]::All()) {
  try {
    $visible = $false; try { $visible = [bool]$x.XHwpWindows.Item(0).Visible } catch {}
    $named = @(DocsOf $x | Where-Object { $_ })
    if ($visible -and $named.Count -gt 0) { $cands += $x }
  } catch {}
}
if ($a.doc) {
  $match = @($cands | Where-Object { @(DocsOf $_ | Where-Object { $_ -like "*$($a.doc)*" }).Count -gt 0 })
  if ($match.Count -gt 0) { $cands = $match }
}
if ($cands.Count -eq 0) {
  if ($a.action -eq "close_doc") { Emit @{ ok = $true; quit = $false }; exit 0 }
  Emit @{ ok = $false; error = "not_running" }; exit 0
}
$h = $cands[0]
$allDocs = @(DocsOf $h)                      # 한글 문서 순번 그대로 (빈 문서 포함)
$docs = @($allDocs | Where-Object { $_ })    # 사용자에게 보여 줄 이름 있는 문서

if ($a.doc) {
  $hit = @(); for ($i = 0; $i -lt $allDocs.Count; $i++) { if ($allDocs[$i] -and $allDocs[$i] -like "*$($a.doc)*") { $hit += $i } }
  if ($hit.Count -eq 0) { Emit @{ ok = $false; error = "doc_not_found"; docs = $docs }; exit 0 }
  if ($hit.Count -gt 1) { Emit @{ ok = $false; error = "doc_ambiguous"; docs = @($hit | ForEach-Object { $allDocs[$_] }) }; exit 0 }
  $null = $h.XHwpDocuments.Item($hit[0]).SetActive_XHwpDocument()
  Start-Sleep -Milliseconds 300   # 문서 전환이 끝난 뒤 명령
}

function Find-Text($text, $times) {
  $set = $h.HParameterSet.HFindReplace
  $null = $h.HAction.GetDefault("RepeatFind", $set.HSet)
  $set.FindString = $text; $set.Direction = 0; $set.IgnoreMessage = 1
  for ($k = 0; $k -lt $times; $k++) { if (-not $h.HAction.Execute("RepeatFind", $set.HSet)) { return $false } }
  return $true
}

function Insert-Fragment($file) {
  # 끼워 넣을 내용이 앞뒤 문단과 합쳐지지 않게, 커서 자리에 독립된 빈 문단을 만들고 그 안에 넣는다.
  $p = $h.GetPosBySet()
  $null = $h.HAction.Run("MoveParaEnd"); $e = $h.GetPosBySet(); $null = $h.SetPosBySet($p)
  $atStart = ([int]$p.Item("Pos") -eq 0)
  $atEnd = ([int]$e.Item("Pos") -eq [int]$p.Item("Pos"))
  if ($atStart -and $atEnd) { }                                   # 빈 문단: 그대로 넣는다
  elseif ($atStart) { $null = $h.HAction.Run("BreakPara"); $null = $h.HAction.Run("MovePrevParaEnd") }
  elseif ($atEnd) { $null = $h.HAction.Run("BreakPara") }
  else { $null = $h.HAction.Run("BreakPara"); $null = $h.HAction.Run("BreakPara"); $null = $h.HAction.Run("MovePrevParaEnd") }
  $set = $h.HParameterSet.HInsertFile
  $null = $h.HAction.GetDefault("InsertFile", $set.HSet)
  $set.FileName = $file; $set.FileFormat = "HWPX"
  $set.KeepSection = 0; $set.KeepCharshape = 1; $set.KeepParashape = 1; $set.KeepStyle = 1
  return [bool]$h.HAction.Execute("InsertFile", $set.HSet)
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
    "close_doc" {
      # 시험 정리용: --doc으로 고른 시험 문서만 저장하지 않고 닫는다. 남은 문서가 없으면 한글을 끈다.
      if ($a.doc) { $null = $h.XHwpDocuments.Active_XHwpDocument.Close($false) }
      Start-Sleep -Milliseconds 500
      $named = 0; for ($i = 0; $i -lt $h.XHwpDocuments.Count; $i++) { if ([string]$h.XHwpDocuments.Item($i).FullName) { $named++ } }
      $quit = ($named -eq 0)
      if ($quit) { $null = $h.Quit() }
      Emit @{ ok = $true; quit = $quit }
    }
    "select_test" {
      # 시험용: 사람이 드래그한 것처럼 para 문단의 start~end 글자를 선택한다.
      $null = $h.SetPos(0, [int]$a.para, 0)
      Emit @{ ok = [bool]$h.SelectText([int]$a.para, [int]$a.start, [int]$a.para, [int]$a.end) }
    }
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
      Emit @{ ok = (Insert-Fragment $a.file) }
    }
    "captions_before" {
      # 커서 문단 앞에 있는 캡션 달린 표·그림 수 (번호를 이어 매기기 위해)
      $pos = $h.GetPosBySet(); Emit @{ ok = $true; para = [int]$pos.Item("Para") }
    }
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
      Emit @{ ok = (Insert-Fragment $a.file) }
    }
    default { Emit @{ ok = $false; error = "unknown_action" } }
  }
} catch { Emit @{ ok = $false; error = $_.Exception.Message } }
