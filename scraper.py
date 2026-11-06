"""Job Scraper using JobSpy library with async orchestration."""

import asyncio
import inspect

import pandas as pd
from jobspy import scrape_jobs

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