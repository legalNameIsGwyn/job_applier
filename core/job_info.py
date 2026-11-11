"""Facts pulled out of a job posting: salary, special notes and a short summary. No model needed."""

import re

from config.job_notes import NOTE_PATTERNS
from core.filters import min_years_required


# ------------------------------------------------------------------------------- salary


def _number(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n > 0 else None  # n == n is False for NaN


def format_salary(min_amount, max_amount, interval=None, currency=None) -> str:
    """The salary fields JobSpy returns, as readable text ('' if the posting gave none)."""
    lo, hi = _number(min_amount), _number(max_amount)
    if lo is None and hi is None:
        return ""
    symbol = {"USD": "$", "CAD": "CA$", "GBP": "£", "EUR": "€"}.get(str(currency or "USD").upper(), "")
    money = lambda v: f"{symbol}{v:,.0f}"
    span = money(lo) if hi is None or lo == hi else money(hi) if lo is None else f"{money(lo)} - {money(hi)}"
    unit = {"yearly": "per year", "monthly": "per month", "weekly": "per week", "daily": "per day",
            "hourly": "per hour"}.get(str(interval or "").lower(), "")
    return f"{span} {unit}".strip()


_AMOUNT = r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?"
_PER = r"\s*(?:/|per|an?)\s*(?:hour|hr|year|yr|annum|month)"
_RANGE_RE = re.compile(rf"{_AMOUNT}\s*(?:-|–|—|to)\s*(?:{_AMOUNT}|\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?\s?[kK]?)(?:{_PER})?", re.I)
_SINGLE_RE = re.compile(rf"{_AMOUNT}{_PER}", re.I)


def salary_from_text(description: str) -> str:
    """A pay range or rate quoted in the posting text ('' if none is found)."""
    text = " ".join((description or "").split())
    for regex in (_RANGE_RE, _SINGLE_RE):
        for m in regex.finditer(text):
            found = m.group(0).strip(" .,;")
            nums = [float(n.replace(",", "")) * (1000 if k else 1)
                    for n, k in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s?([kK])?", found)]
            if nums and min(nums) >= 10:   # ignores tiny numbers that aren't pay
                window = text[max(0, m.start() - 60): m.end() + 40].lower()
                if re.search(r"salary|pay|compensation|wage|rate|hour|year|annual|base|range|\bper\b|/", window):
                    return found
    return ""


# -------------------------------------------------------------------------- special notes


def special_notes(title: str, location: str, description: str) -> list[str]:
    """Short flags worth knowing before you rate or apply."""
    text = f"{title}\n{location}\n{description or ''}"
    notes = []

    setup = [name for name, pattern in (("Remote", r"\bremote\b"), ("Hybrid", r"\bhybrid\b"),
                                       ("On-site", r"\bon[- ]?site\b|\bin[- ]office\b|\bin[- ]person\b"))
             if re.search(pattern, text, re.I)]
    if setup:
        notes.append("Work setup mentioned: " + " / ".join(setup))

    years = min_years_required(description or "")
    if years:
        notes.append(f"Asks for {years}+ year(s) of experience")

    degree = re.search(r"\b(bachelor'?s?|master'?s?|ph\.?d|associate'?s?) (degree|of science|of arts)|\bB\.?S\.?\b(?= (in|or))", text, re.I)
    if degree:
        notes.append(f"Mentions a degree: {degree.group(0).strip()}")

    for label, pattern in NOTE_PATTERNS:
        if re.search(pattern, text, re.I):
            notes.append(label)
    return notes


# -------------------------------------------------------------------------------- summary

_SECTIONS = {
    "Responsibilities": r"responsibilit|what you.?ll do|you will|duties|the role|day[- ]to[- ]day|in this role",
    "Requirements": r"requirement|qualification|you have|what you.?ll need|must have|skills|looking for|who you are|minimum|experience",
    "Nice to have": r"nice to have|preferred|bonus|plus|desired",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•·▪●◦–]|\d+[.)])\s+(.*\S)")


def summary_points(description: str, per_section: int = 3, width: int = 140) -> dict[str, list[str]]:
    """The key bullets of a posting, grouped as Responsibilities / Requirements / Nice to have.

    Uses the posting's own bullet lists under their headings. If the text has no bullets
    (many descriptions are flattened), it falls back to the sentences that mention
    requirements or duties.
    """
    out: dict[str, list[str]] = {name: [] for name in _SECTIONS}
    section = None
    for line in (description or "").splitlines():
        stripped = line.strip(" \t*#_:")
        bullet = _BULLET_RE.match(line)
        if bullet:
            if section and len(out[section]) < per_section:
                out[section].append(_clip(bullet.group(1), width))
        elif stripped and len(stripped) < 70:  # a short line that is probably a heading
            section = next((name for name, pat in _SECTIONS.items() if re.search(pat, stripped, re.I)), section)
    if any(out.values()):
        return {k: v for k, v in out.items() if v}

    sentences = re.split(r"(?<=[.!?])\s+", " ".join((description or "").split()))
    for s in sentences:
        for name, pattern in (("Requirements", r"requir|must|experience (with|in)|proficien|knowledge of|degree"),
                              ("Responsibilities", r"responsible|you will|design|develop|build|maintain|collaborate")):
            if len(out[name]) < per_section and 25 <= len(s) and re.search(pattern, s, re.I):
                out[name].append(_clip(s, width))
                break
    return {k: v for k, v in out.items() if v}


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."