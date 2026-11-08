"""What rating.py flags in a posting's "Special notes". Edit freely.

Each entry is (note shown to you, regular expression), matched ignoring case against the
job's title, location and description. Every entry that matches is shown. Notes about work
setup, years of experience and degree are added by the code as well; see job_info.py.
"""

NOTE_PATTERNS = [
    ("Contract / temporary", r"\bcontract(or)?\b|\btemporary\b|\btemp[- ]to[- ]hire\b|\bc2c\b|\b1099\b|\bcontract[- ]to[- ]hire\b"),
    ("Internship / apprenticeship", r"\bintern(ship)?\b|\bapprentice(ship)?\b|\bco-?op\b"),
    ("Part-time", r"\bpart[- ]time\b"),
    ("No visa sponsorship offered", r"(unable|not able|cannot|can't|will not|won't|not) (to )?(provide |offer )?(visa )?sponsor|without sponsorship|no (visa )?sponsorship"),
    ("Offers visa sponsorship", r"(visa )?sponsorship (is )?(available|provided|offered)|will sponsor"),
    ("Security / background check", r"background check|public trust|polygraph|drug (test|screen)"),
    ("Travel required", r"travel (up to |approximately |around )?\d{1,3}\s?%|\d{1,3}\s?% travel|willing to travel|travel required|frequent travel"),
    ("Shift / on-call work", r"on[- ]call|night shifts?|rotating shifts?|weekend (work|coverage|hours)|24/7"),
    ("Relocation help", r"relocation (assistance|bonus|package|support)"),
    ("Posted by a recruiter or agency", r"\bour client\b|on behalf of (our|a) client|staffing (firm|agency)"),
    ("Mentions equity or bonus", r"\bequity\b|stock options|signing bonus|annual bonus"),
    ("Unpaid or commission-only", r"\bunpaid\b|commission[- ]only|volunteer position"),
]