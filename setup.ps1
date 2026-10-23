# SAM PC-WAKE one-click installer: uses previous working credentials and Python.
# Does not print passwords or tokens. Compiles and flashes the new standalone firmware.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$sketch = Join-Path $root 'SAM_PC_Wake'
$win = Join-Path $root 'windows'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Step([string]$text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function StopWith([string]$text) { throw $text }
function RunTool([string]$exe,[string[]]$arguments,[string]$logFile) {
  Write-Host ('> ' + (Split-Path -Leaf $exe) + ' ' + ($arguments -join ' ')) -ForegroundColor DarkGray
  $old=$ErrorActionPreference;$ErrorActionPreference='Continue';$code=-1
  try {
    & $exe @arguments 2>&1 | Tee-Object -FilePath $logFile | Out-Host
    $code=$LASTEXITCODE
  } finally { $ErrorActionPreference=$old }
  if($code -ne 0) {StopWith "Tool failed (exit $code). See $logFile"}
}
function HeaderValue([string]$content,[string]$key) {
  $m=[regex]::Match($content,'(?m)^\s*#define\s+'+[regex]::Escape($key)+'\s+"([^"\r\n]*)"')
  if($m.Success){return $m.Groups[1].Value}
  return ''
}
function ReadConfig([string]$path){
  try { if(Test-Path -LiteralPath $path -PathType Leaf){return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)} }catch{}
  return $null
}
function PythonReady([string]$exe) {
  if(!(Test-Path -LiteralPath $exe -PathType Leaf)){return $false}
  $old=$ErrorActionPreference;$ErrorActionPreference='Continue';$rc=-1
  try {
    & $exe -c 'import sys, numpy, ctranslate2, faster_whisper; assert sys.version_info[:2] == (3,12)' 2>&1 | Out-Null
    $rc=$LASTEXITCODE
  } catch {} finally { $ErrorActionPreference=$old }
  return $rc -eq 0
}
function FindArduinoCli([string[]]$projectDirs) {
  $paths = New-Object 'System.Collections.Generic.List[string]'
  $cmd=Get-Command arduino-cli.exe -ErrorAction SilentlyContinue
  if($cmd){$paths.Add([string]$cmd.Source)}
  $paths.Add((Join-Path $root 'tools\arduino-cli.exe'))
  foreach($project in $projectDirs) {$paths.Add((Join-Path $project 'tools\arduino-cli.exe'))}
  $paths.Add("$env:ProgramFiles\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
  $paths.Add("$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
  $paths.Add("$env:LOCALAPPDATA\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
  foreach($p in $paths){if($p -and (Test-Path -LiteralPath $p -PathType Leaf)){return $p}}
  return $null
}
function DetectBoardPort() {
  $ports=@(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | Where-Object {$_.Name -match '\(COM\d+\)' -and $_.Status -eq 'OK'} |
    ForEach-Object {[pscustomobject]@{Port=[regex]::Match($_.Name,'COM\d+').Value;Name=$_.Name;Device=$_.PNPDeviceID}})
  foreach($port in $ports){ Write-Host "Port $($port.Port): $($port.Name)" }
  $matches=@($ports|Where-Object {$_.Name -match 'Espressif|USB JTAG|USB Serial|CP210|ESP32' -or $_.Device -match 'VID_303A'})
  if($matches.Count -eq 1){return $matches[0].Port}
  StopWith 'Could not uniquely identify SAM COM port. Plug in the Waveshare and retry. If you have several serial devices, disconnect the others temporarily.'
}

try {
  Step 'Find previously flashed SAM configuration in Downloads'
  $downloads=Join-Path $env:USERPROFILE 'Downloads'
  if(!(Test-Path -LiteralPath $downloads -PathType Container)){StopWith 'Downloads folder missing'}
  $projects=New-Object 'System.Collections.Generic.List[string]'
  foreach($d in @(Get-ChildItem -LiteralPath $downloads -Directory | Where-Object {$_.Name -like 'SAM_Standalone_Voice*'})) {
    $projects.Add($d.FullName)
    foreach($nested in @(Get-ChildItem -LiteralPath $d.FullName -Directory -ErrorAction SilentlyContinue | Where-Object {$_.Name -like 'SAM_Standalone_Voice*'})){
      $projects.Add($nested.FullName)
    }
  }
  $profiles=@()
  foreach($d in $projects){
    $h=Join-Path $d 'SAM_Voice\sam_config.h'
    if(!(Test-Path -LiteralPath $h -PathType Leaf)){continue}
    $src=Get-Content -LiteralPath $h -Raw
    $token=HeaderValue $src 'SAM_TOKEN'
    $ip=HeaderValue $src 'SAM_PC_IP'
    if(!$token -or !$ip){continue}
    $saved=ReadConfig (Join-Path $d 'windows\settings.json')
    $score=100
    if($saved -and [string]$saved.token -eq $token){$score+=100}
    $u=Join-Path $d 'logs\firmware-upload.log'
    if(Test-Path -LiteralPath $u){
      if((Get-Content -LiteralPath $u -Tail 30 | Out-String) -match 'Hash of data verified|Hard resetting'){$score+=250}
    }
    $profiles += [pscustomobject]@{Root=$d;Header=$h;Source=$src;Token=$token;IP=$ip;Saved=$saved;Score=$score;Modified=(Get-Item -LiteralPath $h).LastWriteTime}
  }
  if($profiles.Count -eq 0){StopWith 'No previous SAM firmware credentials in Downloads. The existing SAM folders must remain available for this upgrade.'}
  $selected=$profiles|Sort-Object -Property @{Expression='Score';Descending=$true},@{Expression='Modified';Descending=$true}|Select-Object -First 1
  Write-Host "Using existing SAM firmware configuration: $($selected.Root)" -ForegroundColor Green
  # Recover settings matching the current board's token. Never show secret text.
  if($selected.Saved -and [string]$selected.Saved.token -eq $selected.Token){
    $settings=$selected.Saved
  }else{
    $settings=[pscustomobject]@{token=$selected.Token;ollama_model='qwen3.5:4b';whisper_model='base.en';port=8765}
  }
  if(!$settings.ollama_model){$settings|Add-Member -NotePropertyName ollama_model -NotePropertyValue 'qwen3.5:4b' -Force}
  if(!$settings.whisper_model){$settings|Add-Member -NotePropertyName whisper_model -NotePropertyValue 'base.en' -Force}
  if(!$settings.port){$settings|Add-Member -NotePropertyName port -NotePropertyValue 8765 -Force}
  $settings|Add-Member -NotePropertyName stream_port -NotePropertyValue 8766 -Force
  $previousSettings=ReadConfig (Join-Path $win 'settings.json')
  if($previousSettings -and [string]$previousSettings.token -eq $selected.Token){
    foreach($key in @('voice_engine','piper_voice','sapi_voice','speaker_volume')) {
      $property=$previousSettings.PSObject.Properties[$key]
      if($property){$settings|Add-Member -NotePropertyName $key -NotePropertyValue $property.Value -Force}
    }
  }
  if(!$settings.PSObject.Properties['voice_engine']){$settings|Add-Member -NotePropertyName voice_engine -NotePropertyValue 'sapi' -Force}
  if(!$settings.PSObject.Properties['speaker_volume']){$settings|Add-Member -NotePropertyName speaker_volume -NotePropertyValue 75 -Force}
  $settingsPath=Join-Path $win 'settings.json'
  [IO.File]::WriteAllText($settingsPath,($settings | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
  $headerText=$selected.Source
  if($headerText -notmatch '(?m)^\s*#define\s+SAM_STREAM_PORT\b'){$headerText+="`r`n#define SAM_STREAM_PORT 8766`r`n"}
  [IO.File]::WriteAllText((Join-Path $sketch 'sam_config.h'),$headerText,[Text.UTF8Encoding]::new($false))
  Write-Host "PC endpoint: $($selected.IP):8765 (speech) / :8766 (continuous microphone)" -ForegroundColor Green
  Write-Host 'Credentials recovered locally; no password/token is displayed or sent to external services.'

  Step 'Use existing Whisper Python installation (no reinstall)'
  $python=$null
  $pythonOptions=New-Object 'System.Collections.Generic.List[string]'
  $pythonOptions.Add((Join-Path $selected.Root 'windows\.venv\Scripts\python.exe'))
  foreach($d in $projects){$pythonOptions.Add((Join-Path $d 'windows\.venv\Scripts\python.exe'))}
  foreach($p in $pythonOptions){if(PythonReady $p){$python=$p;break}}
  if(!$python){StopWith 'Working Python 3.12/Whisper environment not found. Keep the older SAM directories in Downloads.'}
  [IO.File]::WriteAllText((Join-Path $win 'python_path.txt'),$python,[Text.UTF8Encoding]::new($false))
  Write-Host 'Whisper + CTranslate2 + NumPy: OK' -ForegroundColor Green

  Step 'Check old SAM bridge port availability'
  $occupied=@(Get-NetTCPConnection -LocalPort 8765,8766 -State Listen -ErrorAction SilentlyContinue)
  if($occupied.Count -gt 0){StopWith 'Ports 8765/8766 are occupied. Close the OLD SAM black window (Ctrl+C) before running this one-click test.'}

  Step 'Install MP3 decoder WITHOUT pip (can reuse installed FFmpeg)'
  $decoderSetup=Join-Path $win 'install_ffmpeg.py'
  $oldPref=$ErrorActionPreference; $ErrorActionPreference='Continue'
  $ffmpegReady=$false
  try {
    & $python $decoderSetup
    $ffmpegReady=($LASTEXITCODE -eq 0)
  } finally { $ErrorActionPreference=$oldPref }
  if($ffmpegReady){
    Write-Host 'FFmpeg is ready. SD-card MP3 playback can run without installing pip.' -ForegroundColor Green
  }else{
    Write-Host 'WARNING: Could not download MP3 decoder. SAM voice still works.' -ForegroundColor Yellow
    Write-Host 'You can later run INSTALL_MUSIC_DECODER.bat; it DOES NOT flash the board.' -ForegroundColor Yellow
  }

  Step 'Compile and flash continuous microphone-streamer firmware' 
  $arduino=FindArduinoCli ($projects.ToArray())
  if(!$arduino){StopWith 'Arduino CLI was not found. Your prior successful installer should have it in tools or Arduino IDE.'}
  $port=DetectBoardPort
  $fqbn='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=huge_app,CDCOnBoot=cdc,USBMode=hwcdc,UploadSpeed=115200'
  $build=Join-Path $root 'build'
  $compile=@('compile','--fqbn',$fqbn,'--build-path',$build,$sketch)
  RunTool $arduino $compile (Join-Path $logs 'compile.log')
  RunTool $arduino @('upload','--fqbn',$fqbn,'--port',$port,'--input-dir',$build,$sketch) (Join-Path $logs 'flash.log')
  Write-Host 'FLASH COMPLETE: SAM V5 hands-free conversation + SD music + voice speaker volume.' -ForegroundColor Green
  exit 0
} catch {
  Write-Host "`nSAM ONE-CLICK FAILED: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
