"""Postings for the model tester: real ones only. Scraped (from your database), a live LinkedIn link, or a file you write.

Only the posting's text is used (title, company, location, description, link). Scores and compatibility in the
database belong to one profile and one model, so they are not carried over: every model gets identical input.

A posting file is JSON, a list of objects:
    [{"title": "Help Desk Technician", "company": "Acme", "location": "Norfolk, VA",
      "description": "full posting text...", "job_url": "https://... (optional)"}]
Optional keys "gaps" (list of requirements you lack) and "compat_missing" are used as given; otherwise bridge and
auto mode get them from the frozen scoring step (see prep.py).
"""

import hashlib
import json
import re
from pathlib import Path

REQUIRED = ("title", "company", "description")
TEXT_KEYS = ("title", "company", "location", "description", "job_url")
PASS_THROUGH = ("gaps", "compat_missing", "compat_pct", "compat_detail_pct", "match_score")


def _slug(text: str, limit: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "x"


def clean(raw: dict, where: str = "posting") -> dict:
    """One posting in the shape create_application expects. Says exactly what is missing."""
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: each posting must be an object with title, company and description")
    missing = [k for k in REQUIRED if not str(raw.get(k) or "").strip()]
    if missing:
        raise ValueError(f"{where}: missing {', '.join(missing)}")
    job = {k: str(raw.get(k) or "").strip() for k in TEXT_KEYS}
    job.update({k: raw[k] for k in PASS_THROUGH if raw.get(k) not in (None, "", [])})
    key = job["job_url"] or job["description"]
    job["id"] = f"{_slug(job['company'])}-{_slug(job['title'])}-{hashlib.md5(key.encode()).hexdigest()[:6]}"
    if not job["job_url"]:
        job["job_url"] = f"manual:{job['id']}"
    return job


def from_file(path: str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"posting file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e})") from None
    items = data.get("postings") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError(f"{p} must hold a list of postings")
    return [clean(item, f"{p.name} #{i}") for i, item in enumerate(items, 1)]


def from_database(urls: list[str]) -> list[dict]:
    """Scraped postings, looked up by URL in your jobs database (read only; uses DEFAULT_PROFILE to find them)."""
    from db.queries import get_job_by_url
    from db.session import select_profile
    select_profile()
    found = []
    for url in urls:
        job = get_job_by_url(url)
        if not job:
            raise ValueError(f"{url} is not in your jobs database. Run main.py first, or put it in a posting file.")
        found.append(clean(job, url))
    return found


def parse_linkedin_header(page: str) -> dict:
    """title / company / location from LinkedIn's public posting page. Missing pieces come back as ''.

    These selectors are LinkedIn's guest-page markup as I know it and could not be checked against the live site
    from where this was written; if LinkedIn changes them the error from from_linkedin() says what was not found.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")

    def first(*selectors):
        for sel in selectors:
            node = soup.select_one(sel)
            if node and node.get_text(strip=True):
                return " ".join(node.get_text(" ", strip=True).split())
        return ""

    return {"title": first("h2.top-card-layout__title", "h1.top-card-layout__title", "h2.topcard__title"),
            "company": first("a.topcard__org-name-link", ".topcard__org-name-link"),
            "location": first("span.topcard__flat-asset")}


def from_linkedin(urls: list[str]) -> list[dict]:
    """Live LinkedIn postings, fetched with the scraper's own functions (core/scraper.py)."""
    from core import scraper as s   # its private helpers are reused so the tester and main.py read pages the same way
    session = s.requests.Session()
    session.headers.update(s.REQUEST_HEADERS)
    found = []
    for url in urls:
        job_id = s._linkedin_job_id(url)
        if not job_id:
            raise ValueError(f"{url} is not a linkedin.com/jobs/view/... link")
        try:
            page = s._fetch_linkedin_page(session, job_id)
        except s._PostingGone:
            raise ValueError(f"{url}: LinkedIn says this posting no longer exists") from None
        except s.requests.RequestException as e:
            raise ValueError(f"{url}: could not reach LinkedIn ({type(e).__name__}). Check your connection.") from None
        except s._RateLimited:
            raise ValueError("LinkedIn is rate limiting requests right now; wait a while and try again") from None
        description = s._parse_linkedin_description(page)
        head = parse_linkedin_header(page)
        missing = [k for k, v in (("title", head["title"]), ("company", head["company"]), ("description", description)) if not v]
        if missing:
            raise ValueError(f"{url}: could not read the {', '.join(missing)} from the page. Put the posting in a "
                             "--posting-file instead.")
        found.append(clean({**head, "description": description,
                            "job_url": f"https://www.linkedin.com/jobs/view/{job_id}"}, url))
    return found


def unique(postings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in postings:
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out
