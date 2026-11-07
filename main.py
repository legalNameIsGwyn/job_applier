"""Main job scraper pipeline: scrape -> score -> save (each job saved as it's scored)."""

import asyncio
from datetime import datetime

import pandas as pd

from db import DB_PATH, FAILED_SCORE, get_scored_urls, init_db, save_job
from scraper import fill_missing_descriptions, scrape_multiple_terms
from scorer import MODEL, load_resume, score_job
from application_maker import create_application, job_folder
from show_jobs import get_jobs

MAX_CONSECUTIVE_FAILURES = 3  # abort if Ollama is clearly broken (not running, model missing)

# Automatic resume + cover letter generation after scoring
DOC_MIN_SCORE = 6      # only jobs scoring at least this get documents
MAX_DOCS_PER_RUN = 10  # cap per run (each job needs two model calls)
DOC_WINDOW_DAYS = 7    # only consider jobs scraped in the last N days


def clean(value) -> str:
    """Turn NaN/None from the DataFrame into an empty string."""
    return "" if pd.isna(value) else str(value)


def generate_documents(min_score: float = DOC_MIN_SCORE, max_docs: int = MAX_DOCS_PER_RUN,
                       days: int = DOC_WINDOW_DAYS) -> int:
    """Create a tailored resume + cover letter for the best-scoring recent jobs.

    Reads from the database (not just this run), so jobs scored in an earlier or
    interrupted run still get documents. Jobs that already have a folder are
    skipped by create_application, so this is safe to call on every run.
    Returns how many job folders were created.
    """
    # Take every qualifying job, drop the ones that already have a folder, THEN apply the
    # cap. Capping the query itself would keep re-selecting the same already-done top jobs.
    jobs = get_jobs(1000, "top", min_score=min_score, days=days, include_zero=False)
    jobs = [j for j in jobs if not job_folder(j).exists()]
    print(f"\n[DOCS] {len(jobs)} job(s) scoring {min_score}+ in the last {days} days have no documents yet"
          + (f"; making the best {max_docs}" if len(jobs) > max_docs else ""))
    jobs = jobs[:max_docs]

    created, failures = 0, 0
    for job in jobs:
        print(f"[DOCS] {job['match_score']:g}  {job['title'][:45]} - {job['company'][:25]}")
        try:
            if create_application(job):
                created += 1
            failures = 0
        except Exception as e:
            failures += 1
            print(f"[DOCS] Failed: {e}")
            if failures >= MAX_CONSECUTIVE_FAILURES:
                print("[DOCS] Too many failures in a row. Is Ollama running? Stopping.")
                break
    print(f"[DOCS] {created} new application folder(s) created")
    return created


async def main(
    site_names: list[str],
    search_term: str | list[str],
    location: str,
    results_wanted: int = 100,
    hours_old: int = 72,
    make_docs: bool = True,
    doc_min_score: float = DOC_MIN_SCORE,
    max_docs: int = MAX_DOCS_PER_RUN,
) -> None:
    """
    Full pipeline: scrape jobs -> score with Ollama -> save to SQLite DB.

    Each job is written to the database right after it is scored, so a crash or
    Ctrl-C loses nothing, and re-running skips jobs that are already scored.

    Args:
        site_names: List of site identifiers to scrape (e.g., ["linkedin"])
        search_term: One search term, or a list of them (all are searched and merged)
        location: Geographic filter
        results_wanted: Max jobs per site
        hours_old: Maximum job posting age in hours
        make_docs: After scoring, create a resume + cover letter for the best matches
        doc_min_score: Minimum score for a job to get documents
        max_docs: Most jobs to generate documents for in one run

    Example:
        asyncio.run(main(["linkedin"], ["junior software engineer", "python developer"], "Norfolk, VA"))
    """
    print(f"[PIPELINE] Starting job scraper at {datetime.now().isoformat()}")
    print("=" * 50)

    # Step 1: Initialize database
    init_db()

    # Step 2: Check the resume loads
    print(f"[SCORER] Loaded resume for {load_resume().get('name', 'unknown')}")
    print(f"[SCORER] Using model: {MODEL}")

    # Step 3: Scrape jobs
    search_terms = [search_term] if isinstance(search_term, str) else list(search_term)
    print(f"\n[SCRAPER] Scraping sites {site_names} for terms {search_terms}")
    df = await scrape_multiple_terms(
        site_names=site_names,
        search_terms=search_terms,
        location=location,
        results_wanted=results_wanted,
        hours_old=hours_old,
    )

    if df.empty:
        print("[SCRAPER] No jobs found, exiting.")
        return

    df = df.drop_duplicates(subset="job_url").reset_index(drop=True)
    print(f"[SCRAPER] {len(df)} unique jobs")

    # Skip jobs scored on a previous run (failed ones are retried)
    already_scored = get_scored_urls()
    todo = df[~df["job_url"].isin(already_scored)].copy()
    print(f"[SCORER] {len(df) - len(todo)} already scored, {len(todo)} to score")

    # Fetch descriptions only for jobs we still need to score (saves requests on re-runs)
    todo = await asyncio.to_thread(fill_missing_descriptions, todo)

    # A job without a description can't be scored meaningfully. Skip it without
    # saving anything, so it is picked up again on the next run.
    has_desc = todo["description"].fillna("").astype(str).str.strip() != ""
    skipped = int((~has_desc).sum())
    if skipped:
        print(f"[SCORER] Skipping {skipped} jobs with no description (they'll be retried next run)")
    todo = todo[has_desc]

    if todo.empty:
        print("[SCORER] Nothing new to score.")
        if skipped:
            print("[SCORER] Jobs without descriptions usually mean LinkedIn is rate limiting; "
                  "wait a while or lower results_wanted.")
        if make_docs:  # still catch up on documents for jobs scored earlier
            generate_documents(doc_min_score, max_docs)
        return

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

    # Step 6: Resume + cover letter for the best matches
    if make_docs:
        generate_documents(doc_min_score, max_docs)

    print("\n" + "=" * 50)


if __name__ == "__main__":
    asyncio.run(main(
        site_names=["linkedin", "indeed"],
        search_term=[
            "junior software engineer",
            "software developer",
            "python developer",
            "associate software engineer",
        ],
        location="Norfolk, VA",
        results_wanted=50,  # per site, per search term
        hours_old=72,
        make_docs=True,       # set False to only scrape and score
        doc_min_score=6,
        max_docs=10,
    ))