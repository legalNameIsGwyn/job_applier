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
}

# Sites with a filler built so far.
IMPLEMENTED = {"greenhouse", "lever", "ashby"}


def detect_ats(url: str | None) -> str | None:
    """'greenhouse', 'lever', 'ashby', 'workday', 'linkedin', 'indeed', or None if unknown."""
    for name, pattern in ATS_PATTERNS.items():
        if url and re.search(pattern, url, re.IGNORECASE):
            return name
    return None


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
