"""Job Scraper using JobSpy library with async orchestration."""

import asyncio
import html as _html
import inspect
import random
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

import pandas as pd
from jobspy import scrape_jobs

from config.settings import (
    AVAILABLE_SITES, COUNTRY_INDEED, DEFAULT_HOURS_OLD, DEFAULT_RESULTS_WANTED, DELAY_BETWEEN_SEARCH_TERMS,
    DESCRIPTION_FETCH_DELAY, DESCRIPTION_FETCH_TIMEOUT, RATE_LIMIT_BACKOFF_SECONDS, RATE_LIMIT_STOP_AFTER,
    LINKEDIN_JOBSPY_FETCH_DESCRIPTIONS, LINKEDIN_RESULTS_WANTED, USER_AGENT,
)  # all tunable in config/settings.py

try:  # both are normally installed alongside jobspy
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

# LinkedIn search results carry no job description unless asked to fetch each
# page (slower). The parameter name differs between jobspy versions, so pass
# whichever one this install supports.
_SCRAPE_PARAMS = inspect.signature(scrape_jobs).parameters
DESCRIPTION_KWARGS = {
    name: True
    for name in ("linkedin_fetch_description", "fetch_description")
    if name in _SCRAPE_PARAMS
}


# "zip_recruiter", "glassdoor", "bayt", "naukri", "bdjobs", "hellowork",

SCRAPE_CONFIG = {
    "results_wanted": DEFAULT_RESULTS_WANTED,
    "hours_old": DEFAULT_HOURS_OLD,
}

LINKEDIN_JOB_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}


class _RateLimited(Exception):
    """LinkedIn answered 429 (too many requests)."""


def _is_blank(value) -> bool:
    return pd.isna(value) or not str(value).strip()


def _linkedin_job_id(url: str) -> str | None:
    """Extract the numeric job id from a linkedin.com/jobs/view/... URL."""
    match = re.search(r"/view/(?:.*?-)?(\d+)(?:[/?#]|$)", url or "")
    return match.group(1) if match else None


def _parse_linkedin_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = (
        soup.select_one("div.show-more-less-html__markup")
        or soup.select_one("div.description__text")
    )
    if not node:
        return ""
    for tag in node.find_all(["b", "strong", "i", "em", "u", "a", "span"]):
        tag.unwrap()  # keep inline formatting from splitting sentences
    node = BeautifulSoup(str(node), "html.parser")  # re-parse to merge split text
    for br in node.find_all("br"):
        br.replace_with("\n")
    for li in node.find_all("li"):
        li.insert(0, "- ")
    return node.get_text("\n", strip=True)

def _parse_linkedin_applicants(html: str) -> int | None:
    """Applicant count from the public job page ('42 applicants', 'Over 200 applicants').
    None when there is no count, or it only says 'Be among the first 25 applicants'."""
    node = BeautifulSoup(html, "html.parser").select_one(".num-applicants__caption")
    if not node:
        return None
    text = node.get_text(" ", strip=True).lower()
    match = re.search(r"(\d[\d,]*)", text)
    if not match or "first" in text:
        return None
    number = int(match.group(1).replace(",", ""))
    return number + 1 if ("over" in text or "more than" in text) else number

def _unwrap_external(link: str) -> str | None:
    """The employer's URL from a LinkedIn redirect like .../externalApply/123?url=<encoded>, else None."""
    link = _html.unescape(link).strip().strip('"\' ')
    query = parse_qs(urlsplit(link).query)
    target = unquote(query["url"][0]) if "url" in query else link
    if re.match(r"https?%3a", target, re.I):  # encoded twice
        target = unquote(target)
    host = urlsplit(target).netloc.lower()
    if not target.lower().startswith("http") or not host or host.endswith("linkedin.com"):
        return None
    return target


def _parse_linkedin_apply_link(html: str) -> str | None:
    """The employer's own application URL from a LinkedIn job page, or None (e.g. Easy Apply).

    LinkedIn's public job page carries the Apply button's link in a hidden <code id="applyUrl">
    comment and on the button itself, as a redirect holding the employer's URL in ?url=...
    All the places it can appear are checked.
    """
    candidates = []
    
    # Pattern 1: Hidden applyUrl comment (current)
    candidates.extend(re.findall(r'id="applyUrl"[^>]*>\s*<!--\s*"?(.*?)"?\s*-->', html, re.S))
    
    # Pattern 2: Data attributes on apply button
    candidates.extend(re.findall(r'data-.*?apply.*?"\s*:\s*"([^"]+)"', html))
    
    # Pattern 3: Job description section
    candidates.extend(re.findall(r'<div[^>]*class="job-description[^>]*>(.*?)</div>', html, re.S))
    
    # Pattern 4: Application link in description
    candidates.extend(re.findall(r'<a[^>]*href="([^"]*apply[^"]*)"', html))
    
    # Pattern 5: JSON in script tags
    candidates.extend(re.findall(r'externalApply/\d+\?[^"]*"', html))
    
    for link in candidates:
        target = _unwrap_external(link)
        if target:
            return target
    return None


def _fetch_linkedin_page(session, job_id: str) -> str:
    """The HTML of LinkedIn's public job posting ('' if unavailable). Raises _RateLimited on 429."""
    resp = session.get(LINKEDIN_JOB_API.format(job_id=job_id), timeout=DESCRIPTION_FETCH_TIMEOUT)
    if resp.status_code == 429:
        raise _RateLimited()
    return resp.text if resp.status_code == 200 else ""


def _fetch_linkedin_description(session, job_id: str) -> str:
    return _parse_linkedin_description(_fetch_linkedin_page(session, job_id))


def fill_missing_descriptions(
    df: pd.DataFrame, min_delay: float = DESCRIPTION_FETCH_DELAY[0], max_delay: float = DESCRIPTION_FETCH_DELAY[1]
) -> pd.DataFrame:
    """Fetch the description from each LinkedIn job page that lacks one.

    Requests are spaced out to avoid rate limiting. If LinkedIn answers 429
    three times in a row, fetching stops and the remaining jobs keep an empty
    description (the caller skips them; they are retried on the next run).
    Returns a copy of df; the index must be unique.
    """
    df = df.copy()
    if "description" not in df.columns:
        df["description"] = ""
    df["description"] = df["description"].astype(object)
    
    if "applicants" not in df.columns:
        df["applicants"] = pd.Series([None] * len(df), index=df.index, dtype=object)
        
    missing = [
        idx
        for idx, row in df.iterrows()
        if _is_blank(row["description"]) and "linkedin.com" in str(row.get("job_url", ""))
    ]
    if not missing:
        return df

    if requests is None or BeautifulSoup is None:
        print("[SCRAPER] 'requests' and 'beautifulsoup4' are needed to fetch descriptions: "
              "pip install requests beautifulsoup4")
        return df

    print(f"[SCRAPER] Fetching {len(missing)} LinkedIn descriptions "
          f"(~{int(len(missing) * (min_delay + max_delay) / 2)}s, spaced out to avoid rate limits)")

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    filled = 0
    rate_limited_in_a_row = 0

    for n, idx in enumerate(missing, start=1):
        job_id = _linkedin_job_id(str(df.at[idx, "job_url"]))
        if not job_id:
            continue
        try:
            page = _fetch_linkedin_page(session, job_id)
            text = _parse_linkedin_description(page) if page else ""
            link = _parse_linkedin_apply_link(page) if page else None  # usually absent: LinkedIn hides it
            count = _parse_linkedin_applicants(page) if page else None
            rate_limited_in_a_row = 0
        except _RateLimited:
            rate_limited_in_a_row += 1
            if rate_limited_in_a_row >= RATE_LIMIT_STOP_AFTER:
                print("[SCRAPER] LinkedIn is rate limiting (429). Stopping description "
                      "fetching; wait a while and re-run to pick up the rest.")
                break
            print("[SCRAPER] Rate limited (429), backing off...")
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * rate_limited_in_a_row)
            continue
        except requests.RequestException as e:
            print(f"[SCRAPER] Could not fetch job {job_id}: {e}")
            continue

        if text:
            df.at[idx, "description"] = text
            filled += 1

        if count is not None:
            df.at[idx, "applicants"] = count

        # If the page does carry the employer's apply link, keep it (unless JobSpy already gave one).
        if link:
            if "job_url_direct" not in df.columns:
                df["job_url_direct"] = None
                df["job_url_direct"] = df["job_url_direct"].astype(object)
            if _is_blank(df.at[idx, "job_url_direct"]):
                df.at[idx, "job_url_direct"] = link
        if n % 10 == 0:
            print(f"[SCRAPER] Fetched {n}/{len(missing)} pages ({filled} descriptions)")
        time.sleep(random.uniform(min_delay, max_delay))

    print(f"[SCRAPER] Got descriptions for {filled}/{len(missing)} jobs")
    return df


async def scrape_sites(
    site_name: str,
    search_term: str,
    location: str,
    results_wanted: int | None = None,
    hours_old: int | None = None,
) -> pd.DataFrame:
    """Scrape jobs from a specific site using JobSpy library."""
    config = SCRAPE_CONFIG.copy()
    if results_wanted is not None:
        config["results_wanted"] = results_wanted
    if hours_old is not None:
        config["hours_old"] = hours_old

    normalized_site = site_name.lower().replace(" ", "")
    if normalized_site == "linkedin":
        config["results_wanted"] = min(config["results_wanted"], LINKEDIN_RESULTS_WANTED)

    if normalized_site not in AVAILABLE_SITES:
        raise ValueError(f"Invalid site name. Must be one of: {AVAILABLE_SITES}")

    print(f'[SCRAPER] Scraping {normalized_site}: "{search_term}" in {location}')

    try:
        # scrape_jobs is blocking, so run it in a worker thread; this is what
        # lets multiple sites actually scrape concurrently.
        df = await asyncio.to_thread(
            scrape_jobs,
            site_name=[normalized_site],
            search_term=search_term,
            location=location,
            country_indeed=COUNTRY_INDEED,
            **(DESCRIPTION_KWARGS if LINKEDIN_JOBSPY_FETCH_DESCRIPTIONS else {}),
            **config,
        )
        print(f"[SCRAPER] Found {len(df)} jobs from {normalized_site}")
        return df

    except Exception as e:
        print(f"[SCRAPER] Error scraping {normalized_site}: {e}")
        raise


async def scrape_multiple_sites(
    site_names: list[str],
    search_term: str,
    location: str,
    results_wanted: int | None = None,
    hours_old: int | None = None,
) -> pd.DataFrame:
    """Scrape multiple sites concurrently; one failing site doesn't sink the rest."""
    tasks = [
        scrape_sites(site, search_term, location, results_wanted, hours_old)
        for site in site_names
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    dfs = [r for r in results if isinstance(r, pd.DataFrame)]
    if not dfs:
        raise RuntimeError("No sites scraped successfully")

    combined_df = pd.concat(dfs, ignore_index=True)
    print(f"[SCRAPER] Total jobs found across all sites: {len(combined_df)}")
    return combined_df


async def scrape_multiple_terms(
    site_names: list[str],
    search_terms: list[str],
    location: str,
    results_wanted: int | None = None,
    hours_old: int | None = None,
    delay_between_terms: float = DELAY_BETWEEN_SEARCH_TERMS,
) -> pd.DataFrame:
    """Run every search term across every site and merge the results.

    Terms run one after another (sites within a term run concurrently), with a
    short pause between them to stay friendly to the job sites. A term that
    fails is skipped rather than aborting the whole run. Duplicates (the same
    job showing up for several terms) are removed by job_url.
    """
    dfs = []
    for i, term in enumerate(search_terms):
        if i:
            await asyncio.sleep(delay_between_terms)
        try:
            df = await scrape_multiple_sites(site_names, term, location, results_wanted, hours_old)
        except Exception as e:
            print(f'[SCRAPER] Skipping "{term}": {e}')
            continue
        df["search_term"] = term
        dfs.append(df)

    if not dfs:
        raise RuntimeError("No search term produced any results")

    combined = pd.concat(dfs, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset="job_url").reset_index(drop=True)
    print(f"[SCRAPER] {before} jobs across {len(dfs)} search terms -> {len(combined)} unique")
    return combined