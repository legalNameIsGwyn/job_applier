"""General settings. Edit freely; nothing here needs code changes.

The code reads these values when it starts. Your resume is NOT in this folder:
it stays at RESUME_FILE below.
"""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the folder that contains main.py

# --------------------------------------------------------------------- files and folders
RESUME_FILE = PROJECT_DIR / "data" / "resume.json"                 # your resume data (stays outside config/)
DB_PATH = str(PROJECT_DIR / "data" / "jobs_db.sqlite")             # the jobs database
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
RESULTS_WANTED = 50   # per site, per search term
HOURS_OLD = 72        
LINKEDIN_RESULTS_WANTED = 15   # LinkedIn blocks big pulls
LINKEDIN_JOBSPY_FETCH_DESCRIPTIONS = False  # False = JobSpy won't open every job page
# main.py's slower fetcher fills descriptions in instead

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
RATE_LIMIT_BACKOFF_SECONDS = 30           # first wait after a 429; doubles/triples on repeats
RATE_LIMIT_STOP_AFTER = 3                 # give up fetching descriptions after this many 429s in a row
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ----------------------------------------------------------------------------- documents
MAKE_DOCS = True          # create a resume + cover letter automatically after scoring
DOC_MIN_SCORE = 6         # only jobs scoring at least this get documents
MAX_DOCS_PER_RUN = 10     # most NEW jobs to make documents for per run
DOC_WINDOW_DAYS = 7       # only consider jobs scraped in the last N days
MAX_PROJECTS = 3          # projects shown on the resume
TAILOR_MAX_SKILLS = 12    # skills the model may move to the front (all skills are still listed)
FONT = "Calibri"
COVER_LETTER_GREETING = "Dear Hiring Team,"
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
MIN_RATINGS = 10                # fewest hand ratings needed to tune the scores
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
SUMMARY_MIN_SCORE = 6         # what counts as a match
SUMMARY_DIR = PROJECT_DIR / "reports"   # optional: where --html reports are saved