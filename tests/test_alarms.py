"""Offline regression tests for SAM alarms; no ESP32 or Ollama required."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
import sys
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))
from sam_alarms import AlarmManager, alarm_chime

AT = datetime(2026, 10, 23, 18, 0, 0)  # Friday, local PC time


class TestAlarms(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sam_alarms.json'
        self.mgr = AlarmManager(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_daily_and_weekday_recur_persist(self):
        self.assertIn('every day at 6:30 AM', self.mgr.handle('Set an alarm every day at 6:30 AM', AT))
        self.assertIn('weekdays at 6:00 AM', self.mgr.handle('Set an alarm on weekdays at 6 AM', AT))
        new = AlarmManager(self.path)
        self.assertEqual(len(new._alarms), 2)
        day = datetime.fromisoformat(new._alarms[1]['next_at']).strftime('%A')
        self.assertEqual(day, 'Monday')

    def test_friday_alarm(self):
        self.assertIn('every Friday at 5:30 AM',
                      self.mgr.handle('set alarm every Friday at 5:30 am', AT))
        day = datetime.fromisoformat(self.mgr._alarms[0]['next_at']).date().isoformat()
        self.assertEqual(day, '2026-10-30')

    def test_relative_and_tomorrow(self):
        self.assertIn('6:10 PM', self.mgr.handle('set alarm in ten minutes', AT))
        self.assertIn('7:00 AM', self.mgr.handle('wake me up tomorrow at 7 AM', AT))

    def test_ambiguous_am_pm_not_created(self):
        self.assertIn('AM or PM', self.mgr.handle('set an alarm at 6:30', AT))
        self.assertEqual(self.mgr._alarms, [])

    def test_due_and_stop(self):
        self.mgr.handle('set an alarm in 1 minute', AT)
        self.mgr.poll(AT + timedelta(seconds=61))
        self.assertTrue(self.mgr.should_ring(AT + timedelta(seconds=61)))
        self.assertEqual(self.mgr.mark_ring(AT + timedelta(seconds=61)), 'Alarm')
        self.assertFalse(self.mgr.should_ring(AT + timedelta(seconds=70)))
        self.assertTrue(self.mgr.should_ring(AT + timedelta(seconds=82)))
        self.assertEqual(self.mgr.handle('stop the alarm', AT + timedelta(seconds=83)), 'Alarm stopped.')
        self.assertFalse(self.mgr.should_ring(AT + timedelta(seconds=84)))

    def test_snooze_persists(self):
        self.mgr.handle('set alarm in one minute', AT)
        self.mgr.poll(AT + timedelta(minutes=1))
        self.assertIn('Snoozed until 6:11 PM',
                      self.mgr.handle('snooze for ten minutes', AT + timedelta(minutes=1)))
        self.assertEqual(len(AlarmManager(self.path)._alarms), 1)

    def test_cancel_and_list(self):
        self.mgr.handle('set alarm in 5 minutes', AT)
        self.mgr.handle('set alarm in 10 minutes', AT)
        self.assertIn('1.', self.mgr.handle('list my alarms', AT))
        self.assertIn('Canceled', self.mgr.handle('cancel alarm number one', AT))
        self.assertEqual(len(self.mgr._alarms), 1)
        self.assertIn('All scheduled', self.mgr.handle('cancel all alarms', AT))
        self.assertEqual(AlarmManager(self.path)._alarms, [])

    def test_recurrence_advances(self):
        self.mgr.handle('set an alarm every day at 6:30 PM', AT)
        self.mgr.poll(AT + timedelta(minutes=31))
        self.assertIsNotNone(self.mgr._active)
        next_day = datetime.fromisoformat(self.mgr._alarms[0]['next_at']).date().isoformat()
        self.assertEqual(next_day, '2026-10-24')

    def test_two_simultaneous_due_alarms_are_queued(self):
        self.mgr.handle('set alarm in 1 minute', AT)
        self.mgr.handle('set alarm in 1 minute', AT)
        self.mgr.poll(AT + timedelta(minutes=1))
        self.assertEqual(len(self.mgr._pending), 1)
        self.mgr.handle('stop alarm', AT + timedelta(minutes=1))
        self.mgr.poll(AT + timedelta(minutes=1, seconds=1))
        self.assertIsNotNone(self.mgr._active)

    def test_old_oneoff_not_sounded_hours_late(self):
        self.mgr.handle('set alarm in one minute', AT)
        self.mgr.poll(AT + timedelta(hours=3))
        self.assertIsNone(self.mgr._active)
        self.assertEqual(self.mgr._alarms, [])

    def test_unrelated_requests_not_intercepted(self):
        self.assertIsNone(self.mgr.handle('tell me about alarm clocks', AT))
        self.assertIsNone(self.mgr.handle('could you make me a sandwich', AT))

    def test_alarm_chime_is_16khz_mono_pcm(self):
        with BytesIO() as stream:
            with wave.open(stream, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b'\x00\x00' * 1600)
            audio = alarm_chime(stream.getvalue())
        with wave.open(BytesIO(audio), 'rb') as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getframerate(), 16000)
            self.assertGreater(w.getnframes(), 1600)


if __name__ == '__main__':
    unittest.main()
