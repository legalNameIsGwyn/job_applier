"""Work out which applicant-tracking system (ATS) a job link belongs to."""

import re
from urllib.parse import urlsplit, urlunsplit

ATS_PATTERNS = {
    "greenhouse": r"(boards|job-boards)(\.eu)?\.greenhouse\.io|[?&]gh_jid=",
    "lever": r"jobs(\.eu)?\.lever\.co",
    "ashby": r"jobs\.ashbyhq\.com",
    "workday": r"myworkdayjobs\.com|\.workday\.com",
    "linkedin": r"linkedin\.com",
    "indeed": r"indeed\.com",
    # Other applicant systems. They have no dedicated filler; generic.py handles all of them.
    "icims": r"icims\.com",
    "taleo": r"taleo\.net",
    "successfactors": r"successfactors\.(com|eu)|jobs\.sap\.com",
    "smartrecruiters": r"smartrecruiters\.com",
    "workable": r"apply\.workable\.com|workable\.com/j/",
    "bamboohr": r"bamboohr\.com",
    "jobvite": r"jobvite\.com",
    "breezy": r"breezy\.hr",
    "recruitee": r"recruitee\.com",
    "oracle": r"oraclecloud\.com",
    "ukg": r"ultipro\.com|ukg\.com",
    "paylocity": r"paylocity\.com",
    "adp": r"adp\.com",
    "jazzhr": r"applytojob\.com|jazz\.co",
    "rippling": r"rippling\.com",
    "teamtailor": r"teamtailor\.com",
    # Job boards that only redirect or aggregate: nothing to fill.
    "jobboard": r"ziprecruiter\.com|glassdoor\.com|monster\.com|simplyhired\.com|careerbuilder\.com|dice\.com",
}

# Named systems that generic.py fills.
GENERIC_SITES = {"icims", "taleo", "successfactors", "smartrecruiters", "workable", "bamboohr", "jobvite",
                 "breezy", "recruitee", "oracle", "ukg", "paylocity", "adp", "jazzhr", "rippling", "teamtailor",
                 "custom"}  # "custom" = any other employer website

# Stored as a job's apply_url when its LinkedIn page was checked and has no employer link
# (typically LinkedIn Easy Apply). Distinguishes "checked, none" from "never checked" (empty).
NO_LINK = "none"
CLICK_CHECKED = "none:clicked"   # also tried by clicking Apply in the logged-in browser; still no link
NO_LINK_MARKERS = (NO_LINK, CLICK_CHECKED)

# Sites with a filler built so far.
IMPLEMENTED = {"greenhouse", "lever", "ashby", "workday"} | GENERIC_SITES


def site_key(ats: str | None) -> str | None:
    """The ENABLED_SITES switch for an ATS: every generic-filled site shares the "generic" switch."""
    return "generic" if ats in GENERIC_SITES else ats


def detect_ats(url: str | None) -> str | None:
    """A name from ATS_PATTERNS, "custom" for any other http(s) site (an employer's own career page),
    or None when there is no usable link."""
    if not url:
        return None
    for name, pattern in ATS_PATTERNS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "custom" if re.match(r"https?://", url, re.IGNORECASE) else None


def application_url(ats: str | None, url: str) -> str:
    """The page that actually holds the form. Lever and Ashby show the description first."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if ats == "lever" and not path.endswith("/apply"):
        path += "/apply"
    elif ats == "ashby" and not path.endswith("/application"):
        path += "/application"
    else:
        return url
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
