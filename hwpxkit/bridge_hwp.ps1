param(
  [Parameter(Mandatory = $true)][string]$Action,
  [string]$Src = "",
  [string]$Dst = "",
  [string]$Format = "",
  [string]$PidFile = ""
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Emit($obj) { [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress -Depth 4)) }

$before = @(Get-Process Hwp -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
function ToTop($h) {
  # Leave any selection / table cell and put the caret at the top of the main text
  try { $null = $h.HAction.Run("Cancel") } catch {}
  try { $null = $h.MovePos(2, 0, 0) } catch {}
}

try { $hwp = New-Object -ComObject HWPFrame.HwpObject }
catch { Emit @{ ok = $false; error = "no_hwp" }; exit 0 }
# Record the Hwp process this script started (on timeout Python kills only these)
if ($PidFile) {
  $mine = @(Get-Process Hwp -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | ForEach-Object { $_.Id })
  [System.IO.File]::WriteAllText($PidFile, ($mine -join ","))
}

try {
  try { $hwp.XHwpWindows.Item(0).Visible = $false } catch {}
  if ($Action -eq "blank") {
    $r = $hwp.SaveAs($Dst, "HWPX", "")
    Emit @{ ok = [bool]$r; dst = $Dst }
    return
  }
  $srcFmt = "HWP"
  if ($Src.ToLower().EndsWith(".hwpx")) { $srcFmt = "HWPX" }
  if (-not $hwp.Open($Src, $srcFmt, "forceopen:true;versionwarning:false")) {
    Emit @{ ok = $false; error = "open_failed" }
    return
  }
  $pages = [int]$hwp.PageCount
  switch ($Action) {
    "check"   { Emit @{ ok = $true; pages = $pages } }
    "convert" {
      $r = $hwp.SaveAs($Dst, $Format, "")
      Emit @{ ok = [bool]$r; pages = $pages; dst = $Dst }
    }
    "pages"   {
      ToTop $hwp
      $files = @()
      for ($i = 0; $i -lt $pages; $i++) {
        $f = Join-Path $Dst ("page{0:D3}.bmp" -f ($i + 1))
        if ($hwp.CreatePageImage($f, $i, 96, 24, "bmp")) { $files += $f }
      }
      Emit @{ ok = $true; pages = $pages; files = $files }
    }
    "refresh" {
      # Re-apply each equation's own script so Hangul recomputes its size (works inline and in table cells)
      $n = 0
      $ctrl = $hwp.HeadCtrl
      while ($ctrl -ne $null) {
        if ($ctrl.CtrlID -eq "eqed") {
          $null = $hwp.SetPosBySet($ctrl.GetAnchorPos(0))
          $null = $hwp.FindCtrl()
          $pset = $hwp.HParameterSet.HEqEdit
          $null = $hwp.HAction.GetDefault("EquationModify", $pset.HSet)
          $pset.string = $pset.string
          if ($hwp.HAction.Execute("EquationModify", $pset.HSet)) { $n++ }
        }
        $ctrl = $ctrl.Next
      }
      ToTop $hwp
      $r = $hwp.SaveAs($Dst, "HWPX", "")
      Emit @{ ok = [bool]$r; pages = $pages; count = $n }
    }
    "toc" {
      # 문서 안 차례 칸(TABLEOFCONTENTS)을 한글이 다시 만들고 쪽 번호를 채운다 (MakeContents는 한글이 죽어 쓰지 않음)
      $u = $hwp.HAction.Run("UpdateAllContents")
      ToTop $hwp
      $r = $hwp.SaveAs($Dst, "HWPX", "")
      Emit @{ ok = [bool]$r; pages = $pages; updated = [bool]$u }
    }
    "pagemap" {
      # 실제 쪽마다 본문 글 (인쇄 쪽 번호는 새 쪽 번호로 다시 시작할 수 있어 쓰지 않는다). 엔진이 장 제목 줄을 찾는다.
      ToTop $hwp
      $texts = @()
      for ($i = 0; $i -lt $pages; $i++) { $texts += [string]$hwp.GetPageText($i, 0) }
      Emit @{ ok = $true; pages = $pages; total = $pages; texts = $texts }
    }
    "memos" {
      # 메모 달기: Format = JSON 파일 [{anchor, n, text}]. 처음부터 anchor를 n번째까지 찾아 그 자리에 한글 메모.
      $list = Get-Content -Raw -Encoding UTF8 $Format | ConvertFrom-Json
      # 문서 끝까지 찾으면 "처음부터 다시 찾을까요?"가 떠 멈춘다 → 예/아니오는 아니오, 확인은 확인으로 자동 응답
      try { $null = $hwp.SetMessageBoxMode(0x22021) } catch {}
      $placed = 0; $missed = @(); $k = 0
      foreach ($m in @($list)) {
        $k++
        ToTop $hwp
        $set = $hwp.HParameterSet.HFindReplace
        $null = $hwp.HAction.GetDefault("RepeatFind", $set.HSet)
        $set.FindString = [string]$m.anchor; $set.Direction = 0; $set.IgnoreMessage = 1
        foreach ($opt in @("MatchCase", "WholeWordOnly", "FindRegExp", "FindJaso", "AllWordForms", "SeveralWords", "UseWildCards")) {
          try { $null = $set.HSet.SetItem($opt, $(if ($opt -eq "MatchCase") { 1 } else { 0 })) } catch {}
        }
        $found = $true
        $seen = @{}  # 찾기가 문서 끝에서 처음으로 돌아가면 같은 자리가 다시 나온다 → 못 찾은 것으로
        for ($j = 0; $j -lt [int]$m.n; $j++) {
          if (-not $hwp.HAction.Execute("RepeatFind", $set.HSet)) { $found = $false; break }
          $ps = $hwp.GetPosBySet(); $at = "$($ps.Item('List'))/$($ps.Item('Para'))/$($ps.Item('Pos'))"
          if ($seen.ContainsKey($at)) { $found = $false; break }
          $seen[$at] = $true
        }
        if (-not $found) { $missed += $k; continue }
        $before = [int]$hwp.GetPosBySet().Item("List")
        $opened = [bool]$hwp.HAction.Run("InsertFieldMemo")
        if ($opened -and [int]$hwp.GetPosBySet().Item("List") -ne $before) {
          $ins = $hwp.HParameterSet.HInsertText
          $null = $hwp.HAction.GetDefault("InsertText", $ins.HSet); $ins.Text = [string]$m.text
          $null = $hwp.HAction.Execute("InsertText", $ins.HSet)
          $null = $hwp.HAction.Run("CloseEx")
          $placed++
        } else { $null = $hwp.HAction.Run("Cancel"); $missed += $k }
      }
      ToTop $hwp
      $r = $hwp.SaveAs($Dst, "HWPX", "")
      Emit @{ ok = [bool]$r; pages = $pages; placed = $placed; missed = $missed }
    }
    default   { Emit @{ ok = $false; error = "unknown_action" } }
  }
}
catch { Emit @{ ok = $false; error = $_.Exception.Message } }
finally {
  try { $hwp.Clear(1) } catch {}
  try { $hwp.Quit() } catch {}
}
