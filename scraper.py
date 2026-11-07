"""Job Scraper using JobSpy library with async orchestration."""

import asyncio
import inspect
import random
import re
import time

import pandas as pd
from jobspy import scrape_jobs

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

AVAILABLE_SITES = ["linkedin", "indeed"]

# "zip_recruiter", "glassdoor", "bayt", "naukri", "bdjobs", "hellowork",

SCRAPE_CONFIG = {
    "results_wanted": 10,
    "hours_old": 24,
}

LINKEDIN_JOB_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
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


def _fetch_linkedin_description(session, job_id: str) -> str:
    resp = session.get(LINKEDIN_JOB_API.format(job_id=job_id), timeout=20)
    if resp.status_code == 429:
        raise _RateLimited()
    if resp.status_code != 200:
        return ""
    return _parse_linkedin_description(resp.text)


def fill_missing_descriptions(
    df: pd.DataFrame, min_delay: float = 1.5, max_delay: float = 3.5
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
            text = _fetch_linkedin_description(session, job_id)
            rate_limited_in_a_row = 0
        except _RateLimited:
            rate_limited_in_a_row += 1
            if rate_limited_in_a_row >= 3:
                print("[SCRAPER] LinkedIn is rate limiting (429). Stopping description "
                      "fetching; wait a while and re-run to pick up the rest.")
                break
            print("[SCRAPER] Rate limited (429), backing off...")
            time.sleep(30 * rate_limited_in_a_row)
            continue
        except requests.RequestException as e:
            print(f"[SCRAPER] Could not fetch job {job_id}: {e}")
            continue

        if text:
            df.at[idx, "description"] = text
            filled += 1
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
            country_indeed="USA",
            **DESCRIPTION_KWARGS,
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
    delay_between_terms: float = 5.0,
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