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
    "close_doc" {
      # 시험 정리용: --doc으로 고른 시험 문서만 저장하지 않고 닫는다. 남은 문서가 없으면 한글을 끈다.
      $null = $h.XHwpDocuments.Active_XHwpDocument.Close($false)
      if ($h.XHwpDocuments.Count -eq 1 -and -not [string]$h.XHwpDocuments.Item(0).FullName) { $null = $h.Quit() }
      Emit @{ ok = $true }
    }
    "select_test" {
      # 시험용: 사람이 드래그한 것처럼 para 문단의 start~end 글자를 선택한다.
      $null = $h.SetPos(0, [int]$a.para, 0)
      Emit @{ ok = [bool]$h.SelectText([int]$a.para, [int]$a.start, [int]$a.para, [int]$a.end) }
    }
    default { Emit @{ ok = $false; error = "unknown_action" } }
  }
} catch { Emit @{ ok = $false; error = $_.Exception.Message } }
