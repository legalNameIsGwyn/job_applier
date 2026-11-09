"""Show what the tool sees on one LinkedIn job page, WITHOUT clicking anything.

    python check_linkedin_page.py https://www.linkedin.com/jobs/view/4487548729/

Opens the job in your saved, logged-in browser, then prints the page address, what the tool decides
(Easy Apply / Apply button / nothing), and every visible button and link with flags for the messaging
dock and side lists. It saves linkedin_check.png (a screenshot) and linkedin_check.html next to this
script. The screenshot can show whatever is on your screen, including the Messaging dock, so look at it
before sharing it.
"""

import re
import sys

from playwright.sync_api import sync_playwright

try:
    import linkedin_resolver as lr
except ImportError:  # the file was moved into archive
    import archive.linkedin_resolver as lr
import config.apply_settings as _cfg
from config.apply_settings import BROWSER_PROFILE_DIR

if len(sys.argv) < 2:
    sys.exit("Usage: python check_linkedin_page.py <linkedin job url> [--headless]")
url = sys.argv[1] if "://" in sys.argv[1] else f"https://www.linkedin.com/jobs/view/{sys.argv[1]}/"
headless = "--headless" in sys.argv

with sync_playwright() as p:
    context = getattr(p, getattr(_cfg, "BROWSER", "firefox")).launch_persistent_context(str(BROWSER_PROFILE_DIR), headless=headless, no_viewport=True)
    try:
        print(f"Tabs already open in this profile: {[pg.url for pg in context.pages]}")
        page = context.new_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        print(f"\nPage address now : {page.url}")
        print(f"Page title       : {page.title()}")
        print(f"Looks like a job page: {not lr.NOT_A_JOB_PAGE.search(page.url)}")
        print(f"Login wall / sign-in popup: {bool(lr.LOGIN_WALL.search(page.url) or page.locator('.contextual-sign-in-modal').count())}")
        kind, el, info = lr.find_apply_control(page)
        print(f"\nDecision: {kind}  ({info})")
        if kind == "direct":
            print("  -> the employer link is read straight from the Apply button; nothing needs clicking")
        print("\nVisible buttons and links:")
        for el2 in page.locator("button, a, [role=button], [role=link]").all()[:150]:
            try:
                if not el2.is_visible():
                    continue
                label = " ".join(((el2.get_attribute("aria-label") or "") + " | " + (el2.inner_text() or "")).split())
                if not label.strip(" |"):
                    continue
                flags = ("[dock/nav] " if lr._in_chrome(el2) else "") + ("[list] " if lr._in_listing(el2) else "")
                href = el2.evaluate("e => (e.closest('a') || {}).href || ''")
                print(f"  {flags}{label[:80]}" + (f"  -> {href[:80]}" if href else ""))
            except Exception:
                continue
        page.screenshot(path="linkedin_check.png")
        with open("linkedin_check.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("\nSaved linkedin_check.png and linkedin_check.html")
        if not headless:
            input("Look at the window, then press Enter to close it: ")
    finally:
        context.close()