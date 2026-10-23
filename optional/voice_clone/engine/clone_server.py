"""Standalone GPU-aware local Chatterbox speech service for SAM. No internet calls except first model download.
Requires a separate Python 3.11 environment with current official Chatterbox source.
The user's speaker reference is only ever read from the local drive.
"""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import logging
from pathlib import Path
import re
import sys
import threading
import wave

HERE=Path(__file__).resolve().parent
REFERENCE=HERE/'sam_reference.wav'
HOST='127.0.0.1'
PORT=18769
MODEL=None
DEVICE='cpu'


def text_chunks(text: str, limit: int=230):
    """Split longer responses on sentence boundaries to keep Chatterbox stable."""
    text=' '.join(text.strip().split())
    if not text: return []
    sentences=re.split(r'(?<=[.!?])\s+', text)
    result=[]
    for sentence in sentences:
        while len(sentence)>limit:
            cut=sentence.rfind(' ', 0, limit)
            if cut<limit//3: cut=limit
            result.append(sentence[:cut].strip())
            sentence=sentence[cut:].strip()
        if sentence:
            if result and len(result[-1])+len(sentence)+1 <= limit:
                result[-1]+=' '+sentence
            else:result.append(sentence)
    return result


def model_load():
    global MODEL, DEVICE
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    # Detect by doing real GPU work: a CUDA runtime may be installed even if
    # the hardware/driver cannot execute kernels. Reserve GPU RAM for Windows.
    DEVICE='cpu'
    free_vram=0
    if torch.cuda.is_available():
        try:
            t=torch.tensor([2.0, 3.0],device='cuda')
            if float((t*t).sum().item()) != 13.0:
                raise RuntimeError('CUDA test result incorrect')
            torch.cuda.synchronize()
            free_vram,_=torch.cuda.mem_get_info(0)
            DEVICE='cuda'
            logging.info('GPU detected: %s; free VRAM %.2f GiB',torch.cuda.get_device_name(0),free_vram/(1024**3))
        except Exception:
            logging.exception('CUDA test failed. Falling back to CPU Nano.')
    # Turbo on roomy NVIDIA GPUs; Nano on small NVIDIA GPUs (still accelerated).
    use_nano=(DEVICE=='cpu' or free_vram < 6*1024**3)
    logging.info('Loading %s on %s...', 'Chatterbox Nano' if use_nano else 'Chatterbox Turbo', DEVICE)
    try:
        MODEL=ChatterboxTurboTTS.from_pretrained(device=DEVICE,nano=use_nano)
    except RuntimeError as exc:
        if DEVICE=='cuda' and not use_nano and 'out of memory' in str(exc).lower():
            logging.warning('GPU memory insufficient for Turbo: switching to GPU Nano')
            del MODEL
            MODEL=None
            torch.cuda.empty_cache()
            MODEL=ChatterboxTurboTTS.from_pretrained(device='cuda',nano=True)
        else:
            raise
    logging.info('SAM clone model ready (%s / %s)', MODEL.model_label, DEVICE)


def synth(text: str) -> bytes:
    if MODEL is None:raise RuntimeError('Model is not loaded')
    if not REFERENCE.is_file():raise FileNotFoundError('SAM voice reference WAV missing')
    import torch
    import torchaudio
    chunks=text_chunks(text)
    if not chunks: raise ValueError('Cannot synthesize empty text')
    wave_parts=[]
    with torch.inference_mode():
        for phrase in chunks[:20]:
            spoken=MODEL.generate(phrase,audio_prompt_path=str(REFERENCE))
            if spoken.ndim>1:spoken=spoken.squeeze(0)
            spoken=spoken.to(dtype=torch.float32,device='cpu')
            if MODEL.sr != 16000:
                spoken=torchaudio.functional.resample(spoken,MODEL.sr,16000)
            spoken=torch.clamp(spoken,-1,1)
            wave_parts.append((spoken * 32767).to(torch.int16).numpy().tobytes())
            wave_parts.append(b'\0\0' * 1600)  # a natural 100ms between chunks
    if wave_parts: wave_parts.pop()
    with io.BytesIO() as f:
        with wave.open(f,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            wav.writeframes(b''.join(wave_parts))
        raw=f.getvalue()
    if len(raw)>3_500_000:raise RuntimeError('Reply too large for the Waveshare player')
    return raw


class Handler(BaseHTTPRequestHandler):
    server_version='SAM-Clone/1.0'
    def log_message(self,fmt,*args):logging.info(fmt,*args)
    def _send(self,status:int,body:bytes,kind='application/json'):
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path!='/health':return self._send(404,b'{}')
        status=json.dumps({'service':'sam-clone','ready':MODEL is not None,'device':DEVICE}).encode()
        self._send(200,status)
    def do_POST(self):
        if self.path!='/speak':return self._send(404,b'{}')
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<=10000:return self._send(413,b'{"error":"invalid size"}')
        try:
            req=json.loads(self.rfile.read(size))
            text=req.get('text','')
            if not isinstance(text,str) or not text.strip() or len(text)>2800:raise ValueError('Invalid text')
            data=synth(text)
        except Exception as e:
            logging.exception('Synthesis failed')
            return self._send(500,json.dumps({'error':str(e)[:400]}).encode())
        self._send(200,data,'audio/wav')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--preview',action='store_true',help='Generate WAV preview and quit')
    parser.add_argument('--output',default=str(HERE/'sam_clone_preview.wav'))
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.StreamHandler(sys.stdout)])
    model_load()
    if args.preview:
        msg='Hey! I am Sam. [chuckle] Okay, this is much more like me. What are we getting into today?'
        out=Path(args.output)
        out.write_bytes(synth(msg))
        print('PREVIEW SAVED:',out,flush=True)
        return
    HTTPServer((HOST,PORT),Handler).serve_forever()

if __name__=='__main__':main()
