"""Settings for apply_jobs.py (the form filler). Edit freely.

apply_jobs.py opens each application in a browser window, fills in everything it can,
and then STOPS. It never clicks Submit: you read the form, fix anything wrong, and send it.
"""

from config.settings import PROJECT_DIR

# ------------------------------------------------------------------- which jobs
APPLY_MAX_PER_RUN = 1      # most jobs to open per run
APPLY_WINDOW_DAYS = 7     # only jobs scraped in the last N days

# ------------------------------------------------------------- which sites to fill
# True = fill applications on that site. Greenhouse, Lever, Ashby, Workday and "generic" have fillers.
# "linkedin" (Easy Apply) and "indeed" (Indeed's own forms) have NO filler yet: True or False only changes
# the notice shown for those jobs ("filler isn't built yet" vs "turned off").
ENABLED_SITES = {
    "greenhouse": True,
    "lever": True,
    "ashby": True,
    "workday": True,
    "linkedin": True,    # Easy Apply: no filler yet
    "indeed": False,     # Indeed's own forms: no filler yet    
    "generic": True,     
    # iCIMS, Taleo, SmartRecruiters, Workable, employer career pages...
}

GENERIC_AUTO_ADVANCE = True   # click Next/Continue on its own when nothing on the page needs you
GENERIC_MAX_STEPS = 10        # most pages to walk through on one application

AUTO_FIND_LINKS = False
FIND_LINKS_MAX = 25   # most LinkedIn pages to read per run

LINKEDIN_CLICK_APPLY = True      # opt-in; set False to turn it off
LINKEDIN_CLICK_MAX = 10          # most LinkedIn postings to click through per run
LINKEDIN_CLICK_DELAY = (8, 20)   # random pause in seconds between postings
CHECK_STILL_OPEN = True
WORKDAY_AUTO_ADVANCE = True
WORKDAY_MAX_STEPS = 12
# ---------------------------------------------------------------------- browser
BROWSER = "chromium"   # "firefox" or "chromium"
BROWSER_PROFILE_DIR = PROJECT_DIR / "browser_profile"   # keeps your logins between runs

# ------------------------------------------------------------ several jobs at once
PARALLEL_JOBS = 3   # applications open at once, each in its own terminal + browser window (1 = one at a time)
PARALLEL_PROFILE_DIR = PROJECT_DIR / "browser_profile_workers"   # temporary copies of your profile
HEADLESS = False           # leave False: you need to see and review the form
SLOW_MO_MS = 0             # slow every browser action by this many ms (try 100 to watch it work)
PAGE_TIMEOUT_MS = 30000    # how long to wait for a page to load

# -------------------------------------------------------------------- answers
LEARNED_ANSWERS_FILE = PROJECT_DIR / "data" / "learned_answers.json"  # answers you typed in, remembered
ASK_ABOUT_UNKNOWN = True   # True = stop and ask in the terminal when a question has no answer rule
DRAFT_FREE_TEXT = True     # True = the local model drafts answers to long "why us?" style questions
FREE_TEXT_MAX_WORDS = 120  # length limit for those drafts
DRAFT_SELF_CHECK = True    # True = the model checks each draft against your resume and removes claims the resume does not support

from config.profile_loader import apply_overrides  # noqa: E402
apply_overrides(globals())