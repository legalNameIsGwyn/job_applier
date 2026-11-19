"""Rules for skipping jobs. Edit the lists and numbers; no code changes needed.

Patterns are regular expressions (case-insensitive) in raw strings, so write a
backslash once, e.g. r"\bsenior\b".
"""

# ------------------------------------------------- skipped before descriptions are fetched
# Titles that signal a senior role. Matched as whole words.
SENIOR_TITLE_WORDS = [
    "senior", r"sr\.?", "staff", "principal", "lead", "manager", "director",
    "head of", "architect", "vp", "vice president", "chief", "distinguished",
]

# "Software Engineer III", "Developer 4", ... (I, II, 1 and 2 are allowed)
LEVEL_SUFFIX_PATTERN = r"\b(?:engineer|developer|analyst|programmer|tester|administrator)\s*(?:iii|iv|v|3|4|5)\b"

# Staffing agencies to skip (matched as whole words inside the company name). Empty the list to disable.
BLOCKED_COMPANIES = [
    "robert half", "randstad", "teksystems", "kforce", "insight global", "jobot", "apex systems",
    "cybercoders", "aerotek", "adecco", "manpower", "kelly services", "hays", "collabera",
    "experis", "staffmark", "judge group", "yoh",
]

# ------------------------------------------------------------ skipped after the description
# Reject only when EVERY experience requirement in the posting asks for more than this
# many years (you have roughly 1.5). "1-3 years" passes; "3+ years" does not.
MAX_MIN_YEARS = 2

# Your years of work experience, used to flag "asks 3+ years, you have about 1.4".
# None = work it out from the dates in data/resume.json (overlapping roles count once;
# internships, projects and school are not counted). Or set a number, e.g. 1.5.
MY_YEARS_EXPERIENCE = None

# Postings matching any of these need a clearance or US citizenship.
# A pattern with "citizen" in it is a citizenship rule; the rest are clearance rules.
BLOCKER_PATTERNS = [
    # ---- clearance
    r"security clearance",
    r"\bts\s*/\s*sci\b",
    r"top[- ]secret",
    r"\b(secret|ts)([- ]level)? (security )?clearance",
    r"\bsecret (or|and) (higher|above)",
    r"\binterim secret",
    r"active (dod )?clearance",
    r"clearance (is )?required",
    r"clearance( level)?\s*[:\-]\s*(secret|top secret|ts|confidential|public trust)",
    r"clearance[- ]eligible",
    r"(hold|possess|maintain|obtain)( and maintain)? (an?|the) (active |current |valid )?(dod )?clearance",
    r"(hold|obtain|eligible for|able to obtain) (an?|the) public trust",
    r"public trust (position|clearance|determination|investigation)",
    r"access to classified (information|material|materials|systems|networks)",
    r"polygraph",
    # ---- citizenship
    r"(u\.?s\.?|united states) citizen(ship)?\s+(is\s+)?(required|only)",
    r"must be (a )?(u\.?s\.?|united states) citizen",
    r"\bcitizen of the (u\.?s\.?|united states)",
    r"requires? (u\.?s\.?|united states) citizenship",
    r"citizenship (is )?required",
    r"u\.?s\.? citizens? only",
]

# ...unless the posting says one of these (e.g. "no clearance required").
NO_BLOCKER_PATTERN = (
    r"no (security )?clearance"
    r"|clearance (is )?not required"
    r"|not require (a )?(security )?clearance"
    r"|without (a )?clearance"
)

from config.profile_loader import apply_overrides  # noqa: E402
apply_overrides(globals())