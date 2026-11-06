"""Main job scraper pipeline: scrape -> score -> save (each job saved as it's scored)."""

import asyncio
from datetime import datetime

import pandas as pd

from db import DB_PATH, FAILED_SCORE, get_scored_urls, init_db, save_job
from scraper import scrape_multiple_sites
from scorer import MODEL, load_resume, score_job

MAX_CONSECUTIVE_FAILURES = 3  # abort if Ollama is clearly broken (not running, model missing)


def clean(value) -> str:
    """Turn NaN/None from the DataFrame into an empty string."""
    return "" if pd.isna(value) else str(value)


async def main(
    site_names: list[str],
    search_term: str,
    location: str,
    results_wanted: int = 100,
    hours_old: int = 72,
) -> None:
    """
    Full pipeline: scrape jobs -> score with Ollama -> save to SQLite DB.

    Each job is written to the database right after it is scored, so a crash or
    Ctrl-C loses nothing, and re-running skips jobs that are already scored.

    Args:
        site_names: List of site identifiers to scrape (e.g., ["linkedin"])
        search_term: Job keywords to search
        location: Geographic filter
        results_wanted: Max jobs per site
        hours_old: Maximum job posting age in hours

    Example:
        asyncio.run(main(["linkedin"], "junior software engineer", "Norfolk, VA"))
    """
    print(f"[PIPELINE] Starting job scraper at {datetime.now().isoformat()}")
    print("=" * 50)

    # Step 1: Initialize database
    init_db()

    # Step 2: Check the resume loads
    print(f"[SCORER] Loaded resume for {load_resume().get('name', 'unknown')}")
    print(f"[SCORER] Using model: {MODEL}")

    # Step 3: Scrape jobs
    print(f"\n[SCRAPER] Scraping sites: {site_names}")
    df = await scrape_multiple_sites(
        site_names=site_names,
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        hours_old=hours_old,
    )

    if df.empty:
        print("[SCRAPER] No jobs found, exiting.")
        return

    df = df.drop_duplicates(subset="job_url").reset_index(drop=True)
    print(f"[SCRAPER] {len(df)} unique jobs")

    no_desc = int(df["description"].isna().sum() + (df["description"] == "").sum())
    if no_desc == len(df):
        print("[SCRAPER] None of the jobs have a description, so scoring would be meaningless. "
              "Stopping. Run: python -c \"import inspect, jobspy; "
              "print(inspect.signature(jobspy.scrape_jobs))\" and look for a *fetch_description option.")
        return
    if no_desc:
        print(f"[SCRAPER] Warning: {no_desc} jobs have no description; their scores will be unreliable")

    # Skip jobs scored on a previous run (failed ones are retried)
    already_scored = get_scored_urls()
    todo = df[~df["job_url"].isin(already_scored)]
    print(f"[SCORER] {len(df) - len(todo)} already scored, {len(todo)} to score")

    # Step 4: Score each job and save it immediately
    results = []
    consecutive_failures = 0

    for i, (_, row) in enumerate(todo.iterrows(), start=1):
        job = {
            "site": clean(row.get("site")) or "unknown",
            "job_url": clean(row.get("job_url")),
            "title": clean(row.get("title")),
            "company": clean(row.get("company")),
            "location": clean(row.get("location")),
            "description": clean(row.get("description")),
        }
        print(f"\n[SCORER] Scoring job {i}/{len(todo)}: {job['title'][:50]}...")

        try:
            score = score_job(job["title"], job["company"], job["location"], job["description"])
            consecutive_failures = 0
        except Exception as e:
            print(f"[SCORER] Failed on '{job['title']}': {e}")
            score = {"match_score": FAILED_SCORE, "matched_skills": [], "gaps": ["scoring failed"]}
            consecutive_failures += 1

        save_job(job, score)

        if score["match_score"] >= 0:
            print(f"[SCORER] Score: {score['match_score']}")
            results.append((score["match_score"], job))

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            print(f"\n[PIPELINE] {MAX_CONSECUTIVE_FAILURES} failures in a row. Is Ollama running "
                  f"and is '{MODEL}' pulled? Stopping; progress so far is saved.")
            break

    # Step 5: Summary
    print("\n[PIPELINE] Pipeline complete!")
    print(f"Scored {len(results)} jobs this run. Database: {DB_PATH}")

    if results:
        print("\nTop matches this run:")
        for score, job in sorted(results, key=lambda r: r[0], reverse=True)[:10]:
            print(f"  {score:>4}  {job['title'][:45]} - {job['company'][:25]}\n        {job['job_url']}")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    asyncio.run(main(
        site_names=["linkedin"],
        search_term="junior software engineer",
        location="Norfolk, VA",
        results_wanted=100,
        hours_old=72,
    ))