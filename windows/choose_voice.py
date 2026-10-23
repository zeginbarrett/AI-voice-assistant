"""Interactive offline SAM female voice selector. Run via CHOOSE_SAM_VOICE.bat."""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SETTINGS=ROOT/'settings.json'
PIPER={
    'amy':'en_US-amy-medium',
    'hfc_female':'en_US-hfc_female-medium',
}


def save(settings):
    SETTINGS.write_text(json.dumps(settings,indent=2),encoding='utf-8')


def download_voice(voice):
    name=PIPER[voice]
    base=f'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/{voice}/medium/{name}.onnx'
    directory=ROOT/'voices';directory.mkdir(exist_ok=True)
    for ext in ('','.json'):
        path=directory/(name+'.onnx'+ext)
        if path.is_file() and path.stat().st_size>2000:continue
        url=base+ext
        print(f'Downloading {path.name} (one time; the neural model is about 60MB)...',flush=True)
        req=urllib.request.Request(url,headers={'User-Agent':'SAM-local-voice-setup/1.0'})
        tmp=path.with_suffix(path.suffix+'.part')
        with urllib.request.urlopen(req,timeout=90) as response, tmp.open('wb') as out:
            while True:
                block=response.read(128*1024)
                if not block:break
                out.write(block)
        if ext=='' and tmp.stat().st_size<10_000_000:raise RuntimeError('Model download incomplete')
        if ext and tmp.stat().st_size<100:raise RuntimeError('Voice config download incomplete')
        tmp.replace(path)


def ensure_piper():
    try:import piper
    except ImportError:
        print('Installing Piper into your existing SAM Python environment...',flush=True)
        subprocess.run([sys.executable, str(ROOT/'ensure_pip.py')],check=True)
        subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','piper-tts'],check=True)
    # Resampling uses bundled FFmpeg, so no imageio-ffmpeg Python package needed.
    from install_ffmpeg import install as ensure_ffmpeg
    ensure_ffmpeg()


def sapi_voices():
    ps="Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name+'|'+$_.VoiceInfo.Gender }; $s.Dispose()"
    try:
        o=subprocess.run(['powershell.exe','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=15)
        return [x.split('|',1)[0] for x in o.stdout.splitlines() if x.strip() and '|' in x]
    except Exception:return []


def main():
    if not SETTINGS.exists():raise RuntimeError('SAM is not installed yet. Run RUN_SAM_TEST.bat first.')
    settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
    print('\nSAM - CHOOSE HER VOICE (free, offline after model download)')
    print('  1 - Piper Amy: natural US female (recommended)')
    print('  2 - Piper HFC Female: alternate US female')
    print('  3 - Windows built-in female voice (no downloads)')
    voices=sapi_voices()
    for i,name in enumerate(voices):print(f'  {i+4} - Windows voice: {name}')
    choice=input('\nChoose voice number: ').strip()
    if choice in {'1','2'}:
        voice='amy' if choice=='1' else 'hfc_female'
        ensure_piper();download_voice(voice)
        settings['voice_engine']='piper';settings['piper_voice']=voice
    elif choice=='3':settings['voice_engine']='sapi';settings['sapi_voice']=''
    elif choice.isdecimal() and 4<=int(choice)<4+len(voices):
        settings['voice_engine']='sapi';settings['sapi_voice']=voices[int(choice)-4]
    else:raise RuntimeError('Invalid choice; voice unchanged.')
    save(settings)
    print('\nVoice saved. Restart START_SAM.bat to hear it through the Waveshare.')
    print('You can change it again anytime; no reflashing required.')


if __name__=='__main__':
    try:main()
    except Exception as exc:print('Voice setup failed:',exc);sys.exit(1)
