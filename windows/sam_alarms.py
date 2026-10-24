"""Local, persistent voice-controlled alarms for SAM's Windows brain."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
from io import BytesIO
import math
import struct
import wave

LOG = logging.getLogger('sam')
DAY_NAMES = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
                'fifteen': 15, 'twenty': 20, 'thirty': 30, 'forty': 40,
                'forty-five': 45, 'sixty': 60}
DURATION = re.compile(r'\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|forty-five|sixty)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b')
CLOCK = re.compile(r'\b(?:at|for)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b', re.I)


def _normal(text):
    return re.sub(r'\s+', ' ', text.lower().replace('\u2019', "'")).strip(' .!?')


def _duration(text):
    m = DURATION.search(text)
    if not m:
        return None
    count = NUMBER_WORDS.get(m.group(1))
    if count is None:
        count = float(m.group(1))
    unit = m.group(2)
    seconds = count * (3600 if unit.startswith(('hour', 'hr')) else
                       60 if unit.startswith('min') else 1)
    return timedelta(seconds=seconds) if 0 < seconds <= 365 * 86400 else None


def _clock_time(text, now=None, days=None, tomorrow=False):
    """Accept spoken/digit clock times, choosing next AM or PM if unspecified."""
    q = _normal(text)
    if re.search(r'\b(?:at|for|by)\s+noon\b', q): return (12, 0)
    if re.search(r'\b(?:at|for|by)\s+midnight\b', q): return (0, 0)
    q = re.sub(r'(?<![a-z])([ap])\s*\.?\s*m\.?(?![a-z])',
               lambda m: ' ' + m.group(1) + 'm ', q, flags=re.I)
    q = re.sub(r'\s+', ' ', q).strip(' .!?')
    m = re.search(r'\b(?:at|for|by)\s+'
                  r'(?P<clock>\d{1,4}(?:(?:\s*[:.]\s*|\s+)\d{1,2})?)'
                  r'\s*(?P<period>am|pm)?(?!\s*\d)(?=$|[\s,!?;.])', q, re.I)
    period = None
    parsed = None
    if m:
        raw = m.group('clock').strip()
        if re.search(r'[:.\s]', raw):
            parts = re.split(r'\s*[:.]\s*|\s+', raw)
            if len(parts) == 2: parsed = (int(parts[0]), int(parts[1]))
        elif len(raw) in (3, 4):
            parsed = (int(raw[:-2]), int(raw[-2:]))
        else:
            parsed = (int(raw), 0)
        period = m.group('period')
    else:
        # Whisper may render the same time as "six thirty five".
        spoken = re.search(
            r'\b(?:at|for|by)\s+'
            r'(?P<clock>[a-z]+(?:[-\s]+[a-z]+){0,4}?)'
            r'(?:\s+(?P<period>am|pm))?'
            r'(?=$|\s+(?:tomorrow|today|every|on|this|please)\b|[,.!?;])',
            q, re.I)
        if spoken:
            terms = spoken.group('clock').replace('-', ' ').split()
            values = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,
                      'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,
                      'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,
                      'seventeen':17,'eighteen':18,'nineteen':19,'twenty':20,
                      'thirty':30,'forty':40,'fifty':50,'oh':0,'zero':0}
            if terms and terms[0] in values:
                h = values[terms[0]]
                rest = terms[1:]
                if not rest or rest in (['oclock'], ['o','clock']): minute = 0
                elif len(rest) == 1 and rest[0] in values: minute = values[rest[0]]
                elif len(rest) == 2 and all(t in values for t in rest):
                    minute = values[rest[0]] + values[rest[1]]
                else: minute = -1
                parsed=(h,minute)
                period=spoken.group('period')
    if parsed is None: return None
    hour,minute=parsed
    if not 0 <= minute <= 59: return None
    if period:
        if not 1 <= hour <= 12: return None
        return hour % 12 + (12 if period == 'pm' else 0), minute
    if hour == 0 or 13 <= hour <= 23: return hour,minute
    if not 1 <= hour <= 12: return None
    reference=now if now is not None else datetime.now()
    options=[hour % 12, hour % 12 + 12]
    return min(options, key=lambda h: _next_clock(reference,h,minute,days,tomorrow)),minute


def _recurrence(text):
    if re.search(r'\b(?:every day|daily|each day)\b', text):
        return list(range(7))
    if re.search(r'\b(?:every weekday|weekdays|each weekday|monday through friday)\b', text):
        return list(range(5))
    if re.search(r'\b(?:every weekend|weekends|each weekend)\b', text):
        return [5, 6]
    for idx, day in enumerate(DAY_NAMES):
        if re.search(r'\b(?:every|each|on)\s+' + day + r's?\b', text):
            return [idx]
    return []


def _next_clock(now, hour, minute, days=None, tomorrow=False):
    if tomorrow:
        d = now.date() + timedelta(days=1)
        return datetime.combine(d, datetime.min.time()).replace(hour=hour, minute=minute)
    for increment in range(9):
        d = now.date() + timedelta(days=increment)
        if days and d.weekday() not in days:
            continue
        candidate = datetime.combine(d, datetime.min.time()).replace(hour=hour, minute=minute)
        if candidate > now:
            return candidate
    raise ValueError('Unable to calculate next alarm time')


def _say_time(when):
    return when.strftime('%I:%M %p').lstrip('0')


def _describe(item):
    dt = datetime.fromisoformat(item['next_at'])
    when = dt.strftime('%A %B ') + str(dt.day) + ' at ' + _say_time(dt)
    days = item.get('days') or []
    if days == list(range(7)):
        when = 'every day at ' + _say_time(dt)
    elif days == list(range(5)):
        when = 'weekdays at ' + _say_time(dt)
    elif days == [5, 6]:
        when = 'weekends at ' + _say_time(dt)
    elif len(days) == 1:
        when = 'every ' + DAY_NAMES[days[0]].capitalize() + ' at ' + _say_time(dt)
    return when


class AlarmManager:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._alarms = []
        self._active = None
        self._pending = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('alarms'), list):
                raise ValueError('Invalid SAM alarms file; it was left unchanged')
            for item in data['alarms']:
                datetime.fromisoformat(item['next_at'])
                if not isinstance(item.get('days'), list):
                    raise ValueError('Invalid saved alarm recurrence')
            self._alarms = data['alarms']

    def _save(self, alarms):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.sam_alarms_', suffix='.tmp', dir=str(self.path.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump({'version': 1, 'alarms': alarms}, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _add(self, when, days=None, name='Alarm'):
        if len(self._alarms) >= 100:
            return 'You already have 100 alarms. Cancel one before adding another.'
        item = {'id': uuid.uuid4().hex, 'next_at': when.isoformat(timespec='seconds'),
                'days': list(days or []), 'name': name[:80]}
        updated = self._alarms + [item]
        self._save(updated)
        self._alarms = updated
        return 'Alarm set for ' + _describe(item) + '.'

    def handle(self, text, now=None):
        """Return an acknowledged result or None for unrelated questions."""
        q = _normal(text)
        now = now if now is not None else datetime.now()
        with self._lock:
            if re.search(r'\bsnooze(?:\s+(?:the|my)\s+alarm)?\b', q):
                if self._active is None:
                    return 'No alarm is ringing to snooze.'
                delta = _duration(q) or timedelta(minutes=10)
                when = now + delta
                result = self._add(when, name=self._active['name'])
                if result.startswith('Alarm set'):
                    self._active = None
                    return 'Snoozed until ' + _say_time(when) + '.'
                return result

            if re.search(r'\b(?:stop|dismiss|silence|turn off)\s+(?:the\s+|my\s+|that\s+)?(?:alarm|timer)\b', q):
                if self._active:
                    self._active = None
                    return 'Alarm stopped.'
                return 'No alarm is ringing. Say cancel an alarm to remove a scheduled one.'

            if re.search(r'\b(?:cancel|delete|remove|clear)\b', q) and re.search(r'\b(?:alarms?|timers?)\b', q):
                if re.search(r'\b(?:all|every)\b', q):
                    self._save([])
                    self._alarms = []
                    self._active = None
                    self._pending = []
                    return 'All scheduled alarms have been canceled.'
                ordered = sorted(self._alarms, key=lambda a: a['next_at'])
                idx_match = re.search(r'\b(?:alarm|timer)\s+(?:number\s+)?(\d+|one|two|three|four|five)\b', q)
                choice = NUMBER_WORDS.get(idx_match.group(1)) if idx_match else None
                if idx_match and choice is None and idx_match.group(1).isdigit():
                    choice = int(idx_match.group(1))
                if choice is not None and 1 <= choice <= len(ordered):
                    target = ordered[choice - 1]
                elif len(ordered) == 1:
                    target = ordered[0]
                else:
                    return 'Say list my alarms, then cancel alarm number one, two, and so on.'
                updated = [x for x in self._alarms if x['id'] != target['id']]
                self._save(updated)
                self._alarms = updated
                self._pending = [x for x in self._pending if x['id'] != target['id']]
                return 'Canceled the alarm for ' + _describe(target) + '.'

            if (re.search(r'\b(?:list|show|check)\s+(?:me\s+)?(?:my\s+|the\s+)?alarms?\b', q)
                or re.search(r'\b(?:what|which|when)\b.*\b(?:alarms?|next alarm)\b', q)):
                ordered = sorted(self._alarms, key=lambda a: a['next_at'])
                if not ordered:
                    return 'You have no scheduled alarms.'
                items = [f'{i}. {_describe(x)}' for i, x in enumerate(ordered[:5], 1)]
                ending = f' Plus {len(ordered)-5} more.' if len(ordered) > 5 else ''
                return 'Your alarms: ' + '; '.join(items) + '.' + ending

            is_set = (re.search(r'\b(?:set|create|schedule|add|make)\b.{0,35}\b(?:alarm|timer)\b', q)
                      or re.search(r'\bwake me (?:up )?\b', q))
            if not is_set:
                return None

            delta = _duration(q)
            if delta and (re.search(r'\b(?:in|for)\s+', q) or re.search(r'\btimer\b', q)):
                if _recurrence(q):
                    return 'For a repeating alarm, please specify a clock time with AM or PM.'
                return self._add(now + delta)
            parsed = _clock_time(q, now=now, days=_recurrence(q), tomorrow=bool(re.search(r'\btomorrow\b', q)))
            if parsed is None:
                return 'Please tell me a clock time, like 6:30 or 6:30 PM.'
            days = _recurrence(q)
            tomorrow = bool(re.search(r'\btomorrow\b', q))
            if days and tomorrow:
                return 'Please choose either tomorrow or a repeating schedule.'
            hour, minute = parsed
            return self._add(_next_clock(now, hour, minute, days, tomorrow), days)

    def poll(self, now=None):
        """Advance due schedules and queue alarm(s) to ring."""
        now = now if now is not None else datetime.now()
        with self._lock:
            if self._active and (now - self._active['started']).total_seconds() > 1800:
                self._active = None
            ordered = sorted(self._alarms, key=lambda a: a['next_at'])
            changed = False
            updated = [dict(x) for x in self._alarms]
            for item in ordered:
                due = datetime.fromisoformat(item['next_at'])
                if due > now:
                    break
                if now - due <= timedelta(minutes=30):
                    self._pending.append(item)
                for index, candidate in enumerate(updated):
                    if candidate['id'] == item['id']:
                        if candidate['days']:
                            candidate['next_at'] = _next_clock(
                                now, due.hour, due.minute, candidate['days']
                            ).isoformat(timespec='seconds')
                        else:
                            updated.pop(index)
                        changed = True
                        break
            if changed:
                self._save(updated)
                self._alarms = updated
            if self._active is None and self._pending:
                selected = self._pending.pop(0)
                self._active = {'id': selected['id'], 'name': selected.get('name', 'Alarm'),
                                'started': now, 'last_ring': None}
                LOG.info('ALARM DUE: %s', selected['next_at'])

    def should_ring(self, now=None):
        now = now if now is not None else datetime.now()
        with self._lock:
            if not self._active:
                return False
            last = self._active['last_ring']
            return last is None or (now - last).total_seconds() >= 20

    def mark_ring(self, now=None):
        now = now if now is not None else datetime.now()
        with self._lock:
            if not self._active:
                return None
            self._active['last_ring'] = now
            return self._active['name']


def alarm_chime(wav_bytes):
    """Prepend three-tone PCM chime to the voice reply, keeping ESP32 WAV format."""
    with wave.open(BytesIO(wav_bytes), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(),
                source.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Unsupported alarm WAV format')
        speech = source.readframes(source.getnframes())
    pcm = bytearray()
    for frequency in (880, 1100, 880):
        for n in range(4800):
            edge = min(1.0, n / 320, (4799 - n) / 320)
            sample = int(18500 * max(0, edge) * math.sin(2 * math.pi * frequency * n / 16000))
            pcm.extend(struct.pack('<h', sample))
        pcm.extend(b'\x00' * (1600 * 2))
    with BytesIO() as out:
        with wave.open(out, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(bytes(pcm) + speech)
        return out.getvalue()
