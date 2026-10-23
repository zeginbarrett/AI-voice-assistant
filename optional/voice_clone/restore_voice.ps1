$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'locate_sam.ps1')
try {
  $sam=Find-SamV5Windows
  $python=[IO.File]::ReadAllText((Join-Path $sam.Win 'python_path.txt')).Trim()
  $settings=Join-Path $sam.Win 'voice_settings.py'
  if(!(Test-Path -LiteralPath $settings)) {throw 'Voice settings script missing; run the clone installer first.'}
  & $python $settings restore $sam.Win
  if($LASTEXITCODE -ne 0){throw 'Restoring old voice failed'}
  Write-Host 'Restart START_SAM.bat to use your old voice.' -ForegroundColor Green
} catch {Write-Host $_.Exception.Message -ForegroundColor Red;exit 1}
