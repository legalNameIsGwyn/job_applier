"""Checks the three Phase 1 fixes without opening a browser or touching your database.

    python verify_phase1.py

Every line should say PASS. Delete this file when you no longer need it.
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not ok else ""))


# ---------------------------------------------------------------- 1A: closed from page text
from core.job_status import check_open


def fake_get(status: int, text: str = ""):
    return lambda url, **kw: SimpleNamespace(status_code=status, text=text, json=lambda: {})


CLOSED_PAGE = "<html><body>Sorry, we are no longer accepting applications for this role.</body></html>"
OPEN_PAGE = "<html><body>Apply now. We are hiring a junior developer.</body></html>"

check("employer site, text says closed -> maybe_closed (not recorded)",
      check_open("https://careers.example.com/jobs/123", fake_get(200, CLOSED_PAGE)) == "maybe_closed")
check("employer site, normal page -> open",
      check_open("https://careers.example.com/jobs/123", fake_get(200, OPEN_PAGE)) == "open")
check("employer site, HTTP 404 -> closed",
      check_open("https://careers.example.com/jobs/123", fake_get(404)) == "closed")
check("employer site, HTTP 500 -> unknown",
      check_open("https://careers.example.com/jobs/123", fake_get(500)) == "unknown")
check("indeed page, text says closed -> closed",
      check_open("https://www.indeed.com/viewjob?jk=abc", fake_get(200, CLOSED_PAGE)) == "closed")
check("linkedin page, text says closed -> closed",
      check_open("https://www.linkedin.com/jobs/view/4487548729/", fake_get(200, CLOSED_PAGE)) == "closed")

# ---------------------------------------------------------------- 1B: learned answers
from applying.answering import Answerer

with tempfile.TemporaryDirectory() as tmp:
    learned = Path(tmp) / "learned_answers.json"
    resume = {"name": "Test Person", "contact": {}}
    job = {"title": "x", "company": "y"}
    a = Answerer(resume, job, ask=lambda p="": "", learned_file=learned, draft_free_text=False)
    b = Answerer(resume, job, ask=lambda p="": "", learned_file=learned, draft_free_text=False)
    a._remember("question from window a", "answer a")   # both objects loaded the (empty) file before either saved
    b._remember("question from window b", "answer b")
    saved = json.loads(learned.read_text(encoding="utf-8"))
    check("two windows saving answers keep both answers",
          saved == {"question from window a": "answer a", "question from window b": "answer b"}, str(saved))
    check("no temp files left behind", [p.name for p in Path(tmp).iterdir()] == ["learned_answers.json"],
          str([p.name for p in Path(tmp).iterdir()]))

# ---------------------------------------------------------------- 1A + 1C: run()
import apply_jobs as aj

JOB = {"title": "Junior Dev", "company": "Acme", "job_url": "https://www.linkedin.com/jobs/view/1/",
       "match_score": 8.0, "apply_url": "https://careers.example.com/jobs/1", "location": "Norfolk, VA",
       "description": "x", "site": "linkedin"}

recorded, browsers = [], []
aj.init_db = lambda: None
aj.get_candidates = lambda *a, **k: [dict(JOB)]
aj.AUTO_FIND_LINKS = False
aj.LINKEDIN_CLICK_APPLY = False
aj.CHECK_STILL_OPEN = True
aj.target_for = lambda job: (job["apply_url"], "custom", None)
aj.record_application = lambda *a, **k: recorded.append(a)
aj._open_profile = lambda *a, **k: browsers.append(1) or (_ for _ in ()).throw(AssertionError("browser opened"))

import contextlib
import io


def run_quiet(**kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        aj.run(kw.get("limit", 0), 5, 14, parallel=1)
    return out.getvalue()


aj.check_open = lambda link: "maybe_closed"
text = run_quiet()
check("maybe_closed: nothing recorded in the database", recorded == [], str(recorded))
check("maybe_closed: a warning is printed", "WARNING: the page text mentions" in text)

recorded.clear()
aj.check_open = lambda link: "closed"
run_quiet()
check("closed (API / 404 / LinkedIn / Indeed): recorded as closed",
      len(recorded) == 1 and recorded[0][1] == "closed", str(recorded))

recorded.clear()
aj.check_open = lambda link: "open"
run_quiet()
check("--top 0 does not open a browser", browsers == [], f"{len(browsers)} browser(s) opened")

print()
print("ALL PASS" if all(results) else f"{results.count(False)} CHECK(S) FAILED")
raise SystemExit(0 if all(results) else 1)
