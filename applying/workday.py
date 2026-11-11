"""Workday application wizard: fills each page and stops at the Review page. It never submits.

Workday applications are a sequence of pages (My Information, My Experience, Application Questions,
Voluntary Disclosures, Self Identify, Review) and need an account for each employer. The first time you
apply to an employer, the tool pauses so YOU sign in or create the account in the browser window; the
login is kept in the saved browser profile, so later applications to that employer need nothing.
The tool never sees or stores a password.

Per page it fills what it can, then either clicks "Save and Continue" (WORKDAY_AUTO_ADVANCE, only when
nothing on the page needs you) or waits while you fix the page. The final "Submit" is never clicked.
"""

import re

from applying.form_filler import fill_form
from core.job_status import closed_in_text

NEXT_BUTTONS = ('[data-automation-id="pageFooterNextButton"], '
                '[data-automation-id="bottom-navigation-next-button"]')


def _visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def _body_text(page) -> str:
    try:
        return page.inner_text("body", timeout=5000)[:20000]
    except Exception:
        return ""


def _step_title(page) -> str:
    for selector in ('[data-automation-id="progressBarActiveStep"]', "h2", "h1"):
        loc = page.locator(selector).filter(visible=True)
        try:
            if loc.count():
                return " ".join(loc.first.inner_text(timeout=2000).split())[:80]
        except Exception:
            continue
    return ""


def _needs_sign_in(page) -> bool:
    return _visible(page.locator("input[type=password]")) or bool(re.search(r"/login|/signin", page.url, re.I))


def _next_button(page):
    """The page's Save-and-Continue button, or None. A button that says Submit is never returned."""
    candidates = [page.locator(NEXT_BUTTONS).filter(visible=True).first,
                  page.get_by_role("button", name=re.compile(r"^(save and continue|next|continue)$", re.I)).filter(visible=True).first]
    for button in candidates:
        try:
            if button.count() and not re.search(r"submit", button.inner_text(timeout=2000), re.I):
                return button
        except Exception:
            continue
    return None


def _at_review(page) -> bool:
    submit = page.get_by_role("button", name=re.compile(r"submit", re.I)).filter(visible=True)
    return _visible(submit) or bool(re.search(r"review", _step_title(page), re.I))


def _start_application(page, resume_file, ask) -> None:
    """From the job posting, press Apply and choose to autofill from the resume (or apply manually)."""
    apply = page.locator('[data-automation-id="adventureButton"]').filter(visible=True)
    if not _visible(apply):
        apply = page.get_by_role("link", name=re.compile(r"^apply", re.I)).or_(
            page.get_by_role("button", name=re.compile(r"^apply", re.I))).filter(visible=True)
    if _visible(apply):
        apply.first.click(timeout=5000)
        page.wait_for_timeout(2500)

    autofill = page.locator('[data-automation-id="autofillWithResume"]').or_(
        page.get_by_text(re.compile(r"autofill with resume", re.I))).filter(visible=True)
    if _visible(autofill) and resume_file and resume_file.exists():
        autofill.first.click(timeout=5000)
        page.wait_for_timeout(1500)
        try:
            page.locator("input[type=file]").first.set_input_files(str(resume_file), timeout=8000)
            page.wait_for_timeout(5000)  # Workday reads the resume
            cont = page.get_by_role("button", name=re.compile(r"^continue$", re.I)).or_(
                page.locator('[data-automation-id="pageFooterNextButton"]')).filter(visible=True)
            if _visible(cont):
                cont.first.click(timeout=5000)
        except Exception as e:
            print(f"  (could not use Autofill with Resume: {type(e).__name__}; continuing manually)")
        return
    manual = page.locator('[data-automation-id="applyManually"]').or_(
        page.get_by_text(re.compile(r"apply manually", re.I))).filter(visible=True)
    if _visible(manual):
        manual.first.click(timeout=5000)


def run_application(page, link, answerer, resume_file, letter_file, ask=input, show=print, show_report=None,
                    auto_advance=True, max_steps=12) -> str:
    """Walk the Workday wizard. Returns "review" (ready for you), "closed" or "stopped"."""
    page.goto(link, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if closed_in_text(_body_text(page)) and not _visible(page.locator('[data-automation-id="adventureButton"]')):
        show("  This Workday posting says it is closed.")
        return "closed"

    _start_application(page, resume_file, ask)
    last_title, repeats = None, 0
    for _ in range(max_steps):
        page.wait_for_timeout(2000)
        if _needs_sign_in(page):
            ask("\n  Sign in or create your account for this employer in the browser window "
                "(first time only), then press Enter here: ")
            page.wait_for_timeout(2000)
            if _needs_sign_in(page):
                show("  Still on the sign-in page; stopping. Run again after you are signed in.")
                return "stopped"
            continue

        title = _step_title(page)
        repeats = repeats + 1 if title == last_title else 0
        last_title = title
        show(f"\n  --- Workday page: {title or '(untitled)'} ---")

        report = fill_form(page, answerer, resume_file, letter_file)
        if show_report:
            show_report(report)

        if _at_review(page):
            show("  Reached the Review page. Check everything, then submit it yourself.")
            return "review"

        button = _next_button(page)
        if button is None:
            reply = ask("  I can't find the Continue button here. Move to the next page yourself, then press Enter "
                        "(q = stop): ")
            if reply.strip().lower().startswith("q"):
                return "stopped"
            continue

        stuck = repeats >= 1
        if report.attention or not auto_advance or stuck:
            why = ("the page didn't change last time" if stuck else
                   "some fields need you" if report.attention else "auto-advance is off")
            reply = ask(f"  Pausing ({why}). Fix this page in the browser, then press Enter to continue "
                        "(q = stop here): ")
            if reply.strip().lower().startswith("q"):
                return "stopped"
            if _at_review(page):
                continue
            button = _next_button(page)
            if button is None:
                continue
        button.click(timeout=5000)
        page.wait_for_timeout(2500)
        if _visible(page.locator('[data-automation-id="errorBanner"]')) or re.search(
                r"errors? found", _body_text(page), re.I):
            reply = ask("  Workday reports errors on that page. Fix them in the browser, then press Enter "
                        "(q = stop here): ")
            if reply.strip().lower().startswith("q"):
                return "stopped"
    show("  Stopped after the maximum number of pages (WORKDAY_MAX_STEPS).")
    return "stopped"
