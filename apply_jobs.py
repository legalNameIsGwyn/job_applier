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
    python apply_jobs.py --parked               # open the jobs set aside because they needed you, best score first
    python apply_jobs.py --parked --list        # just show them
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
import re
from collections import Counter
from pathlib import Path

import db.tracking as tracking
from applying.answering import Answerer
from applying.blocked import Blocked, NO_FORM, parking_enabled, set_parking
from applying.notify import notify
from documents.application_maker import create_application, job_folder, name_fields, render_name
from applying.ats import (EASY_APPLY, GENERIC_SITES, IMPLEMENTED, NO_LINK, NO_LINK_MARKERS, RECHECKABLE_MARKERS, application_url, detect_ats,
                 site_key)
from config.apply_settings import (
    APPLY_MAX_PER_RUN, APPLY_WINDOW_DAYS, AUTO_FIND_LINKS, BROWSER_PROFILE_DIR, ENABLED_SITES,
    CHECK_STILL_OPEN, FIND_LINKS_MAX, HEADLESS, LINKEDIN_CLICK_APPLY, LINKEDIN_CLICK_ATTEMPTS, LINKEDIN_CLICK_DELAY, LINKEDIN_CLICK_MAX, PAGE_TIMEOUT_MS,
    SLOW_MO_MS, WORKDAY_AUTO_ADVANCE, WORKDAY_MAX_STEPS,
)
import config.apply_settings as _cfg
from config.settings import COVER_LETTER_FILENAME, DB_PATH, RESUME_FILENAME, MIN_SCORE
from db.queries import clear_missing_link_markers, get_candidates, parked_jobs   # get_candidates: also imported by tools/summary.py
from db.repo import init_db, record_application, record_parked, set_apply_url
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments
from applying.form_filler import fill_form, open_application
from applying.fill_report import save_fill_report
from core.job_status import check_open, closed_in_text
from core.scorer import MODEL, load_resume
from core.console import INDENT, banner, decision, fmt_score, job_head, note, paint, say, section, step, tag, wrap

# Optional settings (defaults apply if config/apply_settings.py doesn't have them yet)
GENERIC_AUTO_ADVANCE = getattr(_cfg, "GENERIC_AUTO_ADVANCE", True)
GENERIC_MAX_STEPS = getattr(_cfg, "GENERIC_MAX_STEPS", 10)
BROWSER = getattr(_cfg, "BROWSER", "chromium")
PARALLEL_JOBS = getattr(_cfg, "PARALLEL_JOBS", 3)
PARKED_AFTER_RUN = getattr(_cfg, "PARKED_AFTER_RUN", "ask")


# --------------------------------------------------------------------------- choosing jobs
# get_candidates (scored jobs worth applying to that you haven't dealt with yet, best first, for the
# active profile) lives in db/queries.py.


def target_for(job: dict) -> tuple[str | None, str | None, str | None]:
    """(url to open, ATS name, reason it can't be filled or None).

    Uses the employer's own link (apply_url) when there is one; otherwise the job-board link,
    which only works if that link itself is a Greenhouse / Lever / Ashby page.
    """
    marker = job.get("apply_url")
    if marker in NO_LINK_MARKERS:
        site = detect_ats(job["job_url"])
        if marker == EASY_APPLY:
            why = ("LinkedIn Easy Apply: LinkedIn's own form, which isn't supported yet "
                   "(use --set-url if you find the employer's link)")
        elif site == "indeed":
            why = ("Indeed job with no employer link: Indeed's own forms aren't supported yet "
                   "(use --set-url if you find the employer's link)")
        else:
            why = "no employer application link found yet (use --set-url if you have it, or --recheck-links to search again)"
        return job["job_url"], site, why
    link = job.get("apply_url") or job["job_url"]
    ats = detect_ats(link)
    if ats == "linkedin" and not job.get("apply_url"):
        return link, ats, "employer link not looked up yet (raise LINKEDIN_CLICK_MAX, or run again)"
    if ats == "indeed" and not marker:
        return link, ats, "Indeed job: employer link not found (Indeed link-finding isn't built yet; use --set-url)"
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
        tag("DOCS", "Making this job's resume and cover letter first...")
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
            results = resolve_links(context, [j["job_url"] for j in todo], LINKEDIN_CLICK_DELAY,
                                    attempts=LINKEDIN_CLICK_ATTEMPTS)
        finally:
            context.close()
    found = closed = retry_later = 0

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
        elif outcome == "easy":    # LinkedIn's own form: final answer, no employer link exists
            set_apply_url(job["job_url"], EASY_APPLY)
            job["apply_url"] = EASY_APPLY
        elif outcome in ("unknown", "error"):   # still failing after every try: left unmarked for the next run
            retry_later += 1
    tag("APPLY", f"Found {found} employer link(s) through LinkedIn."
          + (f" {closed} posting(s) are closed and were dropped." if closed else "")
          + (f" {retry_later} posting(s) didn't work after {LINKEDIN_CLICK_ATTEMPTS} tries and will be tried again next run."
             if retry_later else ""))
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
    return clear_missing_link_markers(RECHECKABLE_MARKERS, db_path)


# ------------------------------------------------------------------------------ console output

# Color of where a filled answer came from; the same words are written to fill_report.txt.
SOURCE_COLORS = {"rule": "green", "learned": "sky", "draft": "orange", "asked": "gold",
                 "blank": "gray", "never": "red", "unknown": "red"}
RESULT_KINDS = {"applied": "ok", "skipped": "skip", "closed": "bad", "opened": "warn"}
CLOSED_TEXT = "The page text says this posting is closed. Not recording it as closed; check it in the browser."


def warn(text: str) -> None:
    tag("APPLY", text, "warn")


def show_line(text: str) -> None:
    """The Workday and generic fillers report progress as plain lines; print them in the console style."""
    body = text.strip()
    if text.startswith("\n"):
        print()
    if not body:
        return
    heading = re.match(r"-+\s*(.*?)\s*-+$", body)
    if heading:
        print(section(heading.group(1)))
    elif body.lower().startswith("reached"):
        decision("ok", body)
    elif re.search(r"closed|stopping|stopped|couldn.t|can.t find|still on|errors?\b|failed|could not|maximum", body, re.I):
        warn(body)
    else:
        print(wrap(body, color="white"))


def style_prompt(prompt: str) -> str:
    """A question for you, in color: a gold arrow and gold text. The space before the cursor is kept."""
    lead = "\n" * (len(prompt) - len(prompt.lstrip("\n")))
    lines = prompt.strip("\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        space = " " if i == len(lines) - 1 and line.endswith(" ") else ""
        out.append(INDENT + (paint("▶ ", "gold", True) if i == 0 else "  ") + paint(line.strip(), "gold") + space)
    return lead + "\n".join(out)


def ask_you(prompt: str = "") -> str:
    return input(style_prompt(prompt))


def show_result(status: str) -> None:
    decision(RESULT_KINDS.get(status, "skip"), f"{status}: recorded")


def park_job(job: dict, link: str, ats: str, blocked: Blocked, number: int, total: int, parked: list) -> None:
    """Put a job that needs you on the parked list, tell you (terminal line and beep), and remember it for this run's summary."""
    try:
        record_parked(job["job_url"], blocked.reason, blocked.detail, apply_url=link, ats=ats)
    except Exception as e:   # a database hiccup must not stop the run; the job is simply offered again next time
        note(f"(couldn't save it to the parked list: {e})")
    parked.append(dict(title=job["title"], company=job["company"], reason=blocked.reason, detail=blocked.detail, job_url=job["job_url"]))
    notify(dict(number=number, total=total, title=job["title"], company=job["company"], state="parked",
                reason=str(blocked), url=link))


def show_parked_summary(parked: list[dict]) -> None:
    """The closing block of a run: what was set aside this run and why, and how many jobs wait on the list in all."""
    if not parked:
        return
    print()
    print(section("PARKED"))
    reasons = Counter(p["reason"] for p in parked)
    tag("APPLY", f"{len(parked)} job(s) parked this run: " + ", ".join(f"{n} {r}" for r, n in reasons.most_common()), "warn")
    for p in parked:
        decision("warn", f"{p['title']} - {p['company']}: {p['reason']}" + (f" ({p['detail'][:80]})" if p["detail"] else ""))
    try:
        waiting = len(parked_jobs())
    except Exception:
        waiting = len(parked)
    note(f"{waiting} job(s) are waiting on the parked list in total.")


def offer_parked(parked: list[dict]) -> None:
    """After a normal run: do the jobs parked in this run now? PARKED_AFTER_RUN = "ask" (y/n), "auto" (no question) or "never"."""
    mode = str(PARKED_AFTER_RUN).strip().lower()
    if not parked or mode == "never":
        return
    if mode != "auto":   # "ask", and anything unrecognised
        print()
        try:
            reply = ask_you(f"Do the {len(parked)} job(s) parked in this run now? (y/n): ")
        except (KeyboardInterrupt, EOFError):
            reply = ""
        if not reply.strip().lower().startswith("y"):
            note("Okay. Run  python apply_jobs.py --parked  whenever you are ready.")
            return
    run_parked(len(parked), only={p["job_url"] for p in parked})

# ----------------------------------------------------------------------------- one job


def apply_to_job(context, job: dict, url: str, ats: str, ask=ask_you, answerer=None) -> str:
    """Fill one application and wait for you. Returns applied | skipped | opened | closed.
    Raises Blocked when the job needs you and parking is on (applying/blocked.py); run() parks it."""
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
            outcome = workday.run_application(page, url, answerer, resume_file, letter_file, ask=ask, show=show_line,
                                              show_report=capture, auto_advance=WORKDAY_AUTO_ADVANCE,
                                              max_steps=WORKDAY_MAX_STEPS)
            if outcome == "closed":
                warn(CLOSED_TEXT)
        elif ats in GENERIC_SITES:
            import applying.generic as generic
            outcome = generic.run_application(page, url, answerer, resume_file, letter_file, ask=ask, show=show_line,
                                              show_report=capture, auto_advance=GENERIC_AUTO_ADVANCE,
                                              max_steps=GENERIC_MAX_STEPS, timeout_ms=PAGE_TIMEOUT_MS)
            if outcome == "closed":
                warn(CLOSED_TEXT)
        else:
            frame = open_application(page, url, PAGE_TIMEOUT_MS)
            try:
                body = page.inner_text("body", timeout=5000)
            except Exception:
                body = ""
            closed = closed_in_text(body[:20000]) and frame is None
            if closed:
                warn(CLOSED_TEXT)
            if frame is None:
                if parking_enabled() and not closed:
                    raise Blocked(NO_FORM)
                warn("Couldn't find the application form on that page. It's open in the browser for you.")
            else:
                if closed_in_text(body[:3000]):
                    warn("The page mentions the job being closed or unavailable. Check before filling in more.")
                capture(fill_form(frame, answerer, resume_file, letter_file))
        reply = ask("\n  Review the form, fix anything, and submit it yourself in the browser.\n"
                    "  Then type  a = I submitted it,  s = skip this job for good,  Enter = not yet: ")
        reply = reply.strip().lower()
        result = "applied" if reply.startswith("a") else "skipped" if reply.startswith("s") else "opened"
    except Blocked:
        result = "parked"
        raise
    finally:
        page.close()
        saved = save_fill_report(job_folder(job), job, url, ats, pages_filled, result)
        if saved:
            note(f"Fill report saved: {saved}")
    return result


def print_report(report) -> None:
    if report.uploaded:
        say("upload", ", ".join(report.uploaded), color="mint")
    for label, value, source in report.filled:
        text = " ".join(str(value).split())
        text = text if len(text) <= 160 else text[:159] + "…"    # the full text is in fill_report.txt
        first = INDENT + paint(source.ljust(7), SOURCE_COLORS.get(source, "white"), True) + " " \
            + paint(f"{label[:30]:<30}", "gray") + " "
        print(wrap(text, first, INDENT + " " * (7 + 1 + 30 + 1), color="white") if text
              else first + paint("(left blank)", "gray"))
    if report.attention:
        print(section("NEEDS YOUR ATTENTION"))
        for label, why in report.attention:
            decision("warn", f"{label[:60]}: {why}")


# --------------------------------------------------------------------------------- CLI


def run(limit, min_score, days, include_opened=False, url=None, list_only=False, parallel=PARALLEL_JOBS) -> None:
    init_db()
    if url:   # you named this job yourself, so you are here: ask instead of parking (this is also how you sign in to an employer's Workday)
        set_parking(False)
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
                warn("The page text mentions the job being closed. Not recorded as closed; check it when the form opens.")
            ready.append((job, link, ats))
    print()
    tag("APPLY", f"{len(ready)} of {len(jobs)} job(s) can be filled.")

    if list_only or not ready or limit <= 0:
        return

    if parallel > 1 and len(ready[:limit]) > 1:
        from applying.worker import launch_all
        set_parking(False)   # the separate windows ask you instead of parking
        launch_all(ready[:limit], parallel, prepare=document_files)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        tag("APPLY", "Playwright isn't installed. Run:  pip install playwright   then   playwright install chromium")
        return

    done = 0
    batch = ready[:limit]
    parked = []   # jobs set aside this run
    with sync_playwright() as p:
        context = _open_profile(p)
        try:
            for number, (job, link, ats) in enumerate(batch, 1):
                step(None, "APPLYING", right=f"score {fmt_score(job['match_score'])}")
                print()
                job_head(job["title"], job["company"], link)
                try:
                    status = apply_to_job(context, job, link, ats)
                except KeyboardInterrupt:
                    print()
                    tag("APPLY", "Stopped.")
                    break
                except Blocked as b:
                    park_job(job, link, ats, b, number, len(batch), parked)
                    continue
                except Exception as e:
                    decision("bad", f"failed: {e}")
                    continue
                record_application(job["job_url"], status, apply_url=link, ats=ats)
                if status == "applied":
                    try:
                        tracking.log_applied(job["job_url"], ats=ats, folder=job_folder(job).name)
                    except Exception as e:   # tracking must never break applying
                        note(f"(couldn't start tracking: {e})")
                done += 1
                show_result(status)
        finally:
            context.close()
    print()
    tag("APPLY", f"Opened {done} application(s).")
    show_parked_summary(parked)

    offer_parked(parked)


def run_parked(limit: int, url: str | None = None, list_only: bool = False, only: set | None = None) -> None:
    """apply_jobs.py --parked: the jobs set aside earlier, best score first. You are here, so a blocker asks you
    instead of parking the job again."""
    init_db()
    set_parking(False)
    jobs = sorted(parked_jobs(url), key=lambda j: -j["match_score"])   # ties stay oldest first

    if only is not None:   # offer_parked: just the jobs parked in the run that just ended
        jobs = [j for j in jobs if j["job_url"] in only]

    if not jobs:
        tag("APPLY", "That job isn't on the parked list." if url else "The parked list is empty.")
        return
    
    print(section("PARKED"))
    
    for job in jobs:
        print()
        job_head(f"{fmt_score(job['match_score'])}  {job['title']}", job["company"], job["apply_url"] or job["job_url"])
        why = job["reason"] + (f" ({job['detail'][:80]})" if job["detail"] else "")
        decision("warn", f"{why}; parked {job['tries']} time(s)")
    print()
    tag("APPLY", f"{len(jobs)} job(s) on the parked list.")
    if list_only or limit <= 0:
        return

    ready = []   # the first `limit` jobs that can be opened; closed or unfillable ones don't use up the count
    for job in jobs:
        if len(ready) >= limit:
            break
        name = f"{job['title']} - {job['company']}"
        link, ats, reason = target_for(job)
        if reason:
            decision("skip", f"{name}: skipped, {reason} (it stays parked)")
            continue
        status = check_open(link) if CHECK_STILL_OPEN else "open"
        if status == "closed":
            decision("bad", f"{name}: closed, the posting is no longer open")
            record_application(job["job_url"], "closed", apply_url=link, ats=ats)
            continue
        if status == "maybe_closed":
            warn(f"{name}: the page text mentions the job being closed. Check it when the form opens.")
        ready.append((job, link, ats))
    if not ready:
        tag("APPLY", "Nothing on the parked list can be opened right now.")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        tag("APPLY", "Playwright isn't installed. Run:  pip install playwright   then   playwright install chromium")
        return

    finished = 0
    with sync_playwright() as p:
        context = _open_profile(p)
        try:
            for number, (job, link, ats) in enumerate(ready, 1):
                step(None, "APPLYING", right=f"parked {number}/{len(ready)}  score {fmt_score(job['match_score'])}")
                print()
                job_head(job["title"], job["company"], link)
                note(f"It was parked because: {job['reason']}" + (f" ({job['detail'][:80]})" if job["detail"] else ""))
                try:
                    status = apply_to_job(context, job, link, ats)
                except KeyboardInterrupt:
                    print()
                    tag("APPLY", "Stopped. The rest stay on the parked list.")
                    break
                except Exception as e:
                    decision("bad", f"failed: {e} (it stays parked)")
                    continue
                if status == "opened":   # you pressed Enter, "not yet"
                    decision("skip", "not yet: it stays on the parked list")
                    continue
                record_application(job["job_url"], status, apply_url=link, ats=ats)
                if status == "applied":
                    try:
                        tracking.log_applied(job["job_url"], ats=ats, folder=job_folder(job).name)
                    except Exception as e:   # tracking must never break applying
                        note(f"(couldn't start tracking: {e})")
                finished += 1
                show_result(status)
        finally:
            context.close()
    print()
    try:
        waiting = len(parked_jobs())
    except Exception:
        waiting = "?"
    tag("APPLY", f"{finished} parked job(s) finished. {waiting} still on the parked list.")


def show_banner(mode: str, min_score) -> None:
    """The same header main.py prints, so you can see which profile this run loaded."""
    from datetime import datetime
    banner(active_profile_name(), mode, MODEL, load_resume().get("name", "unknown"), min_score,
           datetime.now().strftime("%a %Y-%m-%d %H:%M"), score_label="apply")


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
    parser.add_argument("--parked", action="store_true", help="work through the jobs set aside because they needed you (--list shows them, --url picks one)")
    parser.add_argument("--list", action="store_true", help="show what would be filled; open nothing")
    parser.add_argument("--parallel", type=int, default=PARALLEL_JOBS, help="applications open at once, each in its own window (1 = one at a time here)")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)
    show_banner("FULL-AUTO", args.min_score)

    if args.login:
        login(args.login)
        raise SystemExit
    if args.parked:
        run_parked(args.top, args.url, args.list)
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