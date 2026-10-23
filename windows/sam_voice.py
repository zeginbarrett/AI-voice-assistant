"""SAM offline voices. Piper neural TTS (optional) or Windows SAPI fallback.
Output is always mono signed 16-bit, 16kHz RIFF WAV for the existing ESP32 player.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import wave

LOG=logging.getLogger('sam')
HERE=Path(__file__).resolve().parent
_PIPER=None
_PIPER_MODEL=None


def synthesize_sapi(message,config):
    with tempfile.TemporaryDirectory(prefix='sam_sapi_') as tmp:
        text=Path(tmp)/'text.txt'
        out=Path(tmp)/'sam.wav'
        text.write_text(message,encoding='utf-8')
        args=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
              '-File',str(HERE/'tts_sapi.ps1'),'-TextPath',str(text),'-OutPath',str(out),
              '-VoiceName',str(config.get('sapi_voice',''))]
        proc=subprocess.run(args,text=True,capture_output=True,timeout=45)
        if proc.returncode!=0:raise RuntimeError('Windows voice error: '+proc.stderr[-800:])
        return out.read_bytes()


def synthesize_piper(message,config):
    global _PIPER,_PIPER_MODEL
    voice_id=config.get('piper_voice','amy')
    if voice_id not in {'amy','hfc_female'}:raise ValueError('Unknown Piper voice')
    model=HERE/'voices'/f'en_US-{voice_id}-medium.onnx'
    if not model.is_file():raise FileNotFoundError(f'Piper model not installed: {model.name}. Run CHOOSE_SAM_VOICE.bat.')
    from piper import PiperVoice
    from sam_music import ffmpeg_path
    if _PIPER is None or _PIPER_MODEL!=str(model):
        _PIPER=PiperVoice.load(str(model),use_cuda=False)
        _PIPER_MODEL=str(model)
    with tempfile.TemporaryDirectory(prefix='sam_neural_') as tmp:
        native=Path(tmp)/'native.wav'
        with wave.open(str(native),'wb') as f:_PIPER.synthesize_wav(message,f)
        out=Path(tmp)/'out.wav'
        ffmpeg=ffmpeg_path()
        proc=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(native),
                             '-ac','1','-ar','16000','-acodec','pcm_s16le',str(out)],
                            timeout=25,capture_output=True)
        if proc.returncode!=0:raise RuntimeError('Piper audio resampling failed: '+proc.stderr.decode('utf-8','replace')[-400:])
        return out.read_bytes()


def speak(message,config):
    voice_type=str(config.get('voice_engine','sapi')).lower()
    if voice_type=='piper':
        try:data=synthesize_piper(message,config)
        except Exception as exc:
            LOG.warning('Neural voice unavailable (%s); using Windows female voice for this reply.',exc)
            data=synthesize_sapi(message,config)
    else:
        data=synthesize_sapi(message,config)
    if not(data.startswith(b'RIFF') and b'WAVE' in data[:16]):
        raise RuntimeError('TTS output is not WAV')
    if len(data)>3_500_000:raise RuntimeError('TTS WAV exceeds size limit')
    (HERE/'last_sam_reply.wav').write_bytes(data)
    return data
