"""Diagnose why the employer's application link isn't found for one LinkedIn job.

    python check_link.py 4487548729        (the number at the end of the LinkedIn job URL)

Fetches the job two ways (LinkedIn's guest API page, which the scraper uses, and the public job page),
shows what the link parser finds in each, and prints the text around anything that looks like an apply
link. It also saves page_guest.html and page_public.html next to this script.
"""

import re
import sys

import requests

import scraper

if len(sys.argv) != 2:
    sys.exit("Usage: python check_link.py <linkedin job id>")
job_id = sys.argv[1]

session = requests.Session()
session.headers.update(scraper.REQUEST_HEADERS)
pages = {
    "guest": scraper.LINKEDIN_JOB_API.format(job_id=job_id),
    "public": f"https://www.linkedin.com/jobs/view/{job_id}/",
}
for name, url in pages.items():
    try:
        r = session.get(url, timeout=20)
    except requests.RequestException as e:
        print(f"\n== {name}: request failed: {e}")
        continue
    html = r.text
    print(f"\n== {name} page: HTTP {r.status_code}, {len(html)} characters")
    print("   parser result:", scraper._parse_linkedin_apply_link(html))
    print("   says Easy Apply:", bool(re.search(r"easy apply", html, re.I)))
    for key in ("applyUrl", "externalApply", "apply-button", "offsite"):
        hits = list(re.finditer(key, html))
        print(f"   '{key}' appears {len(hits)} time(s)")
        for m in hits[:2]:
            print(f"      ...{html[max(0, m.start() - 80): m.end() + 260]!r}")
    with open(f"page_{name}.html", "w", encoding="utf-8") as f:
        f.write(html)