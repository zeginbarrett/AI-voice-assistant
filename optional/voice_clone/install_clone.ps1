$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$homeDir=Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $homeDir 'locate_sam.ps1')

function FailIfBadExit([string]$description) {
  if($LASTEXITCODE -ne 0) {throw "$description failed (exit code $LASTEXITCODE). Check the message above."}
}
function Copy-Source([string]$file,[string]$out) {Copy-Item -LiteralPath (Join-Path $homeDir $file) -Destination $out -Force}

try {
  Write-Host "`n================================================" -ForegroundColor Cyan
  Write-Host '      SAM - GPU-AWARE CUSTOM FEMALE VOICE' -ForegroundColor Cyan
  Write-Host '      NO ESP32 FLASH REQUIRED' -ForegroundColor Green
  Write-Host "================================================`n" -ForegroundColor Cyan
  Write-Host 'This uses your own recorded reference to produce new local speech.'
  Write-Host 'Only use a speaker voice you own or have permission to synthesize.' -ForegroundColor Yellow
  if(!(Test-Path -LiteralPath (Join-Path $homeDir 'engine\sam_reference.wav') -PathType Leaf)) { throw 'Place your own authorized voice clip at optional\voice_clone\engine\sam_reference.wav before running this installer.' }
  $consent=Read-Host 'Do you have permission to clone the voice in the supplied sample? Type YES'
  if($consent -cne 'YES') { Write-Host 'No changes made.'; exit 2 }

  $sam=Find-SamV5Windows
  $win=$sam.Win
  Write-Host "`nFound your current SAM v5 installation:" -ForegroundColor Green
  Write-Host $sam.Root
  $bridgePython=[IO.File]::ReadAllText((Join-Path $win 'python_path.txt')).Trim()
  if(!(Test-Path -LiteralPath $bridgePython -PathType Leaf)) {throw "SAM's Python executable is missing: $bridgePython"}
  Write-Host 'Windows + mic/speaker firmware remain unchanged.'
  Write-Host 'This installation needs an internet connection and several GB of disk space.'
  Write-Host 'NVIDIA CUDA GPUs will be used automatically when supported. AMD/Intel may run on CPU.' -ForegroundColor Yellow

  $toolDir=Join-Path $homeDir 'tools'
  New-Item -ItemType Directory -Path $toolDir -Force | Out-Null
  $uv=Join-Path $toolDir 'uv.exe'
  if(!(Test-Path -LiteralPath $uv -PathType Leaf)) {
    $cmd=Get-Command uv -ErrorAction SilentlyContinue
    if($cmd) {$uv=$cmd.Source}
  }
  if(!(Test-Path -LiteralPath $uv -PathType Leaf)) {
    Write-Host "`nDownloading official uv installer (isolated Python environment; no pip required)..." -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $url='https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
    $archive=Join-Path $toolDir 'uv_win.zip'
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -MaximumRedirection 10
    if((Get-Item -LiteralPath $archive).Length -lt 1000000) {throw 'uv download incomplete'}
    Expand-Archive -LiteralPath $archive -DestinationPath $toolDir -Force
    Remove-Item -LiteralPath $archive -Force
    $candidate=Get-ChildItem -LiteralPath $toolDir -Filter 'uv.exe' -Recurse -File | Select-Object -First 1
    if(!$candidate) {throw 'uv.exe was missing from the official release archive'}
    $uv=$candidate.FullName
  }

  $cloneEnv=Join-Path $win '.sam_clone_env'
  $voicePython=Join-Path $cloneEnv 'Scripts\python.exe'
  if(!(Test-Path -LiteralPath $voicePython -PathType Leaf)) {
    Write-Host "`nInstalling isolated Python 3.11 for voice cloning..." -ForegroundColor Cyan
    & $uv python install 3.11
    FailIfBadExit 'Python 3.11 installation'
    & $uv venv --python 3.11 $cloneEnv
    FailIfBadExit 'Voice environment creation'
  }

  Write-Host "`nInstalling latest official Chatterbox voice engine from source..." -ForegroundColor Cyan
  Write-Host 'SAM Whisper/Piper packages will NOT be changed.'
  # PyPI's current 0.1.7 wheel predates the Nano model; install official repository.
  & $uv pip install --python $voicePython 'git+https://github.com/resemble-ai/chatterbox.git'
  FailIfBadExit 'Chatterbox installation'
  & $voicePython -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; print('Chatterbox imported successfully')"
  FailIfBadExit 'Voice dependency verification'

  # A generic GPU is not automatically compatible with CUDA. Probe Windows
  # adapters, then verify actual CUDA tensor execution, not just a GPU name.
  Write-Host "`nChecking your Windows GPU for CUDA voice acceleration..." -ForegroundColor Cyan
  $adapterNames=@()
  try { $adapterNames=@(Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object { $_.Name }) } catch {}
  foreach($adapter in $adapterNames) { Write-Host ('  GPU: '+$adapter) }
  $hasNvidia=$false
  foreach($adapter in $adapterNames) { if($adapter -match '(?i)NVIDIA') {$hasNvidia=$true} }
  $smi=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
  if($smi) {
    $hasNvidia=$true
    try { & $smi.Source '--query-gpu=name,driver_version,memory.total' '--format=csv,noheader' } catch {}
  }
  $gpuProbe=Join-Path $homeDir 'engine\gpu_probe.py'
  & $voicePython $gpuProbe
  $cudaReady=($LASTEXITCODE -eq 0)
  if($hasNvidia -and !$cudaReady) {
    Write-Host "`nNVIDIA detected but PyTorch CUDA is not yet working." -ForegroundColor Yellow
    Write-Host 'Installing the official PyTorch 2.6 / CUDA 12.6 Windows wheels...' -ForegroundColor Cyan
    Write-Host 'This is a large download. GPU packages are isolated from SAM Whisper.'
    # Chatterbox currently pins PyTorch 2.6. Use its officially published CUDA build.
    & $uv pip install --python $voicePython --index-url 'https://download.pytorch.org/whl/cu126' --reinstall-package torch --reinstall-package torchaudio 'torch==2.6.0' 'torchaudio==2.6.0'
    if($LASTEXITCODE -ne 0) {
      Write-Host 'CUDA PyTorch install did not finish. CPU voice remains available.' -ForegroundColor Yellow
    }
    & $voicePython $gpuProbe
    $cudaReady=($LASTEXITCODE -eq 0)
  }
  if($cudaReady) {
    Write-Host 'GPU ACCELERATION VERIFIED. SAM will generate voice using CUDA.' -ForegroundColor Green
  } else {
    Write-Host 'CUDA acceleration unavailable. SAM can still use CPU Nano.' -ForegroundColor Yellow
    Write-Host 'If your GPU is AMD/Intel or is not supported by this PyTorch version, the CUDA engine cannot use it directly.'
  }

  Write-Host "`nInstalling reference sample and local voice service..." -ForegroundColor Cyan
  Copy-Source 'engine\clone_server.py' (Join-Path $win 'clone_server.py')
  Copy-Source 'engine\patch_sam_voice.py' (Join-Path $win 'patch_sam_voice.py')
  Copy-Source 'engine\voice_settings.py' (Join-Path $win 'voice_settings.py')
  Copy-Source 'engine\sam_reference.wav' (Join-Path $win 'sam_reference.wav')
  & $bridgePython (Join-Path $win 'patch_sam_voice.py') (Join-Path $win 'sam_voice.py')
  FailIfBadExit 'Safe SAM TTS patch'

  Write-Host "`nGenerating first custom SAM voice preview..." -ForegroundColor Cyan
  $preview=Join-Path $win 'sam_clone_preview.wav'
  & $voicePython (Join-Path $win 'clone_server.py') --preview --output $preview
  FailIfBadExit 'Cloned voice preview'
  if(!(Test-Path -LiteralPath $preview -PathType Leaf)) {throw 'Preview file was not generated'}
  Write-Host 'Preview WAV:' $preview -ForegroundColor Green
  try {Start-Process -FilePath $preview} catch {Write-Host 'Open that WAV file to listen to your preview.' -ForegroundColor Yellow}
  Write-Host "`nListen to the preview first. Your previous SAM voice is still active."
  $answer=Read-Host 'Use this cloned female voice as SAM now? Type YES'
  if($answer -cne 'YES') { Write-Host 'No voice selection changed. You can replay the WAV and rerun this installer.'; exit 0 }
  & $bridgePython (Join-Path $win 'voice_settings.py') activate $win $voicePython
  FailIfBadExit 'Voice activation'
  Write-Host "`nSUCCESS: SAM now uses her cloned voice!" -ForegroundColor Green
  Write-Host 'Close any old SAM window with Ctrl+C, then run:'
  Write-Host (Join-Path $sam.Root 'START_SAM.bat') -ForegroundColor Cyan
  Write-Host 'Keep this installer folder to run RESTORE_OLD_SAM_VOICE.bat if needed.'
} catch {
  Write-Host "`nCUSTOM VOICE SETUP COULD NOT COMPLETE:" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Red
  Write-Host 'The prior voice setting was not switched unless you confirmed a generated preview.'
  exit 1
}
