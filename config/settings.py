"""General settings. Edit freely; nothing here needs code changes.

The code reads these values when it starts. Your resume is NOT in this folder:
it stays at RESUME_FILE below.
"""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the folder that contains main.py

DEFAULT_PROFILE = "software"   # the profile used when you don't pass --profile
MIN_SCORE = 5
ACTIVE_PROFILE = DEFAULT_PROFILE

# A CSV of jobs to click through and apply to by hand, next to each profile's applications folder.
CSV_LOG = True

# --------------------------------------------------------------------- files and folders
RESUME_FILE = PROJECT_DIR / "data" / "resume.json"                 # your resume data (stays outside config/)
DB_PATH = os.environ.get("JOBS_DB") or str(PROJECT_DIR / "data" / "jobs_db.sqlite")             # the jobs database
CALIBRATION_FILE = PROJECT_DIR / "data" / "calibration.json"       # score tuning learned from your ratings
APPLICATIONS_DIR = PROJECT_DIR / "data" /"applications"           # generated resumes and cover letters

# -------------------------------------------------------------------------- what to search
SITES = ["linkedin", "indeed"]
SEARCH_TERMS = [
    "junior software engineer",
    "software developer",
    "python developer",
    "associate software engineer",
]
LOCATION = "Norfolk, VA"
RESULTS_WANTED = 5   # per site, per search term
HOURS_OLD = 72    

LINKEDIN_RESULTS_WANTED = 5   # LinkedIn blocks big pulls
LINKEDIN_JOBSPY_FETCH_DESCRIPTIONS = False  # False = JobSpy won't open every job page
# main.py's slower fetcher fills descriptions in instead

# LinkedIn applicant-count filter (read from each job's public page)
MAX_APPLICANTS = 25              # skip LinkedIn jobs with more applicants than this; None = don't filter
KEEP_UNKNOWN_APPLICANTS = True   # keep jobs whose page shows no usable count


# ----------------------------------------------------------------------------- local model
# The OLLAMA_MODEL environment variable, if set, overrides the name below:
#   PowerShell:  $env:OLLAMA_MODEL = "qwen3.5:4b"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
REQUEST_TIMEOUT_SECONDS = 180      # a stuck model call is abandoned after this long
SCORING_TEMPERATURE = 0            # 0 = most repeatable scoring
WRITING_TEMPERATURE = 0.3          # a little variety for summaries and cover letters
DESCRIPTION_CHARS_SCORING = 2000   # how much of a posting the model reads when scoring
DESCRIPTION_CHARS_WRITING = 3000   # ...and when tailoring the resume / writing the letter
MAX_CONSECUTIVE_FAILURES = 3       # stop after this many model failures in a row

# ------------------------------------------------------------------------------- scraping
AVAILABLE_SITES = ["linkedin", "indeed"]  # sites the scraper knows how to handle
DEFAULT_RESULTS_WANTED = 10               # used when a caller doesn't say
DEFAULT_HOURS_OLD = 24
COUNTRY_INDEED = "USA"
DELAY_BETWEEN_SEARCH_TERMS = 5.0          # seconds
DESCRIPTION_FETCH_DELAY = (1.5, 3.5)      # random pause (min, max seconds) between LinkedIn pages
DESCRIPTION_FETCH_TIMEOUT = 20            # seconds per LinkedIn page
DESCRIPTION_FETCH_ATTEMPTS = 3            # tries per job before it is left for the next run (a 429 or a page with no text counts as a try)
RATE_LIMIT_BACKOFF_SECONDS = 30           # first wait after a 429; doubles/triples on repeats
RATE_LIMIT_STOP_AFTER_JOBS = None         # stop fetching for the whole run after this many jobs in a row end on a 429 (None = never; each job just gives up on its own)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ----------------------------------------------------------------------------- documents
MAKE_DOCS = True          # create a resume + cover letter automatically after scoring
MAX_DOCS_PER_RUN = None     # most NEW jobs to make documents for per run
DOC_WINDOW_DAYS = 7       # only consider jobs scraped in the last N days
MAX_PROJECTS = 3          # projects shown on the resume
TAILOR_MAX_SKILLS = 12    # skills the model may move to the front (all skills are still listed)
FONT = "Calibri"
COVER_LETTER_GREETING = "Good day,"
COVER_LETTER_SIGN_OFF = "Sincerely,"

# ------------------------------------------------------------------------------ file names
# Names are built from your resume.json and the job. ".docx" is added for you.
# Available placeholders (letters, digits, "-", "_" and "." only; anything else becomes "_"):
#   {name}     your full name from resume.json, e.g. Jane_Doe
#   {first}    first word of your name         {last}   last word of your name
#   {company}  the job's company               {title}  the job title
#   {hash}     6 characters unique to the posting URL   {date}  today, YYYY-MM-DD
# The folder name must stay unique per job (keep {hash}); it is how finished jobs are recognized.
RESUME_FILENAME = "{name}_Resume"
COVER_LETTER_FILENAME = "{name}_Cover_Letter"
APPLICATION_FOLDER = "{company}_{title}_{hash}"
NOTES_FILENAME = "notes.txt"    # the review notes saved in each application folder

# ------------------------------------------------------------------- scores and rating
DEFAULT_MODEL_WEIGHT = 0.7      # before you rate any jobs: 70% model score, 30% keyword score
MIN_RATINGS = 50               # fewest hand ratings needed to tune the scores
FULL_TRUST_RATINGS = 100        # below this many ratings the fit is pulled toward the defaults (fully trusted at this many)
RATING_BATCH_SIZE = 20          # jobs shown per `python rating.py`
RATING_DESC_CHARS = 900         # how much of each description is shown while rating
RATING_DESCRIPTION = "summary"  # "summary", "excerpt" (first RATING_DESC_CHARS characters) or "full"
RATING_SUMMARY_BULLETS = 3      # bullets per section
RATING_SHOW_MODEL_NOTES = True  # show the model's matched skills and gaps
FIT_ON_ALL_RATINGS = True       # True = every rating you've ever made counts; False = latest batch only
CALIBRATION_HISTORY_LIMIT = 50  # past calibrations kept in calibration.json
SHOW_DEFAULT_COUNT = 10         # rows printed by `python show_jobs.py`

SUMMARY_AFTER_RUN = True      # print the summary at the end of main.py
SUMMARY_DAYS = 1              # how far back "new" reaches
SUMMARY_TOP = 10              # best matches listed
SUMMARY_DIR = PROJECT_DIR / "data" / "reports"   # optional: where --html reports are saved

# ------------------------------------------------------------------- rating

RATING_CARD_WIDTH = None       # None = fit the terminal; or a number like 90
RATING_CARD_MAX_WIDTH = 100    # cap used when RATING_CARD_WIDTH is None

COMPAT_DETAIL = True      # the extra model call for jobs at or above MIN_SCORE
HARD_REQ_CAP = 60         # detailed % is capped here when a hard requirement is missing
HARD_REQ_KINDS = ("clearance", "work_authorization")   # a missing required item of these caps the detailed %; licenses and certifications are only flagged
DROP_ON_MISSING_KINDS = ("clearance",)   # a required item of these kinds you lack DROPS the job after the detailed check. Add "work_authorization" to drop those too; licenses and certifications are only flagged

MAX_BRIDGE_LINES = 2      # bridge lines proposed per job

# Tailoring mode: "auto", "standard", "bridge" or "boilerplate".
# auto picks one per job from its compatibility percentage.
TAILOR_MODE = "auto"
TAILOR_AUTO_BRIDGE_BELOW = 70       # compatibility under this uses bridge
TAILOR_AUTO_BOILERPLATE_BELOW = 30  # compatibility under this uses boilerplate

# Console look: None = automatic (colors only in a terminal, symbols only if it can show them)
# Console look
CONSOLE_COLOR = None   # None = automatic (colors only in a terminal), True = always color, False = never
CONSOLE_LINKS = None   # None = automatic, True = clickable "open posting" links, False = always show the full URL

# Colors. Each value is a name from `python -m core.console --colors`, a number 0-255, or "#rrggbb".
# "auto" (suitability, compat) = green / yellow / gray depending on how high the number is.
# See your changes without running the pipeline:   python -m core.console

CONSOLE_COLORS = {
    "heading": "white",       # JOB SCRAPER, stage titles, section titles
    "label": "gray",          # profile, mode, suitability, compat ...
    "value": "white",         # the values next to those labels
    "rule": "blue",           # the line after a stage title
    "job_title": "white",     # job block: the title
    "company": "sky",         # job block: company
    "location": "teal",       # job block: where
    "suitability": "auto",    # job block: the 0-10 score
    "compat": "auto",         # job block: compatibility percentage
    "site": "pink",           # job block: where it was posted
    "docs": "lavender",       # job block: the documents mode
    "salary": "lime",         # job block: pay
    "blocker": "red",         # job block: hard requirements you don't meet
    "license": "yellow",      # job block: a required license or certification you don't list
    "about": "blue",          # job block: short description
    "requires": "gold",       # job block: requirements
    "has": "green",           # job block: your matching skills
    "gaps": "orange",         # job block: what you're missing
    "notes": "magenta",       # job block: contract, work setup ...
    "link": "gray",           # job block: link to the posting
}

CONSOLE_TAG_COLORS = {        # the [TAG] at the start of a line
    "SCRAPER": "cyan", "FILTER": "yellow", "SCORER": "blue", "PIPELINE": "blue", "DEDUPE": "gray",
    "COMPAT": "sky", "DOCS": "magenta", "APPLY": "green", "BRIDGE": "orange", "CSV": "gold",
    "SUMMARY": "white", "TRACK": "pink",
}

from config.profile_loader import apply_overrides  # noqa: E402
apply_overrides(globals())