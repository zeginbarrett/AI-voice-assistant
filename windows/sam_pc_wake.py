"""SAM standalone Windows brain. ESP32 sends 16kHz stereo PCM continuously.
No Home Assistant. PC recognizes 'Hey Sam' locally via Whisper and sends
assistant replies as 16k PCM WAV to the Waveshare speaker. Trusted LAN only.
"""
from __future__ import annotations
import collections
import sam_music
import sam_voice
import sam_clock
import hmac
import json
import logging
import math
from io import BytesIO
from pathlib import Path
import re
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('sam')
RATE = 16000
FRAME_BYTES = 4  # 16-bit signed little-endian stereo
CHUNK_FRAMES = 512
MAX_REPLY = 2_000_000
LOCK = threading.Lock()
CURRENT = None
_WHISPER = None
_WHISPER_LOCK = threading.Lock()
_CHAT_HISTORY = []
MODEL_CONFIG = {}
MUSIC = None

PERSONA = ('You are SAM, an upbeat, capable, witty, intelligent female voice assistant. '
           'Speak in natural conversational English, usually 1-3 short sentences. '
           'You can have an extended natural conversation across several turns. Answer direct questions directly, including telling a joke when asked. '
           'Avoid markdown, emoji and stage directions. If unsure, say so.')


def model():
    global _WHISPER
    with _WHISPER_LOCK:
        if _WHISPER is None:
            from faster_whisper import WhisperModel
            name = MODEL_CONFIG.get('whisper_model', 'base.en')
            LOG.info('Loading local Whisper %s (first launch may fetch weights)', name)
            _WHISPER = WhisperModel(name, device='cpu', compute_type='int8', cpu_threads=6)
    return _WHISPER


def wav_file(name, array):
    p = ROOT / name
    audio = np.asarray(array, dtype='<i2')
    with wave.open(str(p), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(audio.tobytes())


def measure(samples):
    samples = np.asarray(samples, dtype='<i2')
    if not samples.size:
        return {'rms': 0.0, 'peak': 0.0, 'zeros': 1.0}
    normalized = samples.astype(np.float32) / 32768.0
    return {
        'rms': float(np.sqrt(np.mean(normalized * normalized, dtype=np.float64))),
        'peak': float(np.max(np.abs(normalized))),
        'zeros': float(np.mean(samples == 0))}


def choose_channel(stereo):
    """Preserve raw channels; choose whichever has less silent/zero data."""
    left, right = stereo[:, 0], stereo[:, 1]
    lm, rm = measure(left), measure(right)
    score = lambda m: m['rms'] * (1.01 - m['zeros'])
    return (0 if score(lm) >= score(rm) else 1), lm, rm


def mic_corrupt(left, right):
    """Repeated ~87.5% zeros is a bad serialized sample stream, not quiet speech."""
    return left['zeros'] > .60 and right['zeros'] > .60


def spurious_transcript(text):
    """Refuse characteristic silence hallucinations instead of feeding them to Ollama."""
    normalized = re.sub(r'[^a-z ]', ' ', text.lower()).split()
    if not normalized: return False
    if len(normalized) >= 3 and len(set(normalized)) <= 2: return True
    if len(normalized) >= 14 and len(set(normalized))/len(normalized) < .24: return True
    if len(normalized) == 1 and normalized[0] in {'heh','ugh','you','okay'}: return True
    return False


def recognize(mono):
    if not mono.size: return ''
    data = mono.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(data)))
    rms = math.sqrt(float(np.mean(data * data, dtype=np.float64)))
    if peak < .0003: return ''
    gain = min(14.0, max(1.0, .045 / max(rms, 0.00001)), .88 / max(peak, 0.00001))
    if gain > 1: data = np.clip(data * gain, -1.0, 1.0)
    segments, _ = model().transcribe(
        data, language='en', beam_size=3, temperature=0.0,
        vad_filter=False, condition_on_previous_text=False)
    transcript = ' '.join(seg.text.strip() for seg in segments).strip()
    if spurious_transcript(transcript):
        LOG.warning('Ignoring repetitive Whisper hallucination: %r', transcript[:150])
        return ''
    return transcript


def is_wake(text):
    return bool(re.search(r'\b(?:hey|hi)\s+sam\b', text, re.I))


def ollama(prompt):
    global _CHAT_HISTORY
    messages = [{'role': 'system', 'content': PERSONA + '\n' + sam_clock.context()}] + _CHAT_HISTORY[-8:]
    messages.append({'role': 'user', 'content': prompt})
    body = {
        'model': MODEL_CONFIG['ollama_model'], 'messages': messages,
        'stream': False, 'think': False,
        'options': {'temperature': 0.65, 'num_predict': 140}}
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=75) as response:
            output = json.load(response)['message']['content'].strip()
    except Exception as exc:
        LOG.error('OLLAMA FAILED: %s', exc)
        return 'Ollama took too long to answer. Please try again.'
    if not output: return 'I did not get an answer from Ollama.'
    _CHAT_HISTORY.extend([{'role':'user','content':prompt}, {'role':'assistant','content':output}])
    _CHAT_HISTORY = _CHAT_HISTORY[-10:]
    return output.replace('**','').replace('`','')[:450]


def tts(message):
    return sam_voice.speak(message, MODEL_CONFIG)


def response_for(text):
    """Route hardware/media commands locally and return (spoken_reply,followup)."""
    if MUSIC is not None:
        local = sam_music.parse_command(text, MUSIC)
        if local is not None:
            # Music must start after TTS; no open mic feeding its own speaker.
            new_music=re.search(r'\b(?:play|shuffle)\s+', text, re.I) is not None
            return local, not new_music
    clock_reply = sam_clock.reply_for(text)
    if clock_reply is not None:
        return clock_reply, True
    return ollama(text),True


class Session:
    """Mic stream plus PC-side multi-turn dialogue with speech-end detection."""
    def __init__(self,sock,ip):
        self.socket=sock
        self.ip=ip
        self.lock=threading.RLock()
        self.frames_lock=threading.RLock()
        self.audio=collections.deque(maxlen=260)
        self.raw_slots=collections.deque(maxlen=130)
        self.firmware='UNKNOWN'
        self.question=[]
        self.state='IDLE'
        self.listen_start=0.0
        self.listen_until=0.0
        self.last_voice=0.0
        self.voice_chunks=0
        self.speech_started=False
        self.noise_floor=0.0005
        self.keep_followup=True
        self.listen_kind='WAKE'
        self.last_scan=0.0
        self.connected=True
        self.reply=None
        self.last_diag=0.0
        self.worker=threading.Thread(target=self.watch,daemon=True,name='sam-wake')
        self.worker.start()

    def send(self,byte):
        try:
            with self.lock:self.socket.sendall(byte)
            return True
        except OSError:
            self.connected=False;return False

    def ingest(self,raw):
        self.store_mics(np.frombuffer(raw,dtype='<i2').reshape(-1,2).copy())

    def ingest_raw4(self,raw):
        four=np.frombuffer(raw,dtype='<i2').reshape(-1,4).copy()
        with self.frames_lock:self.raw_slots.append(four)
        self.store_mics(four[:,[2,0]].copy())

    def store_mics(self,samples):
        now=time.monotonic()
        with self.frames_lock:
            self.audio.append(samples)
            if self.state=='LISTEN':
                self.question.append(samples)
                if len(self.question)>520:self.question.pop(0)
                if now-self.listen_start>=0.38:
                    # Analyze both channels. A brief, isolated loud sample does not
                    # count as a word: require at least 3 consecutive 32ms blocks.
                    x=samples.astype(np.float32) / 32768.0
                    rms=float(np.sqrt(np.mean(x*x,dtype=np.float64)))
                    threshold=max(0.00115, min(0.006, self.noise_floor*2.45))
                    if rms>=threshold:
                        self.voice_chunks+=1
                        if self.voice_chunks>=3:
                            self.speech_started=True
                            self.last_voice=now
                    else:
                        self.voice_chunks=0

    def snapshot(self,seconds=4.0):
        chunks=max(1,int(seconds*RATE/CHUNK_FRAMES))
        with self.frames_lock:parts=list(self.audio)[-chunks:]
        return np.concatenate(parts) if parts else np.zeros((0,2),dtype='<i2')

    def slot_diagnostics(self):
        with self.frames_lock:recent=list(self.raw_slots)
        if not recent:return
        four=np.concatenate(recent)
        info=[measure(four[:,i]) for i in range(4)]
        LOG.info('RAW4 slots 0..3 nonzeros: %s',', '.join('%.1f%%'%(100*(1-x['zeros'])) for x in info))
        for slot in range(4):wav_file('last_raw_slot%d.wav'%slot,four[:,slot])

    def awake(self,label,prefill=''):
        with self.frames_lock:
            if self.state!='IDLE':return
            baseline=self.snapshot(2.4)
            if len(baseline)>=CHUNK_FRAMES:
                count=(len(baseline)//CHUNK_FRAMES)*CHUNK_FRAMES
                blocks=baseline[-count:].astype(np.float32).reshape(-1,CHUNK_FRAMES,2)/32768.0
                levels=np.sqrt(np.mean(blocks*blocks,axis=(1,2)))
                self.noise_floor=max(0.00025,min(0.001, float(np.percentile(levels,20))))
            self.question.clear()
            self.speech_started=False
            self.voice_chunks=0
            self.listen_start=time.monotonic()
            self.last_voice=self.listen_start
            self.listen_until=self.listen_start+11.5
            self.state='LISTEN'
            self.listen_kind='WAKE'
        LOG.info('WAKE: %s; hands-free.',label)
        if prefill and len(prefill.split())>=2:
            LOG.info('HEARD IN WAKE: %r',prefill)
            with self.frames_lock:self.state='THINK'
            self.send(b'T')
            threading.Thread(target=self._speak_answer,args=(prefill,),daemon=True).start()
        else:
            self.send(b'L')
            LOG.info('SAM is listening; ask your question.')

    def listen_finished(self):
        with self.frames_lock:
            if self.state!='LISTEN':return
            self.state='THINK'
            parts=self.question[:]
            self.question.clear()
        self.send(b'T')
        self.last_scan=time.monotonic()
        threading.Thread(target=self.answer,args=(parts,),daemon=True).start()

    def answer(self,parts):
        try:
            if not parts:raise ValueError('No question audio arrived')
            stereo=np.concatenate(parts)
            c,lm,rm=choose_channel(stereo)
            wav_file('last_question.wav',stereo[:,c])
            LOG.info('QUESTION AUDIO: %.2fs, channel=%s, rms=%.5f, zeros=%.1f%%',
                     len(stereo)/RATE,'LEFT' if c==0 else 'RIGHT',
                     (lm,rm)[c]['rms'],(lm,rm)[c]['zeros']*100)
            if mic_corrupt(lm,rm):
                self._speak_answer('',override='The microphone stream looks corrupted. Try restarting SAM.')
                return
            text=recognize(stereo[:,c])
            LOG.info('HEARD: %r',text)
            if not text:
                self._speak_answer('',override='Could you repeat that?')
                return
            self._speak_answer(text)
        except Exception as exc:
            LOG.exception('QUESTION ERROR: %s',exc)
            self._recover()

    def _speak_answer(self,text,override=None):
        try:
            reply,followup=(override,True) if override else response_for(text)
            self.keep_followup=followup
            LOG.info('HEARD: %r',text)
            LOG.info('SAM: %s',reply)
            self.reply=tts(reply)
            LOG.info('TTS: %.1f KiB; starting reply',len(self.reply)/1024)
            with self.frames_lock:self.state='REPLY'
            self.send(b'P')
        except Exception as exc:
            LOG.exception('VOICE PIPELINE ERROR: %s',exc)
            self._recover()

    def _recover(self):
        with self.frames_lock:self.state='IDLE';self.question.clear()
        self.reply=None
        self.send(b'E')

    def close_reply(self):
        self.reply=None
        with self.frames_lock:
            self.question.clear()
            self.last_scan=time.monotonic()
            self.noise_floor=0.00050
            self.listen_start=self.last_scan
            self.listen_until=self.listen_start+12.0
            self.last_voice=self.last_scan
            self.speech_started=False
            self.voice_chunks=0
            self.listen_kind='FOLLOWUP'
            self.state='LISTEN' if self.keep_followup else 'IDLE'
        if self.keep_followup:
            self.send(b'L')
            LOG.info('FOLLOW-UP MODE: talk naturally, no Hey Sam needed (12 seconds).')
        else:
            self.send(b'I')
            LOG.info('MUSIC MODE: no re-wake needed for listening after next Hey Sam.')

    def diag(self):
        stereo=self.snapshot(4.0)
        if not stereo.size:return
        c,lm,rm=choose_channel(stereo)
        LOG.info('LIVE MIC: L peak %.4f RMS %.5f zeros %.1f%% | R peak %.4f RMS %.5f zeros %.1f%%',
                 lm['peak'],lm['rms'],lm['zeros']*100,rm['peak'],rm['rms'],rm['zeros']*100)
        wav_file('last_stream_left.wav',stereo[:,0]);wav_file('last_stream_right.wav',stereo[:,1])
        self.slot_diagnostics()
        if mic_corrupt(lm,rm):LOG.warning('Bad microphone stream; check ESP32 firmware.')

    def watch(self):
        while self.connected:
            now=time.monotonic()
            if now-self.last_diag>=9:
                self.last_diag=now
                try:self.diag()
                except Exception as exc:LOG.warning('Mic diagnostics: %s',exc)
            with self.frames_lock:
                state=self.state
                start=self.listen_start
                end=self.listen_until
                voice=self.last_voice
                talking=self.speech_started
            if state=='LISTEN':
                # One-second trailing silence finishes the question naturally.
                if talking and now-start>=1.2 and now-voice>=1.05:
                    self.listen_finished()
                elif now>=end:
                    if talking:self.listen_finished()
                    else:
                        with self.frames_lock:self.state='IDLE';self.question.clear()
                        self.send(b'I')
                        LOG.info('Conversation idle; say Hey Sam when ready.')
            if state=='IDLE' and now-self.last_scan>=1.8:
                self.last_scan=now
                try:
                    sample=self.snapshot(3.7)
                    if len(sample)<RATE*2:time.sleep(.1);continue
                    c,lm,rm=choose_channel(sample)
                    if mic_corrupt(lm,rm) or (lm['rms']<0.0010 and rm['rms']<0.0010):
                        time.sleep(.1);continue
                    text=recognize(sample[:,c])
                    if text:LOG.info('WAKE HEARD: %r',text[:250])
                    if is_wake(text):
                        # Don't lose a question spoken in the same phrase as 'Hey Sam'.
                        found=re.search(r'\b(?:hey|hi)\s+sam\b',text,re.I)
                        rest=text[found.end():].strip(' ,.!?') if found else ''
                        self.awake('Hey Sam (PC Whisper)',rest)
                except Exception as exc:LOG.error('PC WAKE RECOGNITION FAILED: %s',exc)
            time.sleep(.09)


def read_exact(sock, n):
    chunks=[]
    while n:
        block=sock.recv(n)
        if not block:raise EOFError('Device disconnected')
        chunks.append(block);n-=len(block)
    return b''.join(chunks)


def read_auth(sock):
    line=bytearray()
    for _ in range(160):
        x=read_exact(sock,1)
        if x==b'\n':break
        line.extend(x)
    else:raise ValueError('Too-long authentication line')
    marker,_,provided=line.partition(b' ')
    if marker!=b'SAMSTREAM1' or not hmac.compare_digest(provided.decode('ascii','ignore'),MODEL_CONFIG['token']):
        raise PermissionError('Invalid stream authentication')


class StreamServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    request_queue_size=5


class StreamHandler(socketserver.BaseRequestHandler):
    def handle(self):
        global CURRENT
        s=self.request
        s.settimeout(120)
        try:
            read_auth(s)
            sess=Session(s,self.client_address[0])
            with LOCK:
                old=CURRENT;CURRENT=sess
            if old:
                old.connected=False
                try:old.socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            sess.send(b'O')
            if MUSIC:MUSIC.bind(sess)
            LOG.info('ESP32 CONNECTED %s | continuous 16-bit stereo/16kHz microphone stream',sess.ip)
            while sess.connected:
                cmd=read_exact(s,1)
                if cmd==b'A':
                    count=int.from_bytes(read_exact(s,2),'little')
                    if count<=0 or count>1024:raise ValueError('Invalid frame count')
                    sess.ingest(read_exact(s,count*FRAME_BYTES))
                elif cmd==b'R':
                    count=int.from_bytes(read_exact(s,2),'little')
                    if count<=0 or count>1024:raise ValueError('Invalid raw frame count')
                    sess.ingest_raw4(read_exact(s,count*8))
                elif cmd==b'V':
                    length=read_exact(s,1)[0]
                    if length<1 or length>64:raise ValueError('Invalid firmware version frame')
                    sess.firmware=read_exact(s,length).decode('ascii','replace')
                    LOG.info('FIRMWARE VERIFIED: %s',sess.firmware)
                elif cmd==b'B':
                    sess.awake('K2 manual activation')
                elif cmd==b'D':
                    sess.close_reply()
                else:
                    raise ValueError('Unknown stream packet')
        except (EOFError, ConnectionError, OSError, ValueError, PermissionError) as exc:
            LOG.warning('ESP32 disconnected: %s', exc)
        finally:
            try:sess.connected=False
            except UnboundLocalError:pass
            with LOCK:
                if CURRENT is locals().get('sess'):CURRENT=None


class HTTPHandler(BaseHTTPRequestHandler):
    server_version='SAM-StandAlone/0.2'
    def log_message(self, fmt, *args):
        LOG.info('HTTP %s: '+fmt, self.client_address[0], *args)
    def reply(self, status, contents, content_type='text/plain'):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(contents)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(contents)
    def do_GET(self):
        if self.path == '/health':
            self.reply(200,json.dumps({'service':'SAM PC WAKE','ready':True,
                                       'active_stream':CURRENT is not None,
                                       'model':MODEL_CONFIG['ollama_model']}).encode(),'application/json')
            return
        if self.path!='/v1/reply':return self.reply(404,b'Not found')
        if not hmac.compare_digest(self.headers.get('X-Sam-Token',''),MODEL_CONFIG['token']):
            return self.reply(403,b'Invalid token')
        with LOCK:
            sess=CURRENT
        if sess is None or sess.reply is None:return self.reply(404,b'No reply pending')
        self.reply(200,sess.reply,'audio/wav')


def main():
    global MODEL_CONFIG, MUSIC
    settings=ROOT/'settings.json'
    if not settings.exists():raise RuntimeError('Missing settings.json; run RUN_SAM_TEST.bat')
    MODEL_CONFIG=json.loads(settings.read_text(encoding='utf-8'))
    if not MODEL_CONFIG.get('token') or not MODEL_CONFIG.get('ollama_model'):
        raise RuntimeError('Missing authentication or Ollama model in settings.json')
    MUSIC=sam_music.MusicPlayer(MODEL_CONFIG['token'])
    MUSIC.volume=max(0,min(100,int(MODEL_CONFIG.get('speaker_volume',75))))
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',datefmt='%H:%M:%S')
    LOG.info('SAM V5 | Hands-free follow-up + voice volume + microSD music | v4 16kHz I2S')
    LOG.info('Whisper detects "Hey Sam" ON WINDOWS, not on the ESP32')
    LOG.info('Ollama model %s; HANDS-FREE Hey Sam | K2 optional diagnostic',MODEL_CONFIG['ollama_model'])
    LOG.info('Blue=idle | purple=listening | amber=thinking | green=speaking')
    LOG.info('Volume: say volume up/down or set volume to 40 percent. Music: play music/skip/pause.')
    LOG.info('Female voice engine: %s (change with CHOOSE_SAM_VOICE.bat)',MODEL_CONFIG.get('voice_engine','sapi'))
    LOG.info('Every 9s: LIVE MIC stereo levels and WAV recordings; no buttons required')
    LOG.info('Private LAN only: audio and voice replies are NOT encrypted')
    port=int(MODEL_CONFIG.get('port',8765));stream_port=int(MODEL_CONFIG.get('stream_port',8766))
    listener=StreamServer(('0.0.0.0',stream_port),StreamHandler)
    threading.Thread(target=listener.serve_forever,daemon=True).start()
    LOG.info('Audio stream TCP 0.0.0.0:%d | Reply HTTP 0.0.0.0:%d',stream_port,port)
    server=ThreadingHTTPServer(('0.0.0.0',port),HTTPHandler)
    try:server.serve_forever()
    finally:listener.shutdown();server.server_close();listener.server_close();server.server_close()


if __name__=='__main__':main()
