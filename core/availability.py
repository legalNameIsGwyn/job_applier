"""Is a posting still open?

mark_closed_elsewhere(): new jobs from sites other than LinkedIn (LinkedIn is read from the page the description fetch downloads).
recheck_stored(): jobs already saved that have documents (main.py, or python -m tools.check --availability).

mark_closed_elsewhere() asks each job's own site through core.job_status.check_open(): one extra request per job, so it
only runs when CHECK_AVAILABILITY_OTHER_SITES is on, and only for jobs that already passed the earlier rules. A site that
doesn't say ("unknown") counts as open. The result is the same "closed" column the LinkedIn fetch fills.
"""

import random
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta

import pandas as pd

from config.settings import (
    AVAILABILITY_RECHECK_DAYS, CHECK_AVAILABILITY_OTHER_SITES, DB_PATH, DESCRIPTION_FETCH_ATTEMPTS,
    DESCRIPTION_FETCH_DELAY, RATE_LIMIT_BACKOFF_SECONDS,
)
from core import csv_log
from core.console import INDENT, link, tag
from core.job_status import check_open


def _label(row) -> str:
    parts = [str(row.get(c)).strip() for c in ("title", "company") if str(row.get(c) or "").strip() not in ("", "nan", "None")]
    label = " · ".join(parts) or str(row.get("job_url", ""))
    return label if len(label) <= 60 else label[:59].rstrip() + "…"


def mark_closed_elsewhere(df: pd.DataFrame, enabled: bool = CHECK_AVAILABILITY_OTHER_SITES, check=check_open,
                          delay=DESCRIPTION_FETCH_DELAY) -> pd.DataFrame:
    """Set df["closed"] = True for non-LinkedIn postings their site says are closed. Returns a copy."""
    df = df.copy()
    if "closed" not in df.columns:
        df["closed"] = False
    if not enabled:
        return df
    todo = [idx for idx, row in df.iterrows()
            if "linkedin.com" not in str(row.get("job_url", "")) and str(row.get("job_url", "")).startswith("http")]
    if not todo:
        return df
    tag("AVAILABILITY", f"Asking {len(todo)} job(s) on other sites whether they are still open.")
    for n, idx in enumerate(todo, start=1):
        row = df.loc[idx]
        status = check(row["job_url"])
        if status == "closed":
            df.at[idx, "closed"] = True
            tag("AVAILABILITY", f"{n}/{len(todo)}: {_label(row)}: closed", "warn")
        else:
            tag("AVAILABILITY", f"{n}/{len(todo)}: {_label(row)}: {'open' if status == 'open' else 'no answer, kept'}")
        if n < len(todo):
            time.sleep(random.uniform(*delay))
    return df


# ------------------------------------------------------------------------------------ jobs already saved

PROTECTED = ("applied", "skipped", "closed")   # an application row in one of these: leave the job alone


def pick_rows(csv_rows: list, db_jobs: dict, app_status: dict, tracked: set, skip: set,
              days: float = AVAILABILITY_RECHECK_DAYS, today: date | None = None) -> tuple[list, dict]:
    """Which CSV rows (jobs with documents and no status yet) to check. Returns (rows, why the others were left out).

    db_jobs: url -> (job id, last_checked datetime or None); app_status: job id -> applications.status.
    """
    today = today or date.today()
    out, left = [], {"this run": 0, "applied or handled": 0, "checked recently": 0}
    for row in csv_rows:
        url = row["job_url"]
        job_id, stamp = db_jobs.get(url, (None, None))
        if url in skip:
            left["this run"] += 1
        elif url in tracked or app_status.get(job_id) in PROTECTED:
            left["applied or handled"] += 1
        else:
            last = stamp.date() if stamp else None
            if last is None and row.get("last_checked"):
                try:
                    last = date.fromisoformat(row["last_checked"][:10])
                except ValueError:
                    pass
            if days and last and (today - last) < timedelta(days=days):
                left["checked recently"] += 1
            else:
                out.append(row)
    return out, left


def check_with_retries(url: str, check=check_open, tries: int = DESCRIPTION_FETCH_ATTEMPTS,
                       backoff: float = RATE_LIMIT_BACKOFF_SECONDS, sleep=time.sleep, log=tag) -> str:
    """open / closed / unknown. A LinkedIn job that gets no answer (a 429, usually) is tried again after a wait;
    other sites are asked once, because 'unknown' from them is a real answer."""
    tries = max(1, int(tries)) if "linkedin.com" in url else 1
    status = "unknown"
    for attempt in range(1, tries + 1):
        status = check(url)
        if status != "unknown" or attempt == tries:
            break
        log("AVAILABILITY", f"No answer (try {attempt}/{tries}), waiting {backoff * attempt:g}s...", "warn")
        sleep(backoff * attempt)
    return status


def _load(db_path) -> tuple[dict, dict, set]:
    from sqlalchemy import select
    from db.models import Application, Job, Tracking
    from db.session import session_scope
    with session_scope(db_path) as s:
        db_jobs = {u: (i, c) for u, i, c in s.execute(select(Job.job_url, Job.id, Job.last_checked)).all() if u}
        app_status = {i: st for i, st in s.execute(select(Application.job_id, Application.status)).all()}
        tracked = set(s.scalars(select(Tracking.job_url)))
    return db_jobs, app_status, tracked


def _stamp(url: str, db_path) -> None:
    from sqlalchemy import select
    from db.models import Job, utcnow
    from db.session import session_scope
    with session_scope(db_path) as s:
        job = s.scalar(select(Job).where(Job.job_url == url))
        if job is not None:
            job.last_checked = utcnow()


def recheck_stored(skip_urls=(), db_path=DB_PATH, days: float = AVAILABILITY_RECHECK_DAYS, check=check_open,
                   delay=DESCRIPTION_FETCH_DELAY, sleep=time.sleep) -> dict:
    """Ask each saved job that has documents (a row in the CSV with no status) whether it is still open.

    Skipped: jobs in skip_urls (this run's scrape), jobs with an application row that is applied / skipped / closed,
    jobs you track, and jobs checked within `days` days (0 = never skip). A job found closed gets an applications row
    with status 'closed' (its score and documents stay) and 'closed' in a blank CSV status cell. Every answer stamps
    last_checked; a job that gives no answer is left unstamped and is tried again next run. No cap.
    Returns counts: checked, closed, open, no_answer, and unanswered (the CSV rows that gave no answer, for ask_about).
    """
    from db.repo import record_application
    counts = {"checked": 0, "closed": 0, "open": 0, "no_answer": 0, "unanswered": []}
    if not csv_log.enabled():
        tag("AVAILABILITY", "CSV_LOG is off, so there is no list of jobs with documents to check.")
        return counts
    db_jobs, app_status, tracked = _load(db_path)
    todo, left = pick_rows(csv_log.open_rows(), db_jobs, app_status, tracked, set(skip_urls), days)
    skipped = ", ".join(f"{n} {why}" for why, n in left.items() if n)
    tag("AVAILABILITY", f"Re-checking {len(todo)} saved job(s) that have documents" + (f" (left out: {skipped})" if skipped else "") + ".")
    updates = {}
    try:
        for n, row in enumerate(todo, start=1):
            url = row["job_url"]
            label = _label({"title": row["title"], "company": row["company"], "job_url": url})
            tag("AVAILABILITY", f"Checking {n}/{len(todo)}: {label}")
            print(INDENT + "  " + link(url))
            status = check_with_retries(url, check, sleep=sleep)
            if status == "unknown":
                counts["no_answer"] += 1
                counts["unanswered"].append(row)
                tag("AVAILABILITY", "No answer; it will be checked again next run.", "warn")
            else:
                counts["checked"] += 1
                counts[status] += 1
                updates[url] = {"last_checked": date.today().isoformat()}
                _stamp(url, db_path)
                if status == "closed":
                    record_application(url, "closed", note="Posting is no longer open (found by the availability re-check)",
                                       db_path=db_path)
                    updates[url]["status"] = "closed"
                    tag("AVAILABILITY", "The posting is closed. Marked closed.", "warn")
                else:
                    tag("AVAILABILITY", "Still open.", "ok")
            if n < len(todo):
                sleep(random.uniform(*delay))
    finally:   # also on Ctrl-C: what was checked so far is written down
        csv_log.update_rows(updates)
    tag("AVAILABILITY", f"{counts['open']} open, {counts['closed']} closed"
        + (f", {counts['no_answer']} gave no answer (retried next run)" if counts["no_answer"] else "") + ".")
    return counts


def mark_jobs(urls, as_status: str = "closed", db_path=DB_PATH) -> dict:
    """Mark jobs closed (or open again) by hand, for when you checked the posting yourself.

    closed: an applications row with status 'closed' and 'closed' in a blank CSV status cell.
    open:   removes a 'closed' mark (an applications row that says closed, and a CSV cell that says closed).
    A job you applied to is never changed. Both stamp last_checked. Returns counts: done, skipped.
    """
    from sqlalchemy import select
    from db.models import Application, Job
    from db.repo import record_application
    from db.session import session_scope
    counts, updates = {"done": 0, "skipped": 0}, {}
    today = date.today().isoformat()
    for url in dict.fromkeys(u.strip() for u in urls if u.strip()):
        with session_scope(db_path) as s:
            job = s.scalar(select(Job).where(Job.job_url == url))
            app = s.scalar(select(Application).where(Application.job_id == job.id)) if job else None
            current = app.status if app else None
        if current == "applied":
            counts["skipped"] += 1
            tag("MARK", f"Left alone (you applied to it): {url}", "warn")
            continue
        if as_status == "closed":
            if job and not record_application(url, "closed", note="Marked closed by hand", db_path=db_path):
                counts["skipped"] += 1
                continue
            updates[url] = {"status": "closed", "last_checked": today}
        else:
            if current == "closed":
                with session_scope(db_path) as s:
                    s.delete(s.scalar(select(Application).where(Application.job_id == job.id)))
            updates[url] = {"clear_status": "closed", "last_checked": today}
        if job:
            _stamp(url, db_path)
        counts["done"] += 1
        tag("MARK", f"{'Marked closed' if as_status == 'closed' else 'Marked open again'}"
            + ("" if job else " (not in the database, so only the CSV was changed)") + f": {url}", "ok")
    csv_log.update_rows(updates)
    return counts


def ask_about(rows: list, db_path=DB_PATH, ask=input, opener=webbrowser.open, open_each: bool = False) -> dict:
    """Walk through jobs the sites would not answer for and let YOU say whether each is still open.

    With open_each, each link is opened in your browser first, one job at a time.
    For every job: its link, then  o = still open · c = closed · b = open the link in your browser · s = skip for now
    · q = stop asking. 'o' and 'c' are saved like a re-check answer (a closed job is marked closed, an open one is not
    asked about again for AVAILABILITY_RECHECK_DAYS days). A skipped job is asked about again next run.
    Returns counts: open, closed, skipped.
    """
    counts = {"open": 0, "closed": 0, "skipped": 0}
    for n, row in enumerate(rows, start=1):
        url = row["job_url"]
        print()
        tag("CHECK YOURSELF", f"{n}/{len(rows)}: " + _label({"title": row["title"], "company": row["company"], "job_url": url}))
        print(INDENT + "  " + link(url))
        if open_each:
            opener(url)
        while True:
            try:
                answer = ask("   Still open?  [o]pen  [c]losed  [b]rowser  [s]kip  [q]uit > ").strip().lower()[:1] or "s"
            except (EOFError, KeyboardInterrupt):
                answer = "q"
            if answer == "b":
                opener(url)
                continue
            if answer in ("o", "c", "s", "q"):
                break
            print("   Type o, c, b, s or q.")
        if answer == "q":
            counts["skipped"] += len(rows) - n + 1
            break
        if answer == "s":
            counts["skipped"] += 1
        else:
            mark_jobs([url], "closed" if answer == "c" else "open", db_path)
            counts["closed" if answer == "c" else "open"] += 1
    tag("CHECK YOURSELF", f"{counts['open']} open, {counts['closed']} closed, {counts['skipped']} skipped.")
    return counts


def can_ask() -> bool:
    """Only ask when someone is at the keyboard (not in a scheduled or piped run)."""
    return bool(sys.stdin and sys.stdin.isatty())