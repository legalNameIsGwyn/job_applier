"""When a job needs you: the Blocked signal and the one place that decides "park it or ask you".

The fillers (workday.py, generic.py, form_filler.py) reach spots where they cannot go on without you:
no Apply button, a sign-in page, a form they can't find, a required question with no answer. At each
spot they call  stop_or_ask(...)  instead of  ask(...):

    parking on   (a normal run)        raises Blocked(reason). apply_jobs.py catches it, parks the job
                                       on the saved list, closes its page and moves on.
    parking off  (apply_jobs.py --parked, you are present)
                                       asks you in the terminal, like before.

Whether parking is on is decided once per run by set_parking(). If nobody calls it, PARK_BLOCKED in
config/apply_settings.py decides. The tool never tries to solve or get around a bot check: it parks.
"""

import config.apply_settings as _cfg

# Why a job was blocked. The value is what is stored and shown, so keep these short and stable.
NO_APPLY_BUTTON = "no Apply button found"
BOT_CHECK = "bot or human check"
SIGN_IN = "sign-in needed"
NO_FORM = "application form not found"
NO_CONTINUE = "Continue button not found"
UNKNOWN_QUESTION = "unknown required question"
PAGE_ERRORS = "the site reported errors on a page"
STUCK = "the page did not change"

_parking: bool | None = None   # None = use PARK_BLOCKED from config/apply_settings.py


class Blocked(Exception):
    """The job can't go on without you. `reason` is one of the constants above; `detail` adds specifics
    (for example the text of the question that had no answer)."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)

    def __str__(self) -> str:
        return f"{self.reason}: {self.detail}" if self.detail else self.reason


def set_parking(on: bool | None) -> None:
    """Choose for this run: True = park blocked jobs, False = ask you, None = go back to the config value."""
    global _parking
    _parking = on


def parking_enabled() -> bool:
    return bool(getattr(_cfg, "PARK_BLOCKED", True)) if _parking is None else _parking


def stop_or_ask(reason: str, prompt: str, ask, detail: str = "") -> str:
    """At a spot that needs you: raise Blocked when parking, otherwise show `prompt` through `ask` and
    return your reply."""
    if parking_enabled():
        raise Blocked(reason, detail)
    return ask(prompt)
