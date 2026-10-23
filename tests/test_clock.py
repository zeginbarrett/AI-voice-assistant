"""Offline regression tests for local clock replies and Ollama time context."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'windows' / 'sam_clock.py'
spec = importlib.util.spec_from_file_location('sam_clock', path)
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)

FIXED = datetime(2026, 10, 23, 1, 53, tzinfo=timezone(timedelta(hours=-5), 'CDT'))


class TestClock(unittest.TestCase):
    def test_common_clock_questions(self):
        for question in ("What time is it?", "What's the time?", "What is the current time?",
                         "Tell me the time", "Do you know what time it is?", "Time right now"):
            with self.subTest(question=question):
                self.assertEqual(clock.reply_for(question, FIXED), 'It is 1:53 AM.')

    def test_date_and_day_questions(self):
        self.assertEqual(clock.reply_for("What's today's date?", FIXED),
                         'Today is Friday, October 23, 2026.')
        self.assertEqual(clock.reply_for('What day of the week is it?', FIXED),
                         'Today is Friday.')
        self.assertEqual(clock.reply_for('What time and date is it?', FIXED),
                         'Today is Friday, October 23, 2026, and the time is 1:53 AM.')

    def test_unrelated_or_other_city_requests_not_intercepted(self):
        for question in ('What time does the store close?', 'What time is it in Tokyo?',
                         'What is the weather today?', 'Can you tell me a bedtime story?',
                         'Time travel is fun', 'What date did Apollo 11 land?'):
            with self.subTest(question=question):
                self.assertIsNone(clock.reply_for(question, FIXED))

    def test_context_includes_timezone_and_is_fresh(self):
        self.assertIn('Friday, October 23, 2026, 1:53:00 AM', clock.context(FIXED))
        self.assertIn('CDT', clock.context(FIXED))
        self.assertIn('-0500', clock.context(FIXED))
        self.assertNotEqual(clock.context(FIXED), clock.context(FIXED+timedelta(minutes=1)))


if __name__ == '__main__':
    unittest.main()
