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

# --------------------------------------------------- scored 0 without asking the model
# Postings matching any of these need a clearance or US citizenship.
BLOCKER_PATTERNS = [
    r"security clearance",
    r"\bts\s*/\s*sci\b",
    r"top[- ]secret",
    r"secret clearance",
    r"active clearance",
    r"clearance (is )?required",
    r"polygraph",
    r"(u\.?s\.?|united states) citizen(ship)?\s+(is\s+)?(required|only)",
    r"must be (a )?(u\.?s\.?|united states) citizen",
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
