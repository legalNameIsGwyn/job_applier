"""A CSV of the jobs you can click through and apply to by hand.

It sits next to the applications folder (profiles/<name>/applications.csv), one row per job.
Rows are only ever appended, and a job whose URL is already in the file is never added twice.
Turn it off with CSV_LOG = False in config/settings.py.
"""

import csv
from datetime import date
from pathlib import Path

import config.settings as _settings
from core.console import tag

COLUMNS = ["job_url", "score", "compat_pct", "title",  "folder", "status", "company", "location", "mode", "date", "last_checked"]


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
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return {row.get("job_url", "") for row in csv.DictReader(f)} - {""}
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        tag("CSV", f"Could not read {path.name} ({e}); treating it as empty.")
        return set()


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
        tag("CSV", f"Could not write {path.name}. Is it open in Excel? Close it; the row is added on the next run.")
        return False
    except OSError as e:
        tag("CSV", f"Could not write {path.name}: {e}")
        return False
    return True

def handled_urls(path: Path | None = None) -> set[str]:
    """job_urls whose status cell is not blank: you (or a past run) already dealt with them."""
    path = path or csv_path()
    if not enabled() or not path.exists():
        return set()
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return {row["job_url"] for row in csv.DictReader(f)
                    if (row.get("status") or "").strip() and row.get("job_url")}
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        tag("CSV", f"Could not read {path.name} ({e}); treating it as empty.")
        return set()

def sync_statuses(labels: dict[str, str], path: Path | None = None, dry_run: bool = False) -> list[tuple[str, str]]:
    """Fill BLANK status cells. labels maps job_url -> text. Never overwrites a cell you filled.

    Returns the (job_url, text) pairs filled (or that would be, with dry_run).
    """
    path = path or csv_path()
    if not enabled() or not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "status" not in fields:
        return []
    changed = []
    for row in rows:
        url = row.get("job_url")
        if url in labels and not (row.get("status") or "").strip():
            row["status"] = labels[url]
            changed.append((url, labels[url]))
    if changed and not dry_run:
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            tmp.replace(path)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            tag("CSV", f"Could not write {path.name}. Is it open in Excel? Close it and run again.")
            return []
    return changed


def open_rows(path: Path | None = None) -> list[dict]:
    """Rows with a blank status (jobs with documents that nobody has dealt with): url, title, company, last_checked."""
    path = path or csv_path()
    if not enabled() or not path.exists():
        return []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{"job_url": r["job_url"], "title": r.get("title", ""), "company": r.get("company", ""),
                     "last_checked": (r.get("last_checked") or "").strip()}
                    for r in csv.DictReader(f)
                    if r.get("job_url") and not (r.get("status") or "").strip()]
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        tag("CSV", f"Could not read {path.name} ({e}); treating it as empty.")
        return []


def update_rows(updates: dict[str, dict], path: Path | None = None) -> int:
    """updates maps job_url -> {"status": "closed", "last_checked": "2026-11-20"}.

    A last_checked column is added if the file has none. A status is written only into a BLANK cell, never over
    text you wrote. Returns how many rows changed (0 if the file is missing, CSV_LOG is off or Excel has it open).
    """
    path = path or csv_path()
    if not updates or not enabled() or not path.exists():
        return 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for column in ("status", "last_checked"):
        if column not in fields:
            fields.append(column)
    changed = 0
    for row in rows:
        change = updates.get(row.get("job_url"))
        if not change:
            continue
        if change.get("last_checked"):
            row["last_checked"] = change["last_checked"]
        if change.get("status") and not (row.get("status") or "").strip():
            row["status"] = change["status"]
        if change.get("clear_status") and (row.get("status") or "").strip().lower() == change["clear_status"]:
            row["status"] = ""   # only text the tool wrote itself, never your own notes
        changed += 1
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        tag("CSV", f"Could not write {path.name}. Is it open in Excel? Close it and run again.")
        return 0
    return changed
