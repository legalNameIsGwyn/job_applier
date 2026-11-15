"""Generic profile: a template to copy. Every setting below is commented out, so this profile changes nothing.

Create a real profile from it with:   python -m tools.profile new NAME
The wizard writes a profile.py containing only what you answered. To change more later, copy a line from
here into your profile's profile.py, remove the leading "# ", and edit the value.

  python -m tools.profile show NAME    what your profile changes, and where each value comes from
  python -m tools.profile check NAME   validate it (prompts fill in, patterns compile, resume exists)

A profile can extend another so you only list the differences:   EXTENDS = "software"
(one parent for now). Lists and prompts are replaced whole, not merged.
Settings not listed here (files, database, browser, scraping speed, timeouts) are the same for every profile.
"""

# ------------------------------------------------------------------ what to search for
# SEARCH_TERMS = ["help desk technician", "IT support specialist"]   # searched on every site, then merged
# LOCATION = "Norfolk, VA"
# SITES = ["linkedin", "indeed"]
# RESULTS_WANTED = 50            # per site, per search term
# HOURS_OLD = 72                 # only postings newer than this
# LINKEDIN_RESULTS_WANTED = 50
# MAX_APPLICANTS = 25            # skip LinkedIn jobs with more applicants; None = don't filter
# KEEP_UNKNOWN_APPLICANTS = True

# ------------------------------------------------------------------ which jobs to skip
# SENIOR_TITLE_WORDS = ["senior", r"sr\.?", "staff", "principal", "lead", "manager", "director"]
# LEVEL_SUFFIX_PATTERN = r"\b(?:engineer|developer|analyst)\s*(?:iii|iv|v|3|4|5)\b"
# BLOCKED_COMPANIES = ["robert half", "randstad"]   # staffing agencies to skip
# MAX_MIN_YEARS = 2              # skip a posting only if EVERY experience requirement is above this
# MY_YEARS_EXPERIENCE = None     # None = counted from this profile's resume.json
# BLOCKER_PATTERNS = [r"security clearance", r"u\.?s\.? citizens? only"]   # scored 0 without asking the model

# ------------------------------------------------------------------ scoring
# MIN_SCORE = 5                  # one cutoff: documents are made, jobs are listed and applications are offered at this score
# DEFAULT_MODEL_WEIGHT = 0.7     # before you rate jobs: 70% model score, 30% keyword score
# MIN_RATINGS = 50               # hand ratings needed before the scores are tuned
# FULL_TRUST_RATINGS = 100       # ratings at which the tuning is fully trusted
# RATING_BATCH_SIZE = 20
# OLLAMA_MODEL = "qwen2.5:7b"
# SCORING_PROMPT = """..."""     # keep its {placeholders}; the wizard can generate one for your field

# ------------------------------------------------------------------ keywords (keyword score and the "gaps" list)
# COMMON_TERMS = ["Excel", "QuickBooks"]            # terms postings in this field often ask for
# SKILL_ALIASES = {"Excel": ["excel", "spreadsheets"]}   # your resume skill -> other ways a posting writes it
# CASE_SENSITIVE_TERMS = ["Go", "Swift"]

# ------------------------------------------------------------------ documents
# MAKE_DOCS = True
# MAX_DOCS_PER_RUN = 10
# DOC_WINDOW_DAYS = 7
# MAX_PROJECTS = 3
# TAILOR_MAX_SKILLS = 12
# COVER_LETTER_GREETING = "Dear Hiring Team,"
# RESUME_FILENAME = "{name}_Resume"
# COVER_LETTER_FILENAME = "{name}_Cover_Letter"
# TAILOR_PROMPT = """..."""
# LETTER_PROMPT = """..."""
# STYLE_RULES = """..."""

# ------------------------------------------------------------------ applying
# APPLY_MAX_PER_RUN = 5
# APPLY_WINDOW_DAYS = 14
# ENABLED_SITES = {"greenhouse": True, "lever": True, "ashby": True, "workday": True, "generic": True}
# ANSWER_RULES = [...]           # see config/answers.py for the format
