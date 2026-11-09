"""Settings for apply_jobs.py (the form filler). Edit freely.

apply_jobs.py opens each application in a browser window, fills in everything it can,
and then STOPS. It never clicks Submit: you read the form, fix anything wrong, and send it.
"""

from config.settings import PROJECT_DIR

# ------------------------------------------------------------------- which jobs
APPLY_MIN_SCORE = 7        # only jobs scoring at least this
APPLY_MAX_PER_RUN = 5      # most jobs to open per run
APPLY_WINDOW_DAYS = 14     # only jobs scraped in the last N days

# ------------------------------------------------------------- which sites to fill
# True = fill applications on that site. "workday", "linkedin" and "indeed" are listed so you
# can opt in later, but their fillers are not built yet; turning them on only prints a notice.
ENABLED_SITES = {
    "greenhouse": True,
    "lever": True,
    "ashby": True,
    "workday": True,
    "linkedin": True,   # opt-in: LinkedIn's terms forbid automation and it can restrict your account
    "indeed": False,     # opt-in: same risk
}

AUTO_FIND_LINKS = False
FIND_LINKS_MAX = 25   # most LinkedIn pages to read per run

LINKEDIN_CLICK_APPLY = True      # opt-in; set False to turn it off
LINKEDIN_CLICK_MAX = 10          # most LinkedIn postings to click through per run
LINKEDIN_CLICK_DELAY = (8, 20)   # random pause in seconds between postings
CHECK_STILL_OPEN = True
WORKDAY_AUTO_ADVANCE = True
WORKDAY_MAX_STEPS = 12
# ---------------------------------------------------------------------- browser
BROWSER_PROFILE_DIR = PROJECT_DIR / "browser_profile"  # keeps your logins between runs
HEADLESS = False           # leave False: you need to see and review the form
SLOW_MO_MS = 0             # slow every browser action by this many ms (try 100 to watch it work)
PAGE_TIMEOUT_MS = 30000    # how long to wait for a page to load

# -------------------------------------------------------------------- answers
LEARNED_ANSWERS_FILE = PROJECT_DIR / "learned_answers.json"  # answers you typed in, remembered
ASK_ABOUT_UNKNOWN = True   # True = stop and ask in the terminal when a question has no answer rule
DRAFT_FREE_TEXT = True     # True = the local model drafts answers to long "why us?" style questions
FREE_TEXT_MAX_WORDS = 120  # length limit for those drafts
