"""The list of jobs you can click through and apply to by hand: applications.xlsx (or applications.csv).

It sits next to the applications folder (profiles/<name>/applications.xlsx), one row per job.
A job whose URL is already in the file is never added twice. Every write re-sorts the whole list (see sort_rows):
newest date first, then jobs without a status, then highest score, then highest compat_pct. Sorting by hand in
Excel is therefore undone the next time the list is written.
Turn it off with CSV_LOG = False in config/settings.py. LOG_FORMAT = "xlsx" (default) or "csv" picks the file type.

If LOG_FORMAT is "xlsx" and there is no applications.xlsx yet but an applications.csv is beside it,
the CSV's rows are imported the first time the list is written. The CSV itself is left untouched.

The function names (log_job, known_urls, handled_urls, sync_statuses, open_rows, update_rows, csv_path)
are the same for both formats, so nothing else in the project cares which one is in use.
"""

import csv
import zipfile
from datetime import date
from pathlib import Path

import config.settings as _settings
from core.console import tag

COLUMNS = ["job_url", "score", "compat_pct", "title",  "folder", "status", "company", "location", "mode", "date", "last_checked"]
NUMERIC_COLUMNS = ("score", "compat_pct")
FORMATS = ("xlsx", "csv")
MAX_LINK_LENGTH = 2000          # Excel refuses links much longer than this
_STAMP_PREFIX = "project folder: "   # saved in the .xlsx so a moved project can be noticed

# What reading the file can raise. If it does, nothing is written back, so a damaged file is never overwritten.
_READ_ERRORS = (OSError, csv.Error, UnicodeDecodeError, zipfile.BadZipFile, KeyError, ValueError)

_announced: set[str] = set()   # messages already printed this run, so they aren't repeated


def _once(key: str, message: str) -> None:
    if key not in _announced:
        _announced.add(key)
        tag("CSV", message)


# --------------------------------------------------------------------------- settings and paths

def enabled() -> bool:
    return bool(getattr(_settings, "CSV_LOG", True))


def log_format() -> str:
    """"xlsx" or "csv" from LOG_FORMAT in settings (default xlsx). Anything else falls back to xlsx."""
    fmt = str(getattr(_settings, "LOG_FORMAT", "xlsx")).strip().lower()
    if fmt not in FORMATS:
        _once("badformat", f'LOG_FORMAT = "{fmt}" is not "xlsx" or "csv"; using "xlsx".')
        return "xlsx"
    return fmt


def csv_path() -> Path:
    """CSV_LOG_PATH in settings if set (its extension follows LOG_FORMAT), otherwise applications.<format>
    beside the applications folder."""
    suffix = "." + log_format()
    custom = getattr(_settings, "CSV_LOG_PATH", None)
    if custom:
        return Path(custom).with_suffix(suffix)
    return Path(_settings.APPLICATIONS_DIR).parent / f"applications{suffix}"


def _legacy_csv(path: Path) -> Path | None:
    """The old applications.csv to import from: only when `path` is an .xlsx that doesn't exist yet."""
    if path.suffix.lower() != ".xlsx" or path.exists():
        return None
    old = path.with_suffix(".csv")
    return old if old.exists() else None


def log_exists(path: Path | None = None) -> bool:
    """True if the list exists (or an old CSV is waiting to be imported into it)."""
    path = path or csv_path()
    return path.exists() or _legacy_csv(path) is not None


# ---------------------------------------------------------------------------- reading and writing

def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value):
    """A float if the value is a number or numeric text, otherwise the value unchanged ("" and None stay blank)."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return value


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(r) for r in reader]


def _stamp() -> str:
    """Where the project is right now: the folder the generated documents live in."""
    return str(Path(_settings.APPLICATIONS_DIR).absolute())


def _read_xlsx(path: Path) -> tuple[list[str], list[dict], str]:
    """(column names, rows, the project folder this file's links were written for; "" if unknown)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        stamp = _text(wb.properties.description)
        stamp = stamp[len(_STAMP_PREFIX):] if stamp.startswith(_STAMP_PREFIX) else ""
        lines = wb.worksheets[0].iter_rows(values_only=True)
        header = next(lines, None)
        if not header:
            return [], [], stamp
        names = [_text(h) for h in header]
        rows = []
        for values in lines:
            if all(v is None or v == "" for v in values):
                continue
            rows.append({n: v for n, v in zip(names, values) if n})
        return [n for n in names if n], rows, stamp
    finally:
        wb.close()   # lets go of the file so it can be replaced afterwards


def _load(path: Path) -> tuple[list[str], list[dict]]:
    """(column names, rows) from the list. Empty if there is no file yet. Raises _READ_ERRORS if it can't be read."""
    legacy = _legacy_csv(path)
    if legacy is not None:
        _once("import", f"Importing {legacy.name} into {path.name} ({legacy.name} is left as it is).")
        fields, rows = _read_csv(legacy)
        fields = COLUMNS + [f for f in fields if f not in COLUMNS]   # the old file may use another column order
        _save(path, fields, rows, "it is created on the next run")   # create the .xlsx now, once
        return fields, rows
    if not path.exists():
        return [], []
    if path.suffix.lower() != ".xlsx":
        return _read_csv(path)
    fields, rows, stamp = _read_xlsx(path)
    if rows and stamp != _stamp() and "refresh_failed" not in _announced:
        # The project was moved (or this sheet has no links yet): write it again so every link points at the right place.
        _once("refresh", f"Refreshing the links in {path.name} for the project's current location.")
        if not _save(path, _all_columns(fields), rows, "the links are refreshed on the next run"):
            _announced.add("refresh_failed")   # don't try (and complain) again on every read this run
    return fields, rows


def _all_columns(fields: list[str]) -> list[str]:
    """The file's own columns in their order, plus any of ours it doesn't have yet at the end."""
    fields = list(fields)
    return fields + [c for c in COLUMNS if c not in fields]


def _write_xlsx(path: Path, fields: list[str], rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    wb = Workbook()
    wb.properties.description = _STAMP_PREFIX + _stamp()
    ws = wb.active
    ws.title = "Applications"
    ws.append(fields)
    for r, row in enumerate(rows, start=2):
        for c, field in enumerate(fields, start=1):
            value = row.get(field)
            if field in NUMERIC_COLUMNS:
                value = _number(value)
            if value is None or value == "":
                continue
            if isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)
            cell = ws.cell(row=r, column=c, value=value)
            if isinstance(value, str):
                cell.data_type = "s"    # text stays text, even if it starts with "="
                target = _link_target(field, value)
                if target:
                    cell.hyperlink = target   # the cell's text is unchanged; only the link is added
                    cell.style = "Hyperlink"
    wb.save(path)


def _link_target(field: str, value: str) -> str | None:
    """Where a cell should link to: the posting for job_url, the application's folder for folder."""
    value = value.strip()
    if field == "job_url" and value.lower().startswith(("http://", "https://")):
        target = value
    elif field == "folder" and value:
        target = (Path(_settings.APPLICATIONS_DIR) / value).absolute().as_uri()
    else:
        return None
    return target if len(target) <= MAX_LINK_LENGTH else None


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {k: (f"{v:g}" if isinstance(v, float) else v) for k, v in row.items()}
            for field in NUMERIC_COLUMNS:
                value = _number(out.get(field))
                out[field] = f"{value:g}" if isinstance(value, float) else value
            writer.writerow(out)


def sort_rows(rows: list[dict]) -> list[dict]:
    """Newest date group first. Inside a date: jobs with no status before jobs with one, then the highest score,
    then the highest compat_pct. Rows that tie keep the order they already had."""
    def number(row, field):
        value = _number(row.get(field))
        return value if isinstance(value, float) else -1.0   # a blank or unreadable score sorts last
    rows = list(rows)
    rows.sort(key=lambda r: number(r, "compat_pct"), reverse=True)
    rows.sort(key=lambda r: number(r, "score"), reverse=True)
    rows.sort(key=lambda r: bool(_text(r.get("status"))))      # False (no status yet) comes first
    rows.sort(key=lambda r: _text(r.get("date"))[:10], reverse=True)
    return rows


def _save(path: Path, fields: list[str], rows: list[dict], retry_note: str) -> bool:
    """Sort the list, write it to a temporary file, then swap it in. False (with a message) if that can't be done."""
    rows = sort_rows(rows)
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        (_write_xlsx if path.suffix.lower() == ".xlsx" else _write_csv)(tmp, fields, rows)
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        tag("CSV", f"Could not write {path.name}. Is it open in Excel? Close it; {retry_note}.")
        return False
    except OSError as e:
        tmp.unlink(missing_ok=True)
        tag("CSV", f"Could not write {path.name}: {e}")
        return False
    return True


def _try_load(path: Path):
    """_load, or None (with a message) if the file can't be read."""
    try:
        return _load(path)
    except _READ_ERRORS as e:
        tag("CSV", f"Could not read {path.name} ({e}); leaving it alone.")
        return None


# ----------------------------------------------------------------------------------- the list

def known_urls(path: Path | None = None) -> set[str]:
    """Every job_url already in the list (empty if the file is missing or CSV_LOG is off)."""
    if not enabled():
        return set()
    loaded = _try_load(path or csv_path())
    if loaded is None:
        return set()
    return {_text(r.get("job_url")) for r in loaded[1]} - {""}


def _compat(job: dict):
    pct = job.get("compat_detail_pct")
    if pct is None:
        pct = job.get("compat_pct")
    return "" if pct is None else float(pct)


def log_job(job: dict, folder_name: str, mode: str = "", path: Path | None = None) -> bool:
    """Append one row. Returns True if a row was added, False if skipped (already there, or CSV_LOG is off)."""
    if not enabled():
        return False
    path = path or csv_path()
    loaded = _try_load(path)
    if loaded is None:
        return False
    fields, rows = loaded
    if any(_text(r.get("job_url")) == job["job_url"] for r in rows):
        return False
    rows.append({
        "date": date.today().isoformat(), "title": job["title"], "company": job["company"],
        "location": job.get("location", ""),
        "score": float(job["match_score"]) if job.get("match_score") is not None else "",
        "compat_pct": _compat(job), "mode": mode, "job_url": job["job_url"], "folder": folder_name, "status": "",
    })
    return _save(path, _all_columns(fields), rows, "the row is added on the next run")


def handled_urls(path: Path | None = None) -> set[str]:
    """job_urls whose status cell is not blank: you (or a past run) already dealt with them."""
    if not enabled():
        return set()
    loaded = _try_load(path or csv_path())
    if loaded is None:
        return set()
    return {_text(r.get("job_url")) for r in loaded[1] if _text(r.get("status")) and _text(r.get("job_url"))}


def sync_statuses(labels: dict[str, str], path: Path | None = None, dry_run: bool = False) -> list[tuple[str, str]]:
    """Fill BLANK status cells. labels maps job_url -> text. Never overwrites a cell you filled.

    Returns the (job_url, text) pairs filled (or that would be, with dry_run).
    """
    path = path or csv_path()
    if not enabled() or not log_exists(path):
        return []
    loaded = _try_load(path)
    if loaded is None:
        return []
    fields, rows = loaded
    if "status" not in fields:
        return []
    changed = []
    for row in rows:
        url = _text(row.get("job_url"))
        if url in labels and not _text(row.get("status")):
            row["status"] = labels[url]
            changed.append((url, labels[url]))
    if changed and not dry_run and not _save(path, _all_columns(fields), rows, "run it again"):
        return []
    return changed


def open_rows(path: Path | None = None) -> list[dict]:
    """Rows with a blank status (jobs with documents that nobody has dealt with): url, title, company, last_checked."""
    if not enabled():
        return []
    loaded = _try_load(path or csv_path())
    if loaded is None:
        return []
    return [{"job_url": _text(r.get("job_url")), "title": _text(r.get("title")), "company": _text(r.get("company")),
             "last_checked": _text(r.get("last_checked"))}
            for r in loaded[1] if _text(r.get("job_url")) and not _text(r.get("status"))]


def update_rows(updates: dict[str, dict], path: Path | None = None) -> int:
    """updates maps job_url -> {"status": "closed", "last_checked": "2026-11-20"}.

    A last_checked column is added if the file has none. A status is written only into a BLANK cell, never over
    text you wrote. Returns how many rows changed (0 if the file is missing, CSV_LOG is off or Excel has it open).
    """
    path = path or csv_path()
    if not updates or not enabled() or not log_exists(path):
        return 0
    loaded = _try_load(path)
    if loaded is None:
        return 0
    fields, rows = loaded
    changed = 0
    for row in rows:
        change = updates.get(_text(row.get("job_url")))
        if not change:
            continue
        if change.get("last_checked"):
            row["last_checked"] = change["last_checked"]
        if change.get("status") and not _text(row.get("status")):
            row["status"] = change["status"]
        if change.get("clear_status") and _text(row.get("status")).lower() == change["clear_status"]:
            row["status"] = ""   # only text the tool wrote itself, never your own notes
        changed += 1
    if changed and not _save(path, _all_columns(fields), rows, "run it again"):
        return 0
    return changed