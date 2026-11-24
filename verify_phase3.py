"""Checks Phase 3 (the saved fill report) without opening a browser or touching your database.

    python verify_phase3.py

Every line should say PASS. Delete this file when you no longer need it.
"""

import contextlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

import apply_jobs as aj
from applying.fill_report import REPORT_NAME

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not ok else ""))


def report(filled, attention=()):
    return SimpleNamespace(uploaded=["Resume.docx"], filled=list(filled), attention=list(attention))


JOB = {"title": "Junior Dev", "company": "Acme", "job_url": "https://www.linkedin.com/jobs/view/1/"}
tmp = Path(tempfile.mkdtemp())
folder = tmp / "acme_junior-dev_ab12"            # does not exist yet, on purpose

aj.load_resume = lambda: {"name": "Test Person", "contact": {}}
aj.document_files = lambda job: (folder / "r.docx", folder / "c.docx")
aj.job_folder = lambda job: folder
aj.Answerer = lambda *a, **k: object()

page = SimpleNamespace(close=lambda: None, inner_text=lambda *a, **k: "")
context = SimpleNamespace(new_page=lambda: page)


def run_job(ats: str, reply: str, fills=(), boom: bool = False) -> str:
    """Run apply_to_job with a fake form and a fake answer to the final question."""
    def fake_fill(frame, answerer, resume_file, letter_file):
        if boom:
            raise RuntimeError("form exploded")
        return fills[0]

    def fake_workday(page, url, answerer, resume_file, letter_file, ask=None, show=None, show_report=None, **kw):
        for r in fills:
            show_report(r)
        return "review"

    aj.open_application = lambda page, url, timeout: object()
    aj.fill_form = fake_fill
    import applying.workday as workday
    workday.run_application = fake_workday
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            result = aj.apply_to_job(context, JOB, "https://boards.greenhouse.io/acme/jobs/1", ats,
                                     ask=lambda prompt="": reply)
    except RuntimeError:
        result = "raised"
    run_job.output = out.getvalue()
    return result


path = folder / REPORT_NAME

# 1. a normal Greenhouse-style job, left open
first = report([("First name", "Test", "rule"), ("Gender", "Female", "rule")], [("Why us?", "drafted by the model: read it")])
result = run_job("greenhouse", "", [first])
text = path.read_text(encoding="utf-8") if path.exists() else ""
check("report file is created in the job folder (folder made if missing)", path.exists())
check("it lists the fields and their values", "First name: Test" in text and "Gender: Female" in text, text[:200])
check("it lists the fields that need you", "NEEDS YOUR ATTENTION" in text and "Why us?" in text)
check("result 'opened' is recorded", "left open, not submitted yet" in text and result == "opened")
check("terminal says where it was saved", "Fill report saved" in run_job.output)

# 2. same job again: appended, not overwritten
result = run_job("greenhouse", "a", [first])
text = path.read_text(encoding="utf-8")
check("a second run is appended", text.count("=== ") == 2, f"{text.count('=== ')} sections")
check("answering 'a' returns applied and records it", result == "applied" and "you said you submitted it" in text)

# 3. Workday: two wizard pages become Page 1 and Page 2
second = report([("Phone", "555-555-5555", "rule")])
result = run_job("workday", "s", [first, second])
text = path.read_text(encoding="utf-8")
last = text.split("=== ")[-1]
check("Workday: two pages are saved as Page 1 and Page 2", "Page 1" in last and "Page 2" in last and "Phone: 555-555-5555" in last)
check("answering 's' returns skipped", result == "skipped")

# 4. a crash still saves what was done
result = run_job("greenhouse", "", [first], boom=True)
text = path.read_text(encoding="utf-8")
check("a crash still writes a section, marked as an error",
      result == "raised" and text.split("=== ")[-1].count("stopped by an error") == 1)

# 5. the parallel worker replaces aj.print_report; the report must still reach it
seen = []
original = aj.print_report
aj.print_report = lambda r: seen.append(r)
run_job("greenhouse", "", [first])
aj.print_report = original
check("the parallel worker's print_report replacement still gets every page", len(seen) == 1)

print()
print("ALL PASS" if all(results) else f"{results.count(False)} CHECK(S) FAILED")
raise SystemExit(0 if all(results) else 1)
