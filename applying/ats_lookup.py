"""Find a job's employer application link by searching the company's public job board.

LinkedIn no longer shows the employer's link to logged-out visitors, so instead we look for
the same job (same company and title) on the company's own Greenhouse, Lever or Ashby board.
Those boards publish their listings openly, which is exactly where our form filler works.
Companies on other systems (Workday, iCIMS, their own site) simply won't be found.

A match needs the same company slug AND the same title (or a 92%+ similar one); if several postings share
the title, the location has to pick one. When in doubt it returns None rather than guess.

Try it:  python -m applying.ats_lookup "Company Name" "Job Title" "City, ST"
"""

import re
import time
from difflib import SequenceMatcher

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

BOARD_APIS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
_COMPANY_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
                     "plc", "lp", "llp", "the"}
REQUEST_DELAY = 0.3          # seconds between requests to the job boards
TITLE_SIMILARITY = 0.92      # how close a title must be if it isn't identical


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower().replace("&", " and ")).split()


def slug_candidates(company: str, limit: int = 4) -> list[str]:
    """Likely board names for a company: 'Smithfield Foods, Inc.' -> smithfieldfoods, smithfield-foods, smithfield."""
    words = [w for w in _words(company) if w not in _COMPANY_SUFFIXES] or _words(company)
    if not words:
        return []
    options = ["".join(words), "-".join(words), words[0]]
    seen, out = set(), []
    for o in options:
        if o and o not in seen:
            seen.add(o)
            out.append(o)
    return out[:limit]


def _normalize_postings(ats: str, data) -> list[dict]:
    """Every board API's answer as [{title, url, location}]."""
    rows = []
    if ats == "greenhouse":
        for j in (data or {}).get("jobs", []):
            rows.append({"title": j.get("title", ""), "url": j.get("absolute_url", ""),
                         "location": (j.get("location") or {}).get("name", "")})
    elif ats == "lever":
        for j in data or []:
            rows.append({"title": j.get("text", ""), "url": j.get("hostedUrl", ""),
                         "location": (j.get("categories") or {}).get("location", "") or ""})
    elif ats == "ashby":
        for j in (data or {}).get("jobs", []):
            rows.append({"title": j.get("title", ""), "url": j.get("jobUrl") or j.get("applyUrl", ""),
                         "location": j.get("location", "") or ""})
    return [r for r in rows if r["title"] and r["url"]]


def fetch_board(ats: str, slug: str, get=None) -> list[dict] | None:
    """The company's open postings on that system, or None if it has no board there."""
    get = get or (requests.get if requests else None)
    if get is None:
        return None
    url = BOARD_APIS[ats].format(slug=slug)
    for attempt in range(2):
        try:
            resp = get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 429 and attempt == 0:   # rate limited: wait once and retry
                time.sleep(3)
                continue
            if resp.status_code != 200:
                return None
            return _normalize_postings(ats, resp.json())
        except Exception:
            return None
    return None


def _location_score(job_location: str, posting_location: str) -> int:
    """How well two location strings agree (city and state words in common)."""
    job, posting = set(_words(job_location)), set(_words(posting_location))
    return len(job & posting - {"united", "states", "us", "usa", "remote"})


def match_posting(title: str, location: str, postings: list[dict]) -> str | None:
    """URL of the posting that is this job, or None if there isn't a clear match."""
    want = _words(title)
    exact = [p for p in postings if _words(p["title"]) == want]
    matches = exact or [p for p in postings
                        if SequenceMatcher(None, " ".join(want), " ".join(_words(p["title"]))).ratio() >= TITLE_SIMILARITY]
    if not matches:
        return None
    if len({m["url"] for m in matches}) == 1:
        return matches[0]["url"]
    scored = sorted(matches, key=lambda p: _location_score(location, p["location"]), reverse=True)
    best, runner_up = scored[0], scored[1] if len(scored) > 1 else None
    if runner_up is None:
        return best["url"]
    if _location_score(location, best["location"]) > _location_score(location, runner_up["location"]):
        return best["url"]
    return None  # several same-title postings and the location doesn't pick one


class LinkFinder:
    """Looks up employer links, remembering each board it has already downloaded."""

    def __init__(self, get=None, delay: float = REQUEST_DELAY):
        self.get, self.delay, self.boards = get, delay, {}

    def board(self, ats: str, slug: str):
        key = (ats, slug)
        if key not in self.boards:
            self.boards[key] = fetch_board(ats, slug, self.get)
            time.sleep(self.delay)
        return self.boards[key]

    def find(self, company: str, title: str, location: str = "") -> str | None:
        for slug in slug_candidates(company):
            for ats in BOARD_APIS:
                postings = self.board(ats, slug)
                if postings:
                    url = match_posting(title, location, postings)
                    if url:
                        return url
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit('usage: python -m applying.ats_lookup "Company" "Job title" ["City, ST"]')
    link = LinkFinder().find(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    print(link or "No matching posting on a public Greenhouse / Lever / Ashby board.")