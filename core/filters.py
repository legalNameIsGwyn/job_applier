"""Cheap rule-based filters that run before the (slow) model scoring.

filter_reason(title, company) is the early check. It needs no description, so it
runs before any description is fetched. Add the description and the years-of-
experience check runs too. Each returns a short reason string, or None to keep
the job. Filtered jobs are saved with that reason (status "filtered", score 0),
so they never get re-scraped and scored, and you can still see why with
`python show_jobs.py --bottom`.

The lists and numbers live in config/filter_rules.py; edit them there.
"""

import re

from config.filter_rules import BLOCKED_COMPANIES, LEVEL_SUFFIX_PATTERN, MAX_MIN_YEARS, SENIOR_TITLE_WORDS

_SENIOR_RE = re.compile(r"(?<!\w)(?:" + "|".join(SENIOR_TITLE_WORDS) + r")(?!\w)", re.I)
_LEVEL_RE = re.compile(LEVEL_SUFFIX_PATTERN, re.I)

_WORD_NUMBERS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"])}
_NUM = r"(\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
_YEARS_RE = re.compile(
    rf"(?<![\d.]){_NUM}\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*{_NUM}\s*\+?)?\s*(?:years?|yrs?)\b",
    re.I,
)


def _to_int(token: str) -> int:
    token = token.lower()
    return _WORD_NUMBERS[token] if token in _WORD_NUMBERS else int(token)


def min_years_required(description: str) -> int | None:
    """Smallest 'N years of experience' requirement in the text, or None if it names none.

    Only numbers with the word "experience" nearby count, so "25 years in business"
    is ignored. The SMALLEST requirement is used, so alternatives like "5 years, or a
    degree plus 2 years" never cause a wrongful rejection.
    """
    found = []
    for m in _YEARS_RE.finditer(description or ""):
        window = description[max(0, m.start() - 40): m.end() + 100]
        if re.search(r"experience|\bexp\b", window, re.I):
            found.append(_to_int(m.group(1)))
    return min(found) if found else None


def filter_reason(title: str, company: str, description: str | None = None) -> str | None:
    """Return why a job should be skipped, or None to keep it."""
    m = _SENIOR_RE.search(title or "")
    if m:
        return f"Filtered: senior-level title ('{m.group(0)}')"
    m = _LEVEL_RE.search(title or "")
    if m:
        return f"Filtered: higher-level title ('{m.group(0)}')"

    name = (company or "").lower()
    for blocked in BLOCKED_COMPANIES:
        if re.search(r"(?<!\w)" + re.escape(blocked) + r"(?!\w)", name):
            return f"Filtered: blocked company ('{blocked}')"

    if description:
        years = min_years_required(description)
        if years is not None and years > MAX_MIN_YEARS:
            return f"Filtered: requires {years}+ years of experience"
    return None
