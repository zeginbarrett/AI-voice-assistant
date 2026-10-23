"""Trusted local Windows clock for SAM speech commands and AI context."""
from __future__ import annotations

from datetime import datetime
import re


def local_now() -> datetime:
    """Read the host's clock afresh on every request, including its UTC offset."""
    return datetime.now().astimezone()


def context(now: datetime | None = None) -> str:
    """Add live time context to Ollama requests; do not cache timestamps."""
    now = now if now is not None else local_now()
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    clock = now.strftime('%I:%M:%S %p').lstrip('0')
    zone = now.tzname() or 'local time'
    offset = now.strftime('%z')
    return (f"Windows PC clock right now: {date}, {clock}, "
            f"time zone {zone} (UTC offset {offset or 'unknown'}). "
            "This is current only for this request; use it for questions "
            "about the date, time and relative dates. Do not pretend "
            "a reminder was scheduled unless a reminder tool confirms it.")


def reply_for(question: str, now: datetime | None = None) -> str | None:
    """Answer direct local-clock requests without involving the language model.

    Return None for unrelated prompts or questions about other locations.
    """
    q = re.sub(r'\s+', ' ', question.casefold().replace('\u2019', "'")).strip(' \t\r\n.!?,')
    # The PC's time is not necessarily the time in another city or zone.
    if re.search(r'\b(?:it|now|time|date|today)\s+in\s+\w+', q):
        return None

    ask_time = bool(re.search(
        r"\b(?:what(?:'s| is) (?:the )?(?:current |local )?time|"
        r"what time (?:is it|do you have)|"
        r"what time and date is it|"
        r"tell me (?:the |what )?(?:current |local )?time|"
        r"give me (?:the )?(?:current |local )?time|"
        r"do you know (?:what time it is|the time)|"
        r"(?:current|local) time|time right now)\b", q))
    ask_date = bool(re.search(
        r"\b(?:what(?:'s| is) (?:today's |the |the current )?date|"
        r"what date is it|what time and date is it|tell me (?:today's |the )?date|"
        r"today's date|what(?:'s| is) today|what year is it|"
        r"what(?:'s| is) the year)\b", q))
    ask_day = bool(re.search(
        r"\b(?:what(?:'s| is) (?:the )?day(?: of the week)?|"
        r"what day (?:of the week is it|is (?:it|today))|tell me (?:the )?day(?: of the week)?)\b", q))
    if not (ask_time or ask_date or ask_day):
        return None

    now = now if now is not None else local_now()
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    clock = now.strftime('%I:%M %p').lstrip('0')
    if ask_time and (ask_date or ask_day):
        return f"Today is {date}, and the time is {clock}."
    if ask_date:
        return f"Today is {date}."
    if ask_day:
        return f"Today is {now.strftime('%A')}."
    return f"It is {clock}."
