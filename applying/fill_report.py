"""Saves what the tool filled in for each job, so you can check it later.

One text file per job, `fill_report.txt` in the job's application folder (next to the resume and cover letter).
Each run adds a dated section at the bottom; nothing is overwritten. It holds the exact values typed into the
form (name, phone, self-identification answers...), so it stays in the private, git-ignored applications folder.
"""

from datetime import datetime
from pathlib import Path

REPORT_NAME = "fill_report.txt"

RESULTS = {
    "applied": "you said you submitted it",
    "skipped": "you skipped this job",
    "opened": "left open, not submitted yet",
    "closed": "posting closed",
    "parked": "parked: it needed you",
    "error": "stopped by an error",
}


def render_section(job: dict, url: str, ats: str, pages: list, result: str, when: datetime | None = None) -> str:
    """The text of one run: header, then each filled page's fields and the fields that needed you."""
    when = when or datetime.now()
    lines = [f"=== {when:%Y-%m-%d %H:%M}   {job.get('title', '')} - {job.get('company', '')}   [{ats}] ===",
             f"Link:   {url}",
             f"Result: {RESULTS.get(result, result)}"]
    if not pages:
        lines.append("Nothing was filled (no form was found or the run stopped before one).")
    for number, report in enumerate(pages, start=1):
        lines.append(f"\nPage {number}")
        if report.uploaded:
            lines.append(f"  Uploaded: {', '.join(report.uploaded)}")
        for label, value, source in report.filled:
            lines.append(f"  [{source:>7}] {label[:80]}: {value}")
        if report.attention:
            lines.append("  NEEDS YOUR ATTENTION:")
            for label, why in report.attention:
                lines.append(f"    - {label[:80]}: {why}")
    return "\n".join(lines) + "\n"


def save_fill_report(folder: Path, job: dict, url: str, ats: str, pages: list, result: str) -> Path | None:
    """Append this run to the job's fill_report.txt. Returns the file, or None if it couldn't be written."""
    path = Path(folder) / REPORT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        section = render_section(job, url, ats, pages, result)
        existing = path.read_text(encoding="utf-8").rstrip("\n") if path.exists() else ""
        path.write_text((existing + "\n\n" if existing else "") + section, encoding="utf-8")
        return path
    except OSError as e:
        print(f"  (could not save the fill report: {e})")
        return None
