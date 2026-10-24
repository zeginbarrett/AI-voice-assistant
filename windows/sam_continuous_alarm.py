"""Continuous local alarm tone streamed to the existing ESP32 PCM music socket.

Alarms use the persistent scheduler in sam_alarms.py. Playback is not an
ESP32 firmware feature and requires a connected Windows SAM process.
"""
from __future__ import annotations

import logging
import math
import socket
import struct
import threading
import time

LOG = logging.getLogger('sam')
RATE = 16000
SAMPLE_BLOCK = 3200


def tone_block(block):
    """Alternating alarm tones with no long silent interval (stereo PCM16)."""
    pcm = bytearray()
    for n in range(SAMPLE_BLOCK):
        t = (block * SAMPLE_BLOCK + n) / RATE
        freq = 830 if int(t / .45) % 2 == 0 else 670
        wave = .60 * math.sin(2 * math.pi * freq * t) + .24 * math.sin(2 * math.pi * 440 * t)
        value = int(14500 * wave)
        pcm.extend(struct.pack('<hh', value, value))
    return bytes(pcm)


class ContinuousAlarmAudio:
    """One background playback stream; stop and snooze interrupt it immediately."""

    def __init__(self):
        self._lock = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._socket = None
        self._identity = None

    def stop(self):
        with self._lock:
            self._stop.set()
            sock = self._socket
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def ensure(self, alarms, session, music):
        with alarms._lock:
            active = alarms._active
            alarm_id = (active['id'], active['started']) if active else None
        with self._lock:
            if not alarm_id or not session or not session.connected:
                if self._worker and self._worker.is_alive():
                    self.stop()
                return
            key = (alarm_id, id(session))
            if self._identity == key and self._worker and self._worker.is_alive():
                return
            if self._worker and self._worker.is_alive():
                self.stop()
                return
            self._stop = threading.Event()
            self._identity = key
            self._worker = threading.Thread(
                target=self._run, args=(alarms, session, music, alarm_id, self._stop),
                daemon=True, name='sam-continuous-alarm')
            self._worker.start()

    def _run(self, alarms, session, music, alarm_id, stopped):
        sock = None
        try:
            if music is None:
                raise RuntimeError('Audio-stream authentication is unavailable')
            music.stop(silent=True)
            session.send(b'G' + bytes([max(80, music.volume)]))
            with socket.create_connection((session.ip, 8771), timeout=5) as sock:
                sock.settimeout(5)
                with self._lock: self._socket = sock
                sock.sendall(('SAMAUDIO1 ' + music.token + '\n').encode('ascii'))
                LOG.info('CONTINUOUS ALARM: sounding until stop, snooze, or safety cutoff')
                index=0
                started=time.monotonic()
                while not stopped.is_set() and session.connected:
                    with alarms._lock:
                        active=alarms._active
                        if not active or (active['id'],active['started']) != alarm_id:
                            break
                    delay = started + index * (SAMPLE_BLOCK / RATE) - time.monotonic()
                    if delay > 0 and stopped.wait(delay): break
                    sock.sendall(tone_block(index))
                    index += 1
        except (OSError, ValueError, RuntimeError) as exc:
            if not stopped.is_set():
                LOG.warning('Continuous alarm stream interrupted: %s; retrying if active',exc)
        finally:
            with self._lock:
                if self._socket is sock: self._socket = None
            if music is not None and session.connected:
                session.send(b'G' + bytes([music.volume]))
