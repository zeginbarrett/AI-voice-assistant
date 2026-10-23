function Find-SamV5Windows {
  $downloads=Join-Path $env:USERPROFILE 'Downloads'
  if (!(Test-Path -LiteralPath $downloads -PathType Container)) { throw "Downloads folder not found: $downloads" }
  # IMPORTANT: PowerShell reserves an automatic regex-result variable.
  # Never name the candidate list after the automatic regex-result variable.
  $candidates=New-Object 'System.Collections.Generic.List[object]'
  $folders=Get-ChildItem -LiteralPath $downloads -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*SAM_V5*' }
  foreach($folder in $folders) {
    foreach($file in (Get-ChildItem -LiteralPath $folder.FullName -Filter 'sam_voice.py' -File -Recurse -ErrorAction SilentlyContinue)) {
      $win=$file.Directory.FullName
      $root=Split-Path -Parent $win
      $config=Join-Path $win 'settings.json'
      $pyfile=Join-Path $win 'python_path.txt'
      if ((Test-Path -LiteralPath $config) -and (Test-Path -LiteralPath $pyfile) -and
          (Test-Path -LiteralPath (Join-Path $root 'START_SAM.bat'))) {
        $priority= if($win -like '*FIXED_ONE_CLICK_NO_PIP*') {0} else {1}
        [void]$candidates.Add([PSCustomObject]@{ Win=$win; Root=$root; Priority=$priority; Changed=(Get-Item -LiteralPath $config).LastWriteTime })
      }
    }
  }
  if($candidates.Count -eq 0) {
    throw 'Could not find the running SAM v5 folder in Downloads. Run START_SAM.bat from the v5 folder once, then rerun this installer.'
  }
  $best=$candidates | Sort-Object Priority,@{Expression='Changed';Descending=$true} | Select-Object -First 1
  return $best
}
