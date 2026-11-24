"""Open job applications in a browser and fill them in for you. It NEVER clicks Submit.

    python apply_jobs.py --list                 # which jobs qualify and where they would be filled
    python apply_jobs.py                        # fill the best jobs (APPLY_* settings)
    python apply_jobs.py --top 3                # at most 3 jobs this run
    python apply_jobs.py --min-score 8          # only jobs scoring 8+
    python apply_jobs.py --url <job url>        # one specific job from your database
    python apply_jobs.py --set-url <job url> <employer application url>
                                                # save the employer's own link for a job
    python apply_jobs.py --include-opened       # offer jobs you opened before but didn't finish
    python apply_jobs.py --recheck-links        # forget "no link found" results and search again
    python apply_jobs.py --login                # log in to LinkedIn by hand, once (or --login indeed)
    python apply_jobs.py --profile it_support   # use another profile's scores

LinkedIn jobs: LinkedIn hides the employer's link from logged-out visitors, so each job is searched
for on the company's public Greenhouse / Lever / Ashby job board (AUTO_FIND_LINKS in
config/apply_settings.py) and the result is saved, once per job. --recheck-links searches again.

For each job it opens the application, uploads this job's resume and cover letter (making them
first if needed), fills every field it has an answer for, and then waits. Read the form, fix
anything wrong, press Submit yourself, then tell the terminal what happened.

First time only:   pip install playwright    then    playwright install chromium
Settings: config/apply_settings.py (which jobs, which sites)   config/answers.py (the answers)
"""

import argparse
from pathlib import Path

import db.tracking as tracking
from applying.answering import Answerer
from documents.application_maker import create_application, job_folder, name_fields, render_name
from applying.ats import (CLICK_CHECKED, GENERIC_SITES, IMPLEMENTED, NO_LINK, NO_LINK_MARKERS, application_url, detect_ats,
                 site_key)
from config.apply_settings import (
    APPLY_MAX_PER_RUN, APPLY_WINDOW_DAYS, AUTO_FIND_LINKS, BROWSER_PROFILE_DIR, ENABLED_SITES,
    CHECK_STILL_OPEN, FIND_LINKS_MAX, HEADLESS, LINKEDIN_CLICK_APPLY, LINKEDIN_CLICK_DELAY, LINKEDIN_CLICK_MAX, PAGE_TIMEOUT_MS,
    SLOW_MO_MS, WORKDAY_AUTO_ADVANCE, WORKDAY_MAX_STEPS,
)
import config.apply_settings as _cfg
from config.settings import COVER_LETTER_FILENAME, DB_PATH, RESUME_FILENAME, MIN_SCORE
from db.queries import clear_missing_link_markers, get_candidates   # get_candidates: also imported by tools/summary.py
from db.repo import init_db, record_application, set_apply_url
from db.session import add_profile_arguments, apply_profile_arguments
from applying.form_filler import fill_form, open_application
from applying.fill_report import save_fill_report
from core.job_status import check_open, closed_in_text
from core.scorer import load_resume
from core.console import decision, fmt_score, job_head, step, tag

# Optional settings (defaults apply if config/apply_settings.py doesn't have them yet)
GENERIC_AUTO_ADVANCE = getattr(_cfg, "GENERIC_AUTO_ADVANCE", True)
GENERIC_MAX_STEPS = getattr(_cfg, "GENERIC_MAX_STEPS", 10)
BROWSER = getattr(_cfg, "BROWSER", "chromium")
PARALLEL_JOBS = getattr(_cfg, "PARALLEL_JOBS", 3)


# --------------------------------------------------------------------------- choosing jobs
# get_candidates (scored jobs worth applying to that you haven't dealt with yet, best first, for the
# active profile) lives in db/queries.py.


def target_for(job: dict) -> tuple[str | None, str | None, str | None]:
    """(url to open, ATS name, reason it can't be filled or None).

    Uses the employer's own link (apply_url) when there is one; otherwise the job-board link,
    which only works if that link itself is a Greenhouse / Lever / Ashby page.
    """
    if job.get("apply_url") in NO_LINK_MARKERS:
        return job["job_url"], "linkedin", ("no employer application link found (it may be LinkedIn Easy Apply); "
                                            "use --set-url if you have the link")
    link = job.get("apply_url") or job["job_url"]
    ats = detect_ats(link)
    if ats == "linkedin" and not job.get("apply_url"):
        return link, ats, "employer link not looked up yet (raise LINKEDIN_CLICK_MAX, or run again)"
    if ats is None:
        return link, None, "not a supported application site (use --set-url to give the employer's link)"
    if ats == "jobboard":
        return link, ats, "that's a job board, not an application page (use --set-url with the employer's link)"
    key = site_key(ats)
    if not ENABLED_SITES.get(key, key == "generic"):   # "generic" is on unless you turn it off
        return link, ats, f"{key} is turned off in config/apply_settings.py"
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


def find_employer_links(jobs: list[dict]) -> int:
    """Find the employer's application link for jobs that don't have one yet.

    LinkedIn hides that link from logged-out visitors, so each job is looked up on the company's
    own public Greenhouse / Lever / Ashby board (same company and title). The result is saved:
    the link if found, or "none" so the job isn't searched for again. Returns how many were searched.
    """
    try:
        from applying.ats_lookup import LinkFinder
    except ImportError:
        tag("APPLY", "ats_lookup.py not found; skipping the company-board search.")
        return 0

    todo = [j for j in jobs if not j.get("apply_url") and "linkedin.com" in j["job_url"]][:FIND_LINKS_MAX]
    if not todo:
        return 0
    tag("APPLY", f"Searching company job boards (Greenhouse, Lever, Ashby) for {len(todo)} job(s)...")
    finder, found = LinkFinder(), 0
    for job in todo:
        link = finder.find(job["company"], job["title"], job.get("location", ""))
        set_apply_url(job["job_url"], link or NO_LINK)
        job["apply_url"] = link or NO_LINK
        found += bool(link)
    tag("APPLY", f"Found a direct application page for {found} of {len(todo)}.")
    return len(todo)


def _open_profile(playwright, profile_dir=None):
    return getattr(playwright, BROWSER).launch_persistent_context(
        str(profile_dir or BROWSER_PROFILE_DIR), headless=HEADLESS, slow_mo=SLOW_MO_MS, no_viewport=True)


def resolve_via_linkedin(jobs: list[dict]) -> int:
    """Opt-in: click Apply on LinkedIn (in your logged-in browser) for jobs the board search missed."""
    from applying.linkedin_resolver import resolve_links
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 0
    # jobs with no link yet (never searched) or that the board search found nothing for
    todo = [j for j in jobs if (not j.get("apply_url") or j["apply_url"] == NO_LINK)
            and "linkedin.com" in j["job_url"]][:LINKEDIN_CLICK_MAX]
    if not todo:
        return 0
    tag("APPLY", f"Opening {len(todo)} LinkedIn posting(s) in your logged-in browser to find the employer link...")
    with sync_playwright() as p:
        context = _open_profile(p)
        try:
            results = resolve_links(context, [j["job_url"] for j in todo], LINKEDIN_CLICK_DELAY)
        finally:
            context.close()
    found = closed = 0

    for job in todo:
        outcome, url = results.get(job["job_url"], ("login", None))
        if outcome == "link" and url:
            set_apply_url(job["job_url"], url)
            job["apply_url"] = url
            found += 1
        elif outcome == "closed":
            record_application(job["job_url"], "closed", ats="linkedin",
                               note="LinkedIn says it is no longer taking applications")
            jobs.remove(job)   # drop it from this run
            closed += 1
        elif outcome in ("easy", "unknown"):  # remember we tried, so it isn't clicked again every run
            set_apply_url(job["job_url"], CLICK_CHECKED)
            job["apply_url"] = CLICK_CHECKED
    tag("APPLY", f"Found {found} employer link(s) through LinkedIn."
          + (f" {closed} posting(s) are closed and were dropped." if closed else ""))
    return found


def login(site: str = "linkedin") -> None:
    """Open the saved browser profile on a sign-in page so you can log in by hand, once."""
    from playwright.sync_api import sync_playwright
    url = {"linkedin": "https://www.linkedin.com/login", "indeed": "https://secure.indeed.com/auth"}[site]
    with sync_playwright() as p:
        context = _open_profile(p)
        try:
            page = context.new_page()
            page.goto(url)
            input(f"Log in to {site} in the browser window (including any verification), then press Enter here: ")
        finally:
            context.close()
    tag("APPLY", "Saved. Your login is remembered in the browser profile folder.")


def forget_missing_links(db_path: str = DB_PATH) -> int:
    """Clear every "none" marker so those jobs are searched for again."""
    return clear_missing_link_markers(NO_LINK_MARKERS, db_path)


# ----------------------------------------------------------------------------- one job


def apply_to_job(context, job: dict, url: str, ats: str, ask=input, answerer=None) -> str:
    """Fill one application and wait for you. Returns applied | skipped | opened | closed."""
    resume = load_resume()
    resume_file, letter_file = document_files(job)
    answerer = answerer or Answerer(resume, job, ask=ask)

    pages_filled = []                    # every page's Report, saved to the job's fill_report.txt at the end

    def capture(report) -> None:
        pages_filled.append(report)
        print_report(report)             # looked up when called, so the parallel worker's replacement still applies

    page = context.new_page()
    result = "error"                     # stays "error" if something raises before you answer
    try:
        if ats == "workday":
            import applying.workday as workday
            outcome = workday.run_application(page, url, answerer, resume_file, letter_file, ask=ask, show=print,
                                              show_report=capture, auto_advance=WORKDAY_AUTO_ADVANCE,
                                              max_steps=WORKDAY_MAX_STEPS)
            if outcome == "closed":
                print("  The page text says this posting is closed. Not recording it as closed; check it in the browser.")
        elif ats in GENERIC_SITES:
            import applying.generic as generic
            outcome = generic.run_application(page, url, answerer, resume_file, letter_file, ask=ask, show=print,
                                              show_report=capture, auto_advance=GENERIC_AUTO_ADVANCE,
                                              max_steps=GENERIC_MAX_STEPS, timeout_ms=PAGE_TIMEOUT_MS)
            if outcome == "closed":
                print("  The page text says this posting is closed. Not recording it as closed; check it in the browser.")
        else:
            frame = open_application(page, url, PAGE_TIMEOUT_MS)
            try:
                body = page.inner_text("body", timeout=5000)
            except Exception:
                body = ""
            if closed_in_text(body[:20000]) and frame is None:
                print("  The page text says this posting is closed. Not recording it as closed; check it in the browser.")
            if frame is None:
                print("  Couldn't find the application form on that page. It's open in the browser for you.")
            else:
                if closed_in_text(body[:3000]):
                    print("  WARNING: the page mentions the job being closed or unavailable. Check before filling in more.")
                capture(fill_form(frame, answerer, resume_file, letter_file))
        reply = ask("\n  Review the form, fix anything, and submit it yourself in the browser.\n"
                    "  Then type  a = I submitted it,  s = skip this job for good,  Enter = not yet: ")
        reply = reply.strip().lower()
        result = "applied" if reply.startswith("a") else "skipped" if reply.startswith("s") else "opened"
    finally:
        page.close()
        saved = save_fill_report(job_folder(job), job, url, ats, pages_filled, result)
        if saved:
            print(f"  Fill report saved: {saved}")
    return result


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


def run(limit, min_score, days, include_opened=False, url=None, list_only=False, parallel=PARALLEL_JOBS) -> None:
    init_db()
    jobs = get_candidates(min_score, days, include_opened, url)
    if not jobs:
        tag("APPLY", "No jobs to apply to (score too low, nothing recent, or all already handled).")
        return

    if AUTO_FIND_LINKS:
        find_employer_links(jobs)
    if LINKEDIN_CLICK_APPLY and not list_only:
        resolve_via_linkedin(jobs)

    ready = []
    for job in jobs:
        link, ats, reason = target_for(job)
        print()
        job_head(f"{fmt_score(job['match_score'])}  {job['title']}", job["company"], link or job["job_url"])
        status = check_open(link) if (CHECK_STILL_OPEN and not reason) else "open"
        if reason:
            decision("skip", f"skip: {reason}")
        elif status == "closed":
            decision("bad", "closed: the posting is no longer open")
            record_application(job["job_url"], "closed", apply_url=link, ats=ats)
        else:
            decision("ok", f"ready: {ats}{' (generic filler, best effort)' if ats in GENERIC_SITES else ''}")
            if status == "maybe_closed":
                print("  WARNING: the page text mentions the job being closed. Not recorded as closed; check it when the form opens.")
            ready.append((job, link, ats))
    print()
    tag("APPLY", f"{len(ready)} of {len(jobs)} job(s) can be filled.")

    if list_only or not ready or limit <= 0:
        return

    if parallel > 1 and len(ready[:limit]) > 1:
        from applying.worker import launch_all
        launch_all(ready[:limit], parallel, prepare=document_files)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        tag("APPLY", "Playwright isn't installed. Run:  pip install playwright   then   playwright install chromium")
        return

    done = 0
    with sync_playwright() as p:
        context = _open_profile(p)
        try:
            for job, link, ats in ready[:limit]:
                step(None, "APPLYING", right=f"score {fmt_score(job['match_score'])}")
                print()
                job_head(job["title"], job["company"], link)
                try:
                    status = apply_to_job(context, job, link, ats)
                except KeyboardInterrupt:
                    print()
                    tag("APPLY", "Stopped.")
                    break
                except Exception as e:
                    print(f"  Failed: {e}")
                    continue
                record_application(job["job_url"], status, apply_url=link, ats=ats)
                if status == "applied":
                    try:
                        tracking.log_applied(job["job_url"], ats=ats, folder=job_folder(job).name)
                    except Exception as e:   # tracking must never break applying
                        print(f"  (couldn't start tracking: {e})")
                done += 1
                print(f"  Recorded as: {status}")
        finally:
            context.close()
    print()
    tag("APPLY", f"Opened {done} application(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fill job applications in a browser. Never submits.")
    parser.add_argument("--top", type=int, default=APPLY_MAX_PER_RUN, help="most jobs to open this run")
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--days", type=int, default=APPLY_WINDOW_DAYS)
    parser.add_argument("--url", help="apply to this job (its URL in your database)")
    parser.add_argument("--set-url", nargs=2, metavar=("JOB_URL", "APPLY_URL"),
                        help="save the employer's own application link for a job")
    parser.add_argument("--include-opened", action="store_true", help="also offer jobs you opened but didn't finish")
    parser.add_argument("--recheck-links", action="store_true", help="search again for jobs marked 'no link found'")
    parser.add_argument("--login", nargs="?", const="linkedin", choices=["linkedin", "indeed"],
                        help="open the saved browser on a sign-in page so you can log in by hand")
    parser.add_argument("--list", action="store_true", help="show what would be filled; open nothing")
    parser.add_argument("--parallel", type=int, default=PARALLEL_JOBS, help="applications open at once, each in its own window (1 = one at a time here)")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)

    if args.login:
        login(args.login)
        raise SystemExit
    if args.recheck_links:
        init_db()
        tag("APPLY", f"Cleared {forget_missing_links()} 'no link found' result(s).")
    if args.set_url:
        init_db()
        ok = set_apply_url(*args.set_url)
        tag("APPLY", "Saved." if ok else "That job URL isn't in the database.")
    else:
        run(args.top, args.min_score, args.days, args.include_opened, args.url, args.list, args.parallel)