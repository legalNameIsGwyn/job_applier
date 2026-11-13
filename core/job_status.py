"""Is a job posting still open? Checked before you spend time filling in a form.

check_open(url) returns "open", "closed" or "unknown" (the site didn't say, or couldn't be reached).
Greenhouse, Lever, Ashby, Workday and LinkedIn postings are checked through their own public data;
anything else is judged from the page's text. "unknown" is never treated as closed.
"""

import re
from urllib.parse import urlsplit

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html"}

CLOSED_TEXT = re.compile(
    r"no longer (accepting|taking|receiving|available|open|hiring)|"
    r"(not|stopped) (currently )?(accepting|taking|receiving|reviewing) (new |any )?(applications?|applicants?)|"
    r"(position|job|role|posting|requisition|opening) (has been |is |was )?(filled|closed|expired|removed|unavailable)|"
    r"this (job|position|posting) (is|has been) (closed|filled|removed|no longer)|"
    r"applications? (are |is |have been )?closed|applicants? (are )?no longer|"
    r"job (not found|has expired)|"
    r"the page you.?re looking for (doesn.?t|does not) exist|couldn.?t find (that|this) (job|position)",
    re.IGNORECASE,
)


def closed_in_text(text: str) -> bool:
    """True if page text says the posting is closed."""
    return bool(CLOSED_TEXT.search(text or ""))


def _get(url: str, get=None):
    get = get or (requests.get if requests else None)
    if get is None:
        return None
    try:
        return get(url, timeout=15, headers=HEADERS, allow_redirects=True)
    except Exception:
        return None


def _by_status(resp) -> str | None:
    """open/closed/unknown from an API response where 200 = exists and 404/410 = gone."""
    if resp is None:
        return "unknown"
    if resp.status_code in (404, 410):
        return "closed"
    return "open" if resp.status_code == 200 else "unknown"


def check_open(url: str | None, get=None) -> str:
    if not url:
        return "unknown"
    parts = urlsplit(url)
    host, path = parts.netloc.lower(), [p for p in parts.path.split("/") if p]

    if host.endswith("linkedin.com"):
        m = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)", parts.path)
        if not m:
            return "unknown"
        resp = _get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}", get)
        if resp is None or resp.status_code == 429:
            return "unknown"
        if resp.status_code in (404, 410) or closed_in_text(resp.text):
            return "closed"
        return "open" if resp.status_code == 200 else "unknown"

    if "greenhouse.io" in host and len(path) >= 3 and path[1] == "jobs":
        return _by_status(_get(f"https://boards-api.greenhouse.io/v1/boards/{path[0]}/jobs/{path[2]}", get))

    if host.endswith("lever.co") and len(path) >= 2:
        return _by_status(_get(f"https://api.lever.co/v0/postings/{path[0]}/{path[1]}", get))

    if host.endswith("ashbyhq.com") and len(path) >= 2:
        resp = _get(f"https://api.ashbyhq.com/posting-api/job-board/{path[0]}", get)
        if resp is None or resp.status_code != 200:
            return "unknown"
        try:
            jobs = resp.json().get("jobs", [])
        except ValueError:
            return "unknown"
        return "open" if any(path[1] in (j.get("jobUrl", "") + j.get("applyUrl", "") + str(j.get("id", ""))) for j in jobs) else "closed"

    if host.endswith("myworkdayjobs.com") and "job" in path:
        i = path.index("job")
        site = path[i - 1] if i >= 1 else None
        if site:
            tenant = host.split(".")[0]
            api = f"https://{host}/wday/cxs/{tenant}/{site}/job/{'/'.join(path[i + 1:])}"
            resp = _get(api, get)
            if resp is not None and resp.status_code == 200:
                try:
                    info = resp.json()
                    if info.get("jobPostingInfo", {}).get("canApply") is False:
                        return "closed"
                    return "open"
                except ValueError:
                    return "unknown"
            return _by_status(resp) if resp is not None and resp.status_code in (404, 410) else "unknown"

    resp = _get(url, get)  # any other site: read the page
    if resp is None:
        return "unknown"
    if resp.status_code in (404, 410):
        return "closed"
    if resp.status_code == 200:
        return "closed" if closed_in_text(resp.text[:30000]) else "open"
    return "unknown"
