"""A CSV of the jobs you can click through and apply to by hand.

It sits next to the applications folder (profiles/<name>/applications.csv), one row per job.
Rows are only ever appended, and a job whose URL is already in the file is never added twice.
Turn it off with CSV_LOG = False in config/settings.py.
"""

import csv
from datetime import date
from pathlib import Path

import config.settings as _settings

COLUMNS = ["date", "title", "company", "location", "score", "compat_pct", "mode", "job_url", "folder", "status"]


def enabled() -> bool:
    return bool(getattr(_settings, "CSV_LOG", True))


def csv_path() -> Path:
    """CSV_LOG_PATH in settings if set, otherwise applications.csv beside the applications folder."""
    custom = getattr(_settings, "CSV_LOG_PATH", None)
    return Path(custom) if custom else Path(_settings.APPLICATIONS_DIR).parent / "applications.csv"


def known_urls(path: Path | None = None) -> set[str]:
    """Every job_url already in the CSV (empty if the file is missing or CSV_LOG is off)."""
    path = path or csv_path()
    if not enabled() or not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row.get("job_url", "") for row in csv.DictReader(f)} - {""}


def _compat(job: dict) -> str:
    pct = job.get("compat_detail_pct")
    if pct is None:
        pct = job.get("compat_pct")
    return "" if pct is None else f"{pct:g}"


def log_job(job: dict, folder_name: str, mode: str = "", path: Path | None = None) -> bool:
    """Append one row. Returns True if a row was added, False if skipped (already there, or CSV_LOG is off)."""
    if not enabled():
        return False
    path = path or csv_path()
    if job["job_url"] in known_urls(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    row = {
        "date": date.today().isoformat(), "title": job["title"], "company": job["company"],
        "location": job.get("location", ""), "score": f"{job['match_score']:g}" if job.get("match_score") is not None else "",
        "compat_pct": _compat(job), "mode": mode, "job_url": job["job_url"], "folder": folder_name, "status": "",
    }
    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except PermissionError:
        print(f"[CSV] Could not write {path.name}. Is it open in Excel? Close it; the row is added on the next run.")
        return False
    return True