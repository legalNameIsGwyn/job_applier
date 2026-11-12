"""Cheap rule-based filters that run before the (slow) model scoring.

filter_reason(title, company) is the early check. It needs no description, so it
runs before any description is fetched. Add the description and the years-of-
experience check runs too. Each returns a short reason string, or None to keep
the job. Filtered jobs are saved with that reason (status "filtered", score 0),
so they never get re-scraped and scored, and you can still see why with
`python show_jobs.py --bottom`.

The lists and numbers live in config/filter_rules.py; edit them there.
"""

import json
import re
from datetime import date
from pathlib import Path

from config.filter_rules import (
    BLOCKED_COMPANIES, LEVEL_SUFFIX_PATTERN, MAX_MIN_YEARS, MY_YEARS_EXPERIENCE, SENIOR_TITLE_WORDS,
)
from config.settings import RESUME_FILE

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


def my_years_experience() -> float:
    """Your years of work experience: MY_YEARS_EXPERIENCE if set, else counted from resume.json.

    Reads each role's "years" text ("03/2025 - 03/2026"; "Present" works). Overlapping roles
    are counted once. Returns 0.0 if the resume can't be read.
    """
    if MY_YEARS_EXPERIENCE is not None:
        return float(MY_YEARS_EXPERIENCE)
    try:
        roles = json.loads(Path(RESUME_FILE).read_text(encoding="utf-8")).get("experience", [])
    except (OSError, ValueError):
        return 0.0
    today = date.today()
    spans = []
    for role in roles:
        tokens = re.findall(r"(?:(\d{1,2})/)?(\d{4})|(present|current|now)", str(role.get("years", "")), re.I)
        if len(tokens) < 2:
            continue
        month = lambda t: today.year * 12 + today.month if t[2] else int(t[1]) * 12 + int(t[0] or 1)
        start, end = month(tokens[0]), month(tokens[1])
        if end > start:
            spans.append((start, end))
    total, last_end = 0, None
    for start, end in sorted(spans):
        if last_end is None or start > last_end:
            total += end - start
            last_end = end
        elif end > last_end:
            total += end - last_end
            last_end = end
    return round(total / 12, 1)


def years_shortfall(description: str) -> tuple[int, float] | None:
    """(years the posting asks for, years you have) when it asks for more than you have, else None."""
    asked, have = min_years_required(description or ""), my_years_experience()
    return (asked, have) if asked is not None and asked > have else None


def years_gap_note(description: str) -> str | None:
    """Text for the gaps list, e.g. 'Years of experience: asks 3+, you have about 1.4 (short by about 1.6)'."""
    short = years_shortfall(description)
    if not short:
        return None
    asked, have = short
    return f"Years of experience: asks {asked}+, you have about {have:g} (short by about {asked - have:.1f})"


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
