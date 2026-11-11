"""Generic application filler for sites that have no dedicated filler (iCIMS, Taleo, SmartRecruiters,
Workable, SuccessFactors, an employer's own career page, and so on). It NEVER clicks Submit.

It uses the same form scanner as the Greenhouse / Lever / Ashby filler, and adds what multi-page
employer sites need:

  - opens the posting and presses Apply if the form isn't on the page yet
  - if the site asks you to sign in or create an account, pauses so YOU do it in the browser window
    (the login is kept in the saved browser profile; the code never sees a password)
  - fills every field it has an answer for, then either clicks Next / Continue (GENERIC_AUTO_ADVANCE,
    only when nothing on the page needs you) or waits while you fix the page
  - stops when it reaches a page whose only forward button is Submit / Finish / Review

Generic means "best effort": custom sites vary a lot. Anything it can't do is left for you, and the
form stays open in the browser.
"""

import re

from core.job_status import closed_in_text
from applying.form_filler import FORM_FIELDS, SCAN_JS, fill_form

# Buttons that move forward without sending anything.
NEXT_RE = re.compile(
    r"^\s*(save\s*(and|&)\s*(continue|next)|next(\s+(step|page))?|continue(\s+(application|to\s+\w+))?|proceed|"
    r"go to next step|start application)\s*[>»→]?\s*$", re.IGNORECASE)
# Buttons that send or finalize. These are never clicked.
FINAL_RE = re.compile(r"submit|send application|finish|complete application|confirm|place|agree|accept|apply now|review",
                      re.IGNORECASE)
BUTTONS = "button, input[type=submit], input[type=button], a[role=button], [role=button]"


def _visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def find_form_frame(page):
    """The frame with the most VISIBLE form fields (some sites keep every step in the page, hidden)."""
    best, best_n = None, 0
    for frame in page.frames:
        try:
            n = frame.locator(FORM_FIELDS).filter(visible=True).count()
        except Exception:
            continue
        if n > best_n:
            best, best_n = frame, n
    return best if best_n >= 3 else None


def open_application(page, url, timeout_ms=30000):
    """Go to the page; if it is a job description, press Apply (up to twice) to reach a form."""
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    for attempt in range(3):
        for _ in range(10):  # up to ~5 s for a script-built form to appear
            frame = find_form_frame(page)
            if frame or needs_sign_in(page):
                return frame
            page.wait_for_timeout(500)
        button = page.locator('a:has-text("Apply"), button:has-text("Apply"), [role=button]:has-text("Apply")') \
            .filter(visible=True).first
        try:
            button.click(timeout=3000)
        except Exception:
            break
        page.wait_for_timeout(1500)
    return None


def _body_text(page) -> str:
    try:
        return page.inner_text("body", timeout=5000)[:20000]
    except Exception:
        return ""


def needs_sign_in(page) -> bool:
    """A password box is showing (sign in or create account)."""
    try:
        return any(_visible(f.locator("input[type=password]")) for f in page.frames)
    except Exception:
        return False


def _button_text(button) -> str:
    try:
        text = button.inner_text(timeout=1000)
        return " ".join((text or button.get_attribute("value") or "").split())
    except Exception:
        return ""


def forward_buttons(page) -> tuple[object | None, bool]:
    """(the Next / Continue button or None, whether a final Submit-like button is showing)."""
    next_button, final = None, False
    for frame in page.frames:
        try:
            buttons = frame.locator(BUTTONS).filter(visible=True)
            count = min(buttons.count(), 40)
        except Exception:
            continue
        for i in range(count):
            button = buttons.nth(i)
            text = _button_text(button)
            if not text:
                continue
            if NEXT_RE.match(text) and next_button is None:
                next_button = button
            elif FINAL_RE.search(text) and not NEXT_RE.match(text):
                final = True
    return next_button, final


def _signature(page, frame) -> str:
    """Identifies the current page, to notice when clicking Next didn't change anything."""
    try:
        labels = [f["label"] for f in frame.evaluate(SCAN_JS)]
    except Exception:
        labels = []
    return page.url + "|" + "|".join(labels)


def run_application(page, link, answerer, resume_file, letter_file, ask=input, show=print, show_report=None,
                    auto_advance=True, max_steps=10, timeout_ms=30000) -> str:
    """Fill the application. Returns "review" (ready for you), "closed", "noform" or "stopped"."""
    frame = open_application(page, link, timeout_ms)
    body = _body_text(page)
    if frame is None and not needs_sign_in(page) and closed_in_text(body):
        show("  This posting says it is closed.")
        return "closed"

    last_signature, stuck = None, 0
    for step in range(1, max_steps + 1):
        page.wait_for_timeout(1500)

        if needs_sign_in(page):
            reply = ask("\n  This site wants you to sign in or create an account. Do that in the browser window "
                        "(first time only), then press Enter here (q = stop): ")
            if reply.strip().lower().startswith("q"):
                return "stopped"
            page.wait_for_timeout(2500)
            if needs_sign_in(page):
                show("  Still on the sign-in page; stopping. Run again after you are signed in.")
                return "stopped"
            frame = find_form_frame(page)

        frame = find_form_frame(page) or frame
        if frame is None:
            reply = ask("  I can't find a form on this page. Get to the application form in the browser, "
                        "then press Enter (q = stop): ")
            if reply.strip().lower().startswith("q"):
                return "noform"
            frame = find_form_frame(page)
            if frame is None:
                return "noform"

        signature = _signature(page, frame)
        stuck = stuck + 1 if signature == last_signature else 0
        last_signature = signature

        show(f"\n  --- Page {step} of the application ---")
        report = fill_form(frame, answerer, resume_file, letter_file)
        if show_report:
            show_report(report)

        next_button, final = forward_buttons(page)
        if next_button is None:
            if final:
                show("  Reached the last page (only Submit / Review is left). Check everything, then send it yourself.")
            else:
                show("  No Next button found. The rest is for you.")
            return "review"

        if report.attention or not auto_advance or stuck:
            why = ("the page didn't change last time" if stuck else
                   "some fields need you" if report.attention else "auto-advance is off")
            reply = ask(f"  Pausing ({why}). Fix this page in the browser, then press Enter to go on "
                        "(q = stop here, n = I moved on myself): ")
            answer = reply.strip().lower()
            if answer.startswith("q"):
                return "stopped"
            if answer.startswith("n"):
                continue
            next_button, final = forward_buttons(page)
            if next_button is None:
                return "review"
        try:
            next_button.click(timeout=5000)
        except Exception as e:
            show(f"  Couldn't press Next ({type(e).__name__}). Go on yourself.")
            return "stopped"
        page.wait_for_timeout(2500)
    show("  Stopped after the maximum number of pages (GENERIC_MAX_STEPS).")
    return "stopped"
