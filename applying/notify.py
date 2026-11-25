"""Tells you when something happens during an apply run. Handlers are pluggable.

notify(event) hands one event to every handler in HANDLERS. Today there are two: a terminal line and a
beep. A phone, chat or webhook handler later is one more function added with register().

An event is a plain dict:
    number   this job's place in the run (3)         total   jobs in the run (12)
    title    the job title                           company the employer
    state    "parked"                                reason  why (see applying/blocked.py)
    url      the link that was being opened
Handlers must never raise: a notification failing must not stop an application run (notify() also
guards each handler).
"""

import config.apply_settings as _cfg
from core.console import tag

try:
    import winsound   # Windows only
except ImportError:   # pragma: no cover
    winsound = None


def terminal_handler(event: dict) -> None:
    """[PARKED 3/12] Job title - Company: reason"""
    place = f"{event['number']}/{event['total']}" if event.get("number") and event.get("total") else ""
    name = f"{event.get('state', 'parked')} {place}".strip().upper()
    tag(name, f"{event.get('title', '?')} - {event.get('company', '?')}: {event.get('reason', '')}", "warn")


def beep_handler(event: dict) -> None:
    """One short beep, only if NOTIFY_BEEP is on and the machine can beep."""
    if not getattr(_cfg, "NOTIFY_BEEP", True) or winsound is None:
        return
    try:
        winsound.Beep(880, 250)
    except Exception:
        pass


HANDLERS = [terminal_handler, beep_handler]


def register(handler) -> None:
    """Add a handler: a function that takes the event dict."""
    HANDLERS.append(handler)


def notify(event: dict) -> None:
    for handler in list(HANDLERS):
        try:
            handler(event)
        except Exception:
            pass
