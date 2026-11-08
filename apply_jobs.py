"""Open job applications in a browser and fill them in for you. It NEVER clicks Submit.

    python apply_jobs.py --list                 # which jobs qualify and where they would be filled
    python apply_jobs.py                        # fill the best jobs (APPLY_* settings)
    python apply_jobs.py --top 3                # at most 3 jobs this run
    python apply_jobs.py --min-score 8          # only jobs scoring 8+
    python apply_jobs.py --url <job url>        # one specific job from your database
    python apply_jobs.py --set-url <job url> <employer application url>
                                                # save the employer's own link for a job
    python apply_jobs.py --include-opened       # offer jobs you opened before but didn't finish

For each job it opens the application, uploads this job's resume and cover letter (making them
first if needed), fills every field it has an answer for, and then waits. Read the form, fix
anything wrong, press Submit yourself, then tell the terminal what happened.

First time only:   pip install playwright    then    playwright install chromium
Settings: config/apply_settings.py (which jobs, which sites)   config/answers.py (the answers)
"""

import argparse
import sqlite3
from pathlib import Path

from answering import Answerer
from application_maker import create_application, job_folder, name_fields, render_name
from ats import IMPLEMENTED, application_url, detect_ats
from config.apply_settings import (
    APPLY_MAX_PER_RUN, APPLY_MIN_SCORE, APPLY_WINDOW_DAYS, BROWSER_PROFILE_DIR, ENABLED_SITES, HEADLESS,
    PAGE_TIMEOUT_MS, SLOW_MO_MS,
)
from config.settings import COVER_LETTER_FILENAME, RESUME_FILENAME
from db import DB_PATH, init_db, record_application, set_apply_url
from form_filler import fill_form, open_application
from scorer import load_resume

JOB_COLUMNS = ("title", "company", "location", "job_url", "description", "match_score", "apply_url", "site")


# --------------------------------------------------------------------------- choosing jobs


def get_candidates(min_score, days, include_opened=False, url=None, db_path=DB_PATH) -> list[dict]:
    """Scored jobs worth applying to that you haven't dealt with yet, best first."""
    statuses = "(a.status IS NULL OR a.status = 'opened')" if include_opened else "a.status IS NULL"
    sql = (f"SELECT {', '.join('j.' + c for c in JOB_COLUMNS)} FROM jobs j "
           "LEFT JOIN applications a ON a.job_url = j.job_url WHERE j.job_url IS NOT NULL AND ")
    if url:
        sql, params = sql + "j.job_url = ?", [url]
    else:
        sql += (f"j.status = 'scored' AND j.match_score >= ? AND j.scraped_at >= datetime('now', ?) "
                f"AND {statuses} ORDER BY j.match_score DESC")
        params = [min_score, f"-{int(days)} days"]
    conn = sqlite3.connect(db_path)
    try:
        return [dict(zip(JOB_COLUMNS, row)) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def target_for(job: dict) -> tuple[str | None, str | None, str | None]:
    """(url to open, ATS name, reason it can't be filled or None).

    Uses the employer's own link (apply_url) when there is one; otherwise the job-board link,
    which only works if that link itself is a Greenhouse / Lever / Ashby page.
    """
    link = job.get("apply_url") or job["job_url"]
    ats = detect_ats(link)
    if ats is None:
        return link, None, "not a supported application site (use --set-url to give the employer's link)"
    if not ENABLED_SITES.get(ats, False):
        return link, ats, f"{ats} is turned off in config/apply_settings.py"
    if ats not in IMPLEMENTED:
        return link, ats, f"the {ats} filler isn't built yet"
    return application_url(ats, link), ats, None


def document_files(job: dict) -> tuple[Path, Path]:
    """This job's resume and cover letter paths, creating them first if they don't exist."""
    folder = job_folder(job)
    if not folder.exists():
        print("  Making this job's resume and cover letter first...")
        create_application(job)
    fields = name_fields(load_resume(), job)
    return (folder / f"{render_name(RESUME_FILENAME, fields)}.docx",
            folder / f"{render_name(COVER_LETTER_FILENAME, fields)}.docx")


# ----------------------------------------------------------------------------- one job


def apply_to_job(context, job: dict, url: str, ats: str, ask=input, answerer=None) -> str:
    """Fill one application and wait for you. Returns applied | skipped | opened."""
    resume = load_resume()
    resume_file, letter_file = document_files(job)
    answerer = answerer or Answerer(resume, job, ask=ask)

    page = context.new_page()
    try:
        frame = open_application(page, url, PAGE_TIMEOUT_MS)
        if frame is None:
            print("  Couldn't find the application form on that page. It's open in the browser for you.")
        else:
            report = fill_form(frame, answerer, resume_file, letter_file)
            print_report(report)
        reply = ask("\n  Review the form, fix anything, and submit it yourself in the browser.\n"
                    "  Then type  a = I submitted it,  s = skip this job for good,  Enter = not yet: ")
    finally:
        page.close()
    reply = reply.strip().lower()
    return "applied" if reply.startswith("a") else "skipped" if reply.startswith("s") else "opened"


def print_report(report) -> None:
    if report.uploaded:
        print(f"  Uploaded: {', '.join(report.uploaded)}")
    for label, value, source in report.filled:
        print(f"  [{source:>7}] {label[:55]}: {value}")
    if report.attention:
        print("  NEEDS YOUR ATTENTION:")
        for label, why in report.attention:
            print(f"    - {label[:60]}: {why}")


# --------------------------------------------------------------------------------- CLI


def run(limit, min_score, days, include_opened=False, url=None, list_only=False) -> None:
    init_db()
    jobs = get_candidates(min_score, days, include_opened, url)
    if not jobs:
        print("[APPLY] No jobs to apply to (score too low, nothing recent, or all already handled).")
        return

    ready = []
    for job in jobs:
        link, ats, reason = target_for(job)
        label = f"{job['match_score']:g}  {job['title'][:45]} - {job['company'][:25]}"
        if reason:
            print(f"[APPLY] skip  {label}\n          {reason}")
        else:
            print(f"[APPLY] ready {label}  [{ats}]")
            ready.append((job, link, ats))
    print(f"\n[APPLY] {len(ready)} of {len(jobs)} job(s) can be filled.")
    if list_only or not ready:
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[APPLY] Playwright isn't installed. Run:  pip install playwright   then   playwright install chromium")
        return

    done = 0
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR), headless=HEADLESS, slow_mo=SLOW_MO_MS, no_viewport=True)
        try:
            for job, link, ats in ready[:limit]:
                print(f"\n{'=' * 60}\n[APPLY] {job['title']} - {job['company']}  (score {job['match_score']:g})\n  {link}")
                try:
                    status = apply_to_job(context, job, link, ats)
                except KeyboardInterrupt:
                    print("\n[APPLY] Stopped.")
                    break
                except Exception as e:
                    print(f"  Failed: {e}")
                    continue
                record_application(job["job_url"], status, apply_url=link, ats=ats)
                done += 1
                print(f"  Recorded as: {status}")
        finally:
            context.close()
    print(f"\n[APPLY] Opened {done} application(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fill job applications in a browser. Never submits.")
    parser.add_argument("--top", type=int, default=APPLY_MAX_PER_RUN, help="most jobs to open this run")
    parser.add_argument("--min-score", type=float, default=APPLY_MIN_SCORE)
    parser.add_argument("--days", type=int, default=APPLY_WINDOW_DAYS)
    parser.add_argument("--url", help="apply to this job (its URL in your database)")
    parser.add_argument("--set-url", nargs=2, metavar=("JOB_URL", "APPLY_URL"),
                        help="save the employer's own application link for a job")
    parser.add_argument("--include-opened", action="store_true", help="also offer jobs you opened but didn't finish")
    parser.add_argument("--list", action="store_true", help="show what would be filled; open nothing")
    args = parser.parse_args()

    if args.set_url:
        init_db()
        ok = set_apply_url(*args.set_url)
        print("[APPLY] Saved." if ok else "[APPLY] That job URL isn't in the database.")
    else:
        run(args.top, args.min_score, args.days, args.include_opened, args.url, args.list)
