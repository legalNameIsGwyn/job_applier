"""Main job scraper pipeline: scrape -> filter -> score -> save -> make documents.

Run it with:  python main.py
What to search for, which model to use and every other setting is in config/settings.py.
"""

import asyncio
import config.settings as _settings
from datetime import datetime

import pandas as pd

import argparse

from config.settings import DB_PATH
from db.calibrations import load_calibration
from db.queries import applied_urls, get_jobs
from db.repo import FAILED_SCORE, get_scored_urls, init_db, save_job
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments
from core.scraper import fill_missing_descriptions, scrape_multiple_terms
from core.scorer import MODEL, load_resume, score_job
from documents.application_maker import choose_mode, create_application, job_folder
from core.csv_log import csv_path, enabled as csv_enabled, known_urls, log_job
from core.dedupe import duplicate_gap, load_known
from core.filters import filter_reason
from core.job_info import format_salary
from core.calibration import blend, keyword_score
from core.compat import compute as compute_compat, describe as describe_compat
from core.console import banner, decision, job_block, job_head, note, say, section, step

from config.settings import (
    MIN_SCORE, DOC_WINDOW_DAYS, HOURS_OLD, LOCATION, MAKE_DOCS, MAX_CONSECUTIVE_FAILURES,
    MAX_DOCS_PER_RUN, RESULTS_WANTED, SEARCH_TERMS, SITES,
)

TOP_THIS_RUN = 10   # jobs shown in full under "Top matches this run"


def show_summary(already_shown: set[str] | None = None) -> None:
    """Print the end-of-run summary (SUMMARY_AFTER_RUN in config/settings.py). Never breaks a run.

    already_shown: job URLs printed in full in stage 5, left out of the summary's best matches.
    """
    if not getattr(_settings, "SUMMARY_AFTER_RUN", True):
        return
    try:
        from tools.summary import print_summary
        print_summary(already_shown=already_shown)
    except Exception as e:
        decision("warn", f"summary skipped: {e}")


def clean(value) -> str:
    """Turn NaN/None from the DataFrame into an empty string."""
    return "" if pd.isna(value) else str(value)


def job_from_row(row) -> dict:
    """One DataFrame row -> the plain dict the database and scorer use."""
    return {
        "site": clean(row.get("site")) or "unknown",
        "job_url": clean(row.get("job_url")),
        "title": clean(row.get("title")),
        "company": clean(row.get("company")),
        "location": clean(row.get("location")),
        "description": clean(row.get("description")),
        "apply_url": clean(row.get("job_url_direct")),  # the employer's own link, when the board gives one
        "salary": format_salary(row.get("min_amount"), row.get("max_amount"), row.get("interval"), row.get("currency")),
    }


def save_filtered(job: dict, reason: str) -> None:
    """Record a rule-filtered job (score 0, status 'filtered') so it is never re-scraped or re-scored."""
    save_job(job, {"match_score": 0.0, "matched_skills": [], "gaps": [reason]},
             status="filtered", model_score=0.0)

def short_reason(reason: str) -> str:
    """'Filtered: senior-level title ('Senior')' -> 'senior-level title ('Senior')'."""
    return reason[len("Filtered: "):] if reason.startswith("Filtered: ") else reason


def compat_text(compat: dict | None) -> str:
    """'64%' from the detailed compatibility (rough one as a fallback), or 'n/a'."""
    if not compat:
        return "n/a"
    pct = compat.get("detail_pct")
    if pct is None:
        pct = compat.get("pct")
    return "n/a" if pct is None else f"{pct:g}%"


def doc_mode(job: dict, min_score: float) -> str | None:
    """The tailoring mode a job would get, or None if it scores too low for documents."""
    if (job.get("match_score") or 0) < min_score:
        return None
    try:
        return choose_mode(job)[0]
    except ValueError:
        return None

def applicant_reason(row, job: dict) -> str | None:
    """Reason to skip a LinkedIn job for having too many applicants (None = keep it)."""
    limit = getattr(_settings, "MAX_APPLICANTS", None)
    if limit is None or "linkedin.com" not in job["job_url"]:
        return None
    count = row.get("applicants")
    if pd.notna(count) and int(count) > limit:
        return f"{int(count)} applicants (limit {limit})"
    if pd.isna(count) and not getattr(_settings, "KEEP_UNKNOWN_APPLICANTS", True):
        return "no applicant count shown"
    return None

def generate_documents(min_score: float = MIN_SCORE, max_docs: int = MAX_DOCS_PER_RUN,
                       days: int = DOC_WINDOW_DAYS, number: int | None = 6) -> int:
    """Create a tailored resume + cover letter for the best-scoring recent jobs, and log each in the CSV.

    Reads from the database (not just this run), so jobs scored in an earlier or interrupted run still
    get documents. A job already in the applications CSV is skipped. A job that has a folder but no CSV
    row (made before the CSV existed) just gets its row added. Returns how many folders were created.
    """
    step(number, "DOCUMENTS", f"A tailored resume and cover letter for each job scoring {min_score:g}+ "
                              f"in the last {days} days that has none yet.")
    # Take every qualifying job, drop the ones already handled, THEN apply the cap. Capping the
    # query itself would keep re-selecting the same already-done top jobs.
    jobs = get_jobs(1000, "top", min_score=min_score, days=days, include_zero=False)
    logged = known_urls() | applied_urls()
    jobs = [j for j in jobs if j["job_url"] not in logged]

    rows = 0
    for j in [j for j in jobs if job_folder(j).exists()]:
        rows += log_job(j, job_folder(j).name)   # older folder: add its row, mode unknown
    jobs = [j for j in jobs if not job_folder(j).exists()]

    print()
    say("found", f"{len(jobs)} job(s) without documents yet"
        + (f"; making the best {max_docs}" if max_docs and len(jobs) > max_docs else ""))
    jobs = jobs[:max_docs] if max_docs else jobs

    created, failures = 0, 0
    for job in jobs:
        print()
        job_head(job["title"], job["company"], job["job_url"])
        try:
            if create_application(job):
                created += 1
                rows += log_job(job, job_folder(job).name, choose_mode(job)[0])
            failures = 0
        except Exception as e:
            failures += 1
            decision("bad", f"failed: {e}")
            if failures >= MAX_CONSECUTIVE_FAILURES:
                decision("bad", "stopped: too many failures in a row. Is Ollama running?")
                break
    print()
    result = f"{created} folder(s) created"
    if csv_enabled():
        result += f" · {rows} row(s) added to {csv_path().name}"
    say("result", result)
    if csv_enabled():
        say("csv", str(csv_path()), "gray")
    return created


def show_results(results: list, filtered: int, duplicates: int, min_score: float) -> set[str]:
    """Stage 5: counts for this run and the best jobs in full. Returns the URLs shown in full."""
    step(5, "RESULTS", "This run's best jobs, with what the posting asks for and where you fall short.")
    print()
    say("scored", f"{len(results)} this run · filtered {filtered} · duplicates {duplicates}")
    say("database", str(DB_PATH), "gray")

    best = [job for score, job in sorted(results, key=lambda r: r[0], reverse=True) if score > 0][:TOP_THIS_RUN]
    if not best:
        return set()
    # Read them back: the database has compat_missing, matched skills and gaps in one place.
    stored = {j["job_url"]: j for j in get_jobs(1000, "top", days=2, include_zero=False)}
    print()
    print(section("TOP MATCHES THIS RUN"))
    for job in best:
        full = stored.get(job["job_url"], job)
        print()
        job_block(full, doc_mode(full, min_score))
    return {j["job_url"] for j in best}


async def main(
    site_names: list[str],
    search_term: str | list[str],
    location: str,
    results_wanted: int = RESULTS_WANTED,
    hours_old: int = HOURS_OLD,
    make_docs: bool = MAKE_DOCS,
    doc_min_score: float = MIN_SCORE,
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
    init_db()
    banner(active_profile_name(), "SEMI-AUTO", MODEL, load_resume().get("name", "unknown"),
           doc_min_score, datetime.now().strftime("%a %Y-%m-%d %H:%M"))

    # ---- 1 SCRAPE
    search_terms = [search_term] if isinstance(search_term, str) else list(search_term)
    step(1, "SCRAPE", f"Searching {', '.join(site_names)} for {len(search_terms)} search term(s) in {location}.")
    print()
    df = await scrape_multiple_terms(
        site_names=site_names,
        search_terms=search_terms,
        location=location,
        results_wanted=results_wanted,
        hours_old=hours_old,
    )

    if df.empty:
        print()
        decision("warn", "nothing found: the scrapers returned no jobs")
        show_summary()
        return

    df = df.drop_duplicates(subset="job_url").reset_index(drop=True)

    # Skip jobs scored on a previous run (failed ones are retried)
    already_scored = get_scored_urls()
    todo = df[~df["job_url"].isin(already_scored)].copy()
    print()
    say("found", f"{len(df)} unique jobs: {len(df) - len(todo)} already scored earlier, {len(todo)} new")

    # ---- 2 PRE-FILTER: title / company rules. These need no description, so they run BEFORE any description is fetched and save those requests.
    step(2, "PRE-FILTER", "Title and company rules, checked before any description is downloaded.")
    filtered_count, kept, shown = 0, [], 0
    for idx, row in todo.iterrows():
        job = job_from_row(row)
        reason = filter_reason(job["title"], job["company"])
        if reason:
            save_filtered(job, reason)
            filtered_count += 1
            print()
            shown += 1
            job_head(job["title"], job["company"], job["job_url"])
            decision("bad", f"rejected: {short_reason(reason)}")
        else:
            kept.append(idx)
    print()
    say("result", f"{filtered_count} rejected, {len(kept)} kept")
    todo = todo.loc[kept]

    # ---- 3 DESCRIPTIONS: only for jobs we still need to score (saves requests on re-runs)
    step(3, "DESCRIPTIONS", "Downloading the full posting for each job that passed the pre-filter.")
    print()
    todo = await asyncio.to_thread(fill_missing_descriptions, todo)

    # A job without a description can't be scored meaningfully. Skip it without
    # saving anything, so it is picked up again on the next run.
    has_desc = todo["description"].fillna("").astype(str).str.strip() != ""
    skipped = int((~has_desc).sum())
    if skipped:
        print()
        decision("warn", f"skipped: {skipped} job(s) have no description (retried next run)")
    todo = todo[has_desc]

    if todo.empty:
        print()
        say("result", "nothing new to score")
        if skipped:
            note("Jobs without descriptions usually mean LinkedIn is rate limiting; "
                 "wait a while or lower results_wanted.")
        if make_docs:  # still catch up on documents for jobs scored earlier
            generate_documents(doc_min_score, max_docs, number=4)
        show_summary()
        return

    # ---- 4 SCORING: each job is saved right after it is scored
    step(4, "SCORING",
         "Suitability is how well you fit this kind of job for your profile, out of 10. "
         "Compatibility is the share of the posting's listed requirements your resume meets.")
    results = []
    consecutive_failures = 0
    known = load_known()      # jobs already scored, to spot the same posting listed again
    cal = load_calibration()  # read once, not once per job
    duplicates = 0

    for _, row in todo.iterrows():
        job = job_from_row(row)
        print()                   # <-- delete this line to remove the blank line between jobs
        job_head(job["title"], job["company"], job["job_url"])

        # Filter stage 2: needs the description (years of experience required)
        reason = applicant_reason(row, job) or filter_reason(job["title"], job["company"], job["description"])
        
        if reason:
            decision("bad", f"rejected: {short_reason(reason)}")
            save_filtered(job, reason)
            filtered_count += 1
            continue

        original = known.duplicate_of(job)
        if original:
            decision("skip", f"skipped: duplicate of {original['company'][:25]}")
            save_job(job, {"match_score": 0.0, "matched_skills": [], "gaps": duplicate_gap(original)},
                     status="duplicate", model_score=0.0, duplicate_of=original["job_url"])
            duplicates += 1
            continue

        try:
            score = score_job(job["title"], job["company"], job["location"], job["description"])
            # Final score = model score blended with the keyword score, tuned by rating.py
            model_score = score["match_score"]
            keyword = keyword_score(job["title"], job["description"])
            score = {**score, "match_score": blend(model_score, keyword, cal)}
            compat = compute_compat(job, score, score["match_score"])
            consecutive_failures = 0
        except Exception as e:
            decision("bad", f"failed: scoring error ({e})")
            score = {"match_score": FAILED_SCORE, "matched_skills": [], "gaps": ["scoring failed"]}
            model_score = keyword = compat = None
            consecutive_failures += 1

        save_job(job, score, model_score=model_score, keyword_score=keyword, compat=compat)

        if score["match_score"] >= 0:
            final = score["match_score"]
            if final <= 0:
                why = (score.get("gaps") or ["scored 0"])[0]
                decision("bad", f"rejected: {why}")
            else:
                text = f"scored: suitability {final:g}/10 · compatibility {compat_text(compat)}"
                if final >= doc_min_score:
                    mode = choose_mode({"compat_pct": (compat or {}).get("pct"),
                                        "compat_detail_pct": (compat or {}).get("detail_pct")})[0]
                    decision("ok", f"{text} · {mode} documents")
                else:
                    decision("skip", f"{text} · below your minimum of {doc_min_score:g}")
            results.append((final, job))
            known.add(job)

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            print()
            decision("bad", f"stopped: {MAX_CONSECUTIVE_FAILURES} failures in a row. Is Ollama running "
                            f"and is '{MODEL}' pulled? Progress so far is saved.")
            break

    # ---- 5 RESULTS
    shown_urls = show_results(results, filtered_count, duplicates, doc_min_score)

    # ---- 6 DOCUMENTS: resume + cover letter for the best matches
    if make_docs:
        generate_documents(doc_min_score, max_docs)

    show_summary(shown_urls)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape, filter, score and save jobs, then make documents.")
    add_profile_arguments(parser)
    apply_profile_arguments(parser.parse_args())
    # Search terms, location and the other settings still come from config/settings.py (profiles: phase 2).
    asyncio.run(main(
        site_names=SITES,
        search_term=SEARCH_TERMS,
        location=LOCATION,
    ))
