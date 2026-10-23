$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$win=Join-Path $root 'windows'
$pythonFile=Join-Path $win 'python_path.txt'
if(!(Test-Path -LiteralPath $pythonFile -PathType Leaf)){
  Write-Host 'First run RUN_SAM_TEST.bat to recover Python/settings and flash the board.' -ForegroundColor Red
  exit 1
}
$python=[IO.File]::ReadAllText($pythonFile).Trim()
if(!(Test-Path -LiteralPath $python -PathType Leaf)){
  Write-Host "SAM Python not found; your old Downloads folder was moved: $python" -ForegroundColor Red
  exit 1
}
if(!(Test-Path -LiteralPath (Join-Path $win 'settings.json') -PathType Leaf)){
  Write-Host 'settings.json missing. Run RUN_SAM_TEST.bat.' -ForegroundColor Red
  exit 1
}
Write-Host "`nSAM V5 HANDS-FREE IS RUNNING" -ForegroundColor Cyan
Write-Host 'Wake word is now detected by WINDOWS (offline Whisper), not the ESP32.'
Write-Host 'Say HEY SAM, ask your question, then speak naturally for follow-up questions.'
Write-Host 'SAM streams 16kHz stereo over private Wi-Fi. Music and speaker controls enabled.'
Write-Host 'Allow Python on PRIVATE networks if Windows Firewall asks.'
Write-Host 'Keep this window OPEN. Press Ctrl+C to stop SAM.'
Write-Host ''
& $python (Join-Path $win 'sam_pc_wake.py')
if($LASTEXITCODE -ne 0){Write-Host 'SAM bridge stopped with an error.' -ForegroundColor Red;exit 1}
