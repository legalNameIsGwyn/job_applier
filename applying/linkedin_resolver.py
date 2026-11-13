"""Opt-in: find a LinkedIn job's employer application link by clicking Apply in YOUR logged-in browser.

Turn it on with LINKEDIN_CLICK_APPLY = True in config/apply_settings.py, then log in once with
`python apply_jobs.py --login`. For each job the tool opens the LinkedIn posting in the saved browser
profile, clicks Apply, and records the employer page that opens. It does not submit anything.

RISK: LinkedIn forbids automation. This is deliberately low volume (LINKEDIN_CLICK_MAX jobs per run,
random pauses, stops at the first login wall or checkpoint) but it is still automation on your real
account. Leave it off if you can't afford a restriction.
"""

import random
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit
from core.job_status import closed_in_text

# LinkedIn's own page furniture (messaging dock, top navigation): never click anything in these.
CHROME = "#msg-overlay, [class*='msg-overlay'], #global-nav, .global-nav, [role=navigation]"
NOT_A_JOB_PAGE = re.compile(r"/messaging|/feed|/mynetwork|/notifications|/mwlite", re.I)
LOGIN_WALL = re.compile(r"authwall|/login|/checkpoint|/uas/|/signup", re.I)


def external_target(url: str | None) -> str | None:
    """The employer URL: the page itself if it's off LinkedIn, or the ?url= inside a LinkedIn redirect."""
    if not url or url.startswith("about:"):
        return None
    parts = urlsplit(url)
    if parts.netloc.lower().endswith("linkedin.com"):
        inner = parse_qs(parts.query).get("url")   # parse_qs has already decoded it once
        if not inner:
            return None
        target = inner[0]
        if re.match(r"https?%3a", target, re.I):  # encoded twice
            target = unquote(target)
        return external_target(target)
    return url if parts.scheme in ("http", "https", "file") else None


def _settle(popup) -> str | None:
    """Wait for the page Apply opened to finish redirecting, and return its employer URL."""
    popup.wait_for_load_state("domcontentloaded", timeout=15000)
    popup.wait_for_timeout(1500)
    url = external_target(popup.url)
    if url:
        return url
    # LinkedIn's "you are leaving LinkedIn" page: press its Continue button
    button = popup.get_by_role("button", name=re.compile(r"continue|leave|proceed", re.I)).first
    link = popup.get_by_role("link", name=re.compile(r"continue|leave|proceed", re.I)).first
    for control in (button, link):
        try:
            control.click(timeout=3000)
            popup.wait_for_load_state("domcontentloaded", timeout=15000)
            popup.wait_for_timeout(1500)
            return external_target(popup.url)
        except Exception:
            continue
    return None


def _in_chrome(el) -> bool:
    """True if the element is part of LinkedIn's messaging dock or top navigation."""
    try:
        return bool(el.evaluate(f"e => !!e.closest({CHROME!r})"))
    except Exception:
        return False


LISTING = "li, aside, [class*='job-card'], [class*='jobs-search-results']"


def _in_listing(el) -> bool:
    """True if the element is in a list of OTHER jobs (search results, similar jobs), not the job itself."""
    try:
        return bool(el.evaluate(f"e => !!e.closest({LISTING!r})"))
    except Exception:
        return False


def _describe(el) -> str:
    try:
        info = el.evaluate("e => ({tag: e.tagName.toLowerCase(), href: (e.closest('a') || {}).href || '', "
                           "text: (e.innerText || '').trim().slice(0, 40)})")
        return f"<{info['tag']}> {info['text']!r}" + (f" -> {info['href'][:110]}" if info["href"] else "")
    except Exception:
        return "(element)"


def _controls(page) -> list[tuple[str, object]]:
    """Every visible button or link on the page as (label, element); the label is its aria-label or text."""
    found = []
    for el in page.locator("button, a, [role=button], [role=link]").all()[:200]:
        try:
            if not el.is_visible() or _in_chrome(el):
                continue
            label = " ".join(((el.get_attribute("aria-label") or "") + " " + (el.inner_text() or "")).split())
        except Exception:
            continue
        if label:
            found.append((label, el))
    return found


def _describe_apply_controls(controls) -> str:
    return "; ".join(repr(label[:60]) for label, _ in controls if re.search(r"apply", label, re.I)) or "none found"


def _employer_link_from_page(page) -> str | None:
    """The employer URL held in the Apply button's own link (LinkedIn's /safety/go/?url=... redirect)."""
    for el in page.locator('a[href*="/safety/go/"], a[href*="externalApply"]').all()[:20]:
        try:
            if not el.is_visible() or _in_chrome(el):
                continue
            label = " ".join(((el.get_attribute("aria-label") or "") + " " + (el.inner_text() or "")).split())
            if not re.match(r"\s*apply\b", label, re.I):
                continue
            url = external_target(el.evaluate("e => e.href"))
            if url:
                return url
        except Exception:
            continue
    return None


def find_apply_control(page) -> tuple[str, object, str]:
    """What this job page offers, as (kind, element, info):
    ("direct", None, employer url)  the Apply button's link already holds the employer's address
    ("easy", None, label)           the job's own button is Easy Apply (no employer link exists)
    ("apply", element, description) an Apply control we would have to click
    ("none", None, note)            nothing found
    """
    direct = _employer_link_from_page(page)
    if direct:
        return "direct", None, direct

    controls = _controls(page)
    # The job's own button starts with "Easy Apply". Cards for OTHER jobs mention it later in their text.
    easy = next((label for label, el in controls
                 if re.match(r"\s*easy apply\b", label, re.I) and not _in_listing(el)), None)
    if easy is None:
        texts = page.get_by_text(re.compile(r"^\s*Easy Apply\s*$", re.I)).filter(visible=True).all()[:10]
        easy = next(("Easy Apply" for t in texts if not _in_chrome(t) and not _in_listing(t)), None)
    if easy:
        return "easy", None, easy[:60]
    # "Apply", "Apply on company website", "Apply now"... but never "Easy Apply"
    apply = next((el for label, el in controls
                  if re.match(r"\s*apply\b", label, re.I) and not re.search(r"messag|inmail", label, re.I)), None)
    if apply is None:  # LinkedIn's newer pages use a plain <span>/<div> with no button or link tag
        texts = page.get_by_text(re.compile(r"^\s*Apply( on company website| now)?\s*$", re.I)).filter(visible=True)
        apply = next((t for t in texts.all()[:10] if not _in_chrome(t)), None)
    if apply is None:
        return "none", None, f"Buttons/links mentioning apply: {_describe_apply_controls(controls)}"
    return "apply", apply, _describe(apply)

def _page_says_closed(page) -> bool:
    """True if the top of the page (above the description) says the job no longer takes applications.
    Only the part above 'About the job' is read, so a posting that says 'we are not accepting
    applications from agencies' doesn't count as closed."""
    try:
        text = page.inner_text("body", timeout=5000)
    except Exception:
        return False
    cut = text.find("About the job")
    return closed_in_text(text[:cut] if cut > 0 else text[:2500])

def resolve_apply_link(context, job_url: str) -> tuple[str, str | None]:
    """Returns (outcome, url). outcome: link | easy | closed | login | unknown."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = context.new_page()
    try:
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        if NOT_A_JOB_PAGE.search(page.url):
            print(f"[LINKEDIN] LinkedIn sent us to {page.url} instead of the job. Not clicking anything.")
            return "unknown", None
        if LOGIN_WALL.search(page.url) or page.locator(".contextual-sign-in-modal").count() > 0:
            return "login", None
        if _page_says_closed(page):
            print("[LINKEDIN] This posting is closed (no longer taking applications).")
            return "closed", None
        
        kind, apply, info = find_apply_control(page)

        if kind == "direct":
            print(f"[LINKEDIN] Read the employer link from the Apply button (nothing clicked): {info}")
            return "link", info
        if kind == "easy":
            print(f"[LINKEDIN] This job's own button says Easy Apply ({info!r}), so there is no employer link.")
            return "easy", None
        if kind == "none":
            print(f"[LINKEDIN] No Apply button found. {info}")
            return "unknown", None
        print(f"[LINKEDIN] Clicking {info}")
        
        try:
            with context.expect_page(timeout=8000) as opened:
                apply.click()
            popup = opened.value
            try:
                print(f"[LINKEDIN] A new tab opened: {popup.url[:120]}")
                url = _settle(popup)
                if not url:
                    print(f"[LINKEDIN] Apply opened a page but no employer URL was found there: {popup.url}")
                return ("link", url) if url else ("unknown", None)
            finally:
                popup.close()
        except PlaywrightTimeout:  # no new tab: it may have gone to the employer in this tab
            url = external_target(page.url) if page.url != job_url else None
            if not url:
                print(f"[LINKEDIN] Clicked Apply but no new page opened and this one didn't change: {page.url}")
            return ("link", url) if url else ("unknown", None)
    finally:
        page.close()


def resolve_links(context, job_urls: list[str], delay=(8, 20), sleep=time.sleep) -> dict[str, tuple[str, str | None]]:
    """{job_url: (outcome, url)} for each job. Stops at the first login wall."""
    results = {}
    for n, job_url in enumerate(job_urls, start=1):
        try:
            outcome, url = resolve_apply_link(context, job_url)
        except Exception as e:
            print(f"[LINKEDIN] {job_url}: {type(e).__name__}: {e}")
            continue
        results[job_url] = (outcome, url)
        if outcome == "login":
            print("[LINKEDIN] Not logged in (or LinkedIn wants verification). "
                  "Run  python apply_jobs.py --login  and sign in, then try again.")
            break
        print(f"[LINKEDIN] {n}/{len(job_urls)} {outcome}" + (f": {url}" if url else ""))
        if n < len(job_urls):
            sleep(random.uniform(*delay))
    return results