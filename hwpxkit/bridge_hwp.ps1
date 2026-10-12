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
      # 본문 문단마다 쪽 번호. KeyIndicator는 출력 인자 8개(7번째 short)라 C# 리플렉션으로 부른다.
      if (-not ("HwpKey" -as [type])) {
        Add-Type -TypeDefinition @'
public static class HwpKey {
  public static int Page(object hwp) {
    object[] a = new object[] { 0, 0, 0, 0, 0, 0, (short)0, "" };
    var mod = new System.Reflection.ParameterModifier(8);
    for (int i = 0; i < 8; i++) mod[i] = true;
    hwp.GetType().InvokeMember("KeyIndicator", System.Reflection.BindingFlags.InvokeMethod, null, hwp, a,
      new System.Reflection.ParameterModifier[] { mod }, null, null);
    return System.Convert.ToInt32(a[2]);
  }
}
'@
      }
      $list = New-Object System.Collections.Generic.List[int]
      $i = 0
      while ($i -lt 100000 -and $hwp.SetPos(0, $i, 0)) { $list.Add([HwpKey]::Page($hwp)); $i++ }
      Emit @{ ok = $true; pages = $pages; total = $pages; paras = $list.ToArray() }
    }
    default   { Emit @{ ok = $false; error = "unknown_action" } }
  }
}
catch { Emit @{ ok = $false; error = $_.Exception.Message } }
finally {
  try { $hwp.Clear(1) } catch {}
  try { $hwp.Quit() } catch {}
}
