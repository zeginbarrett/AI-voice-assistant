"""Standalone SAM microSD music service.
MP3 files remain on the ESP32 SD card. Authenticated local-only transfer to the
PC, ffmpeg decode, and stereo PCM16 streaming back to the ESP32 speaker.
Nothing touches the working ES7210 microphone capture configuration.
"""
from __future__ import annotations
import logging
import random
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

LOG = logging.getLogger('sam')
MAX_MP3 = 70 * 1024 * 1024


def ffmpeg_path():
    """Use verified standalone FFmpeg first; imageio or PATH as fallback.

    The SAM Python virtualenv may intentionally have no pip installed.
    """
    local = Path(__file__).resolve().parent / 'tools' / 'ffmpeg.exe'
    if local.is_file():
        return str(local)
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(ffmpeg).is_file(): return str(ffmpeg)
    except (ImportError, RuntimeError, OSError):
        pass
    import shutil
    binary = shutil.which('ffmpeg')
    if binary: return binary
    raise RuntimeError('MP3 decoder not installed. Run INSTALL_MUSIC_DECODER.bat (no flash needed).')


class MusicPlayer:
    def __init__(self, token: str):
        self.token = token
        self.session = None
        self.volume = 75
        self.muted_previous = 75
        self.tracks = []
        self.sequence = []
        self.position = 0
        self.current = ''
        self.playing = False
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._worker = None
        self._lock = threading.RLock()
        self._generation = 0
        self._pending_sequence = None
        self._defer_play = False
        self._audio_socket = None

    def bind(self, session):
        with self._lock:
            self.session = session
            session.send(b'G' + bytes([self.volume]))

    def set_volume(self, n):
        n = max(0, min(100, int(n)))
        with self._lock:
            self.volume = n
            if n: self.muted_previous = n
            session = self.session
        if session and session.connected:
            session.send(b'G' + bytes([n]))
        try:
            import json
            cfg_path=Path(__file__).parent/'settings.json'
            if cfg_path.exists():
                cfg=json.loads(cfg_path.read_text(encoding='utf-8'))
                cfg['speaker_volume']=n
                cfg_path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        except Exception: LOG.warning('Volume changed, but could not save persistent level.')
        LOG.info('SPEAKER VOLUME: %d%%', n)
        return f'Volume set to {n} percent.'

    def adjust_volume(self, step):
        return self.set_volume(self.volume + step)

    def mute(self):
        return self.set_volume(0)

    def unmute(self):
        return self.set_volume(self.muted_previous or 70)

    def _get(self, path: str, session, timeout=15):
        req = urllib.request.Request(f'http://{session.ip}:8770{path}', headers={'X-Sam-Token': self.token})
        return urllib.request.urlopen(req, timeout=timeout)

    def refresh(self):
        with self._lock: session = self.session
        if not session or not session.connected:
            raise RuntimeError('SAM is not connected')
        with self._get('/library', session) as response:
            raw = response.read(250000).decode('utf-8','replace')
        if raw.startswith('ERROR'):
            raise RuntimeError('microSD is not mounted. Insert a FAT32 card and restart SAM.')
        tracks=[]
        for line in raw.splitlines():
            k,sep,title=line.partition('\t')
            if sep and k.isdecimal() and title and len(tracks)<1500:
                tracks.append((int(k),title))
        with self._lock: self.tracks = tracks
        LOG.info('SD LIBRARY: %d MP3 files',len(tracks))
        return tracks

    def play(self, query=''):
        tracks=self.refresh()
        if not tracks:return 'I found no MP3 files on the microSD card. Put songs in a Music folder.'
        search=re.sub(r'(?i)^(some |the |my )?(music|songs|tracks)( by | from )?','',query).strip().lower()
        if search in {'','some music','music','songs','something','everything','all','my music'}:
            selection=list(tracks)
            random.shuffle(selection)
        else:
            tokens=[x for x in re.findall(r'[a-z0-9]+',search) if x not in {'play','song','music','by','the','some','from'}]
            selection=[t for t in tracks if all(x in re.sub(r'[^a-z0-9]+',' ',t[1].lower()) for x in tokens)]
            if not selection:return f'I could not find {query} on the SD card. Try saying play music.'
        # Start requested playback only after the spoken acknowledgement finishes.
        if self._defer_play:
            with self._lock: self._pending_sequence = list(selection)
        else:
            self._new_sequence(selection)
        return ('Playing ' + Path(selection[0][1]).stem.replace('_',' ') + '.'
                if len(selection) == 1 else 'Okay, loading the music now.')

    def start_queued(self):
        with self._lock:
            queued = self._pending_sequence
            self._pending_sequence = None
        if queued:
            self._new_sequence(queued)
            return True
        return False

    def _new_sequence(self, sequence):
        self.stop(silent=True)
        with self._lock:
            self.sequence=list(sequence)
            self.position=0
            self._stop=threading.Event()
            self._pause=threading.Event()
            self._generation += 1
            generation=self._generation
            self.playing=True
            self._worker=threading.Thread(target=self._run,args=(generation,self._stop,self._pause),daemon=True,name='sam-music')
            self._worker.start()

    def _run(self,generation,stop,paused):
        interruptions=0
        try:
            while not stop.is_set():
                with self._lock:
                    if generation != self._generation or self.position >= len(self.sequence): break
                    index,name=self.sequence[self.position]
                    session=self.session
                    self.current=name
                if not session or not session.connected: break
                LOG.info('MUSIC NOW PLAYING: %s',name)
                try:
                    self._play_one(session,index,stop,paused)
                    interruptions=0
                except (OSError, RuntimeError, ValueError) as exc:
                    if stop.is_set(): break
                    interruptions+=1
                    LOG.warning('MUSIC STREAM INTERRUPTED: %s (%s); not skipping track',name,exc)
                    if interruptions >= 3: break
                    if stop.wait(min(2*interruptions,5)): break
                    continue
                if stop.is_set(): break
                with self._lock:
                    if generation != self._generation: break
                    self.position+=1
        finally:
            with self._lock:
                if generation == self._generation:
                    self.playing=False
                    self.current=''
                    LOG.info('MUSIC: stopped')

    def _play_one(self,session,index,stop,paused):
        ffmpeg=ffmpeg_path()
        with tempfile.TemporaryDirectory(prefix='sam_sdmp3_') as tmp:
            target=Path(tmp)/'song.mp3'
            with self._get('/track/'+str(index),session,timeout=35) as resp, target.open('wb') as fd:
                total=0
                while not stop.is_set():
                    data=resp.read(65536)
                    if not data: break
                    total+=len(data)
                    if total > MAX_MP3: raise RuntimeError('File exceeds 70 MB limit')
                    fd.write(data)
            if stop.is_set() or target.stat().st_size < 100: return
            cmd=[ffmpeg,'-hide_banner','-loglevel','error','-i',str(target),'-vn',
                 '-f','s16le','-acodec','pcm_s16le','-ac','2','-ar','16000','pipe:1']
            proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            audio=None
            try:
                with socket.create_connection((session.ip,8771),timeout=8) as audio:
                    audio.settimeout(30)
                    with self._lock: self._audio_socket=audio
                    audio.sendall(('SAMAUDIO1 '+self.token+'\n').encode('ascii'))
                    while not stop.is_set():
                        while paused.is_set() and not stop.is_set(): time.sleep(.06)
                        if stop.is_set(): break
                        buf=proc.stdout.read(4096)
                        if not buf: break
                        audio.sendall(buf)
            finally:
                with self._lock:
                    if self._audio_socket is audio: self._audio_socket=None
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=4)

    def stop(self,silent=False):
        with self._lock:
            self._stop.set()
            self._generation+=1
            self.playing=False
            self.current=''
            self._pending_sequence=None
            sock=self._audio_socket
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        if not silent: LOG.info('MUSIC: stopped on request')
        return 'Music stopped.'

    def pause(self):
        if not self.playing:return 'There is no music playing.'
        self._pause.set();return 'Music paused.'

    def resume(self):
        if not self.playing:return 'There is no music to resume.'
        self._pause.clear();return 'Resuming music.'

    def next(self):
        with self._lock:
            if not self.playing:return 'There is no music playing.'
            other=self.sequence[self.position+1:]
        if not other:return self.stop()
        self._new_sequence(other)
        return 'Skipping to the next song.'

    def previous(self):
        with self._lock:
            if not self.sequence:return 'There is no music playing.'
            pos=max(0,self.position-1);other=self.sequence[pos:]
        self._new_sequence(other)
        return 'Playing the previous song.'

    def describe(self):
        if self.playing and self.current:return 'Playing '+Path(self.current).stem.replace('_',' ')+'.'
        return 'No music is playing.'


def parse_command(text: str, player: MusicPlayer):
    """Return a reply for local playback/volume intents, otherwise None for Ollama."""
    t=re.sub(r'\s+',' ',text.lower().strip())
    # Only intercept explicit volume/media requests, not arbitrary questions.
    m=re.search(r'\b(?:set|change|turn|put)?\s*(?:the |sam(?:\'s)? )?(?:speaker |music |audio )?volume\s*(?:to|at)?\s*(\d{1,3})\s*(?:percent|%)?\b',t)
    if m:return player.set_volume(int(m.group(1)))
    if re.search(r'\b(?:volume|sound)\s+(?:up|louder|higher)\b|\b(?:turn|make)\s+(?:it|the volume|sam)\s+(?:up|louder)\b|\b(?:turn up|increase|raise)\s+(?:the\s+)?volume\b|\bspeak louder\b',t):
        return player.adjust_volume(10)
    if re.search(r'\b(?:volume|sound)\s+(?:down|quieter|lower)\b|\b(?:turn|make)\s+(?:it|the volume|sam)\s+(?:down|quieter)\b|\b(?:turn down|decrease|lower)\s+(?:the\s+)?volume\b|\bspeak quieter\b',t):
        return player.adjust_volume(-10)
    if re.search(r'\bunmute(?:\s+(?:the\s+)?(?:music|speaker|audio|volume))?\b',t): return player.unmute()
    if re.search(r'\bmute(?:\s+(?:the\s+)?(?:music|speaker|audio|volume))?\b',t): return player.mute()
    if re.search(r'\b(?:stop|turn off|end)\s+(?:the\s+)?(?:music|song|playlist)\b',t): return player.stop()
    if re.search(r'\b(?:pause)\s*(?:(?:the\s+)?(?:music|song|playlist))?\s*[.!?]*$',t):return player.pause()
    if re.search(r'\b(?:resume|continue)\s+(?:(?:the\s+)?(?:music|song|playlist))\b',t):return player.resume()
    if re.search(r'\b(?:next|skip)(?:\s+(?:track|song|music))?\b',t):return player.next()
    if re.search(r'\b(?:previous|last)\s+(?:track|song)\b',t):return player.previous()
    if re.search(r'\b(?:what(?:\'s| is) playing|what song is this)\b',t):return player.describe()
    # Only commands that START with play/shuffle should control the music.
    # In conversation, 'you play the actor' must remain ordinary dialogue.
    t=re.sub(r'^(?:(?:hey|hi)\s+sam[,! ]*|please\s+)+','',t)
    m=re.match(r'^(?:play|shuffle)\s+(.+)',t)
    if m:return player.play(m.group(1).strip(' .!?'))
    return None
