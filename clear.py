"""Clear the jobs database and/or archive the generated application documents.

    python clear.py db               # empty the jobs database (a backup copy is made first)
    python clear.py docs             # move every application folder into an archive folder
    python clear.py all              # both

    python clear.py db --dry-run     # show what would happen; change nothing
    python clear.py all --yes        # don't ask for confirmation
    python clear.py db --ratings     # ALSO delete your hand ratings and the score calibration
    python clear.py db --no-backup   # skip the backup copy of the database

What each one does
  db    Deletes every job and every application record (applied / skipped / opened / closed) from the
        database. Your hand ratings and calibration.json are KEPT unless you add --ratings: they match
        jobs by URL, so ratings still count when the same jobs are scraped again. Before anything is
        deleted the whole database file is copied to BACKUP_DIR, so this can be undone by copying it back.
  docs  Moves the folders in APPLICATIONS_DIR into a new, dated folder in ARCHIVE_DIR. Nothing is
        deleted. Jobs left without documents get new ones the next time main.py runs.

After clearing the database, the next `python main.py` scrapes, filters and scores everything from scratch.
Other files (resume.json, learned_answers.json, browser_profile, config) are never touched.
Locations come from config/settings.py (DB_PATH, APPLICATIONS_DIR); BACKUP_DIR and ARCHIVE_DIR are
optional settings there and default to folders inside data/.
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import config.settings as _settings

DB_PATH = _settings.DB_PATH
APPLICATIONS_DIR = Path(_settings.APPLICATIONS_DIR)
_DATA_DIR = Path(DB_PATH).resolve().parent
BACKUP_DIR = Path(getattr(_settings, "BACKUP_DIR", _DATA_DIR / "backups"))
ARCHIVE_DIR = Path(getattr(_settings, "ARCHIVE_DIR", _DATA_DIR / "archived_applications"))
CALIBRATION_FILE = Path(getattr(_settings, "CALIBRATION_FILE", _DATA_DIR / "calibration.json"))

JOB_TABLES = ("jobs", "applications")   # always cleared
RATING_TABLES = ("ratings",)            # cleared only with --ratings


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _count(conn, table: str) -> int | None:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:  # table doesn't exist yet
        return None


# ------------------------------------------------------------------------------ database


def clear_database(db_path=DB_PATH, include_ratings=False, backup=True, backup_dir=BACKUP_DIR,
                   calibration_file=CALIBRATION_FILE, dry_run=False, show=print) -> dict | None:
    """Empty the jobs database. Returns {table: rows deleted} (None if there is no database)."""
    if not Path(db_path).exists():
        show(f"[CLEAR] No database at {db_path}; nothing to clear.")
        return None

    tables = JOB_TABLES + (RATING_TABLES if include_ratings else ())
    conn = sqlite3.connect(db_path)
    try:
        counts = {t: _count(conn, t) for t in tables}
        kept = None if include_ratings else _count(conn, "ratings")
        show("[CLEAR] Database: " + ", ".join(f"{n} {t}" for t, n in counts.items() if n is not None))
        if kept:
            show(f"[CLEAR] Keeping {kept} hand rating(s) and the calibration (add --ratings to delete them too).")
        if dry_run:
            show("[CLEAR] Dry run: nothing was changed.")
            return {t: n or 0 for t, n in counts.items()}

        if backup:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            target = Path(backup_dir) / f"{Path(db_path).stem}_{_stamp()}{Path(db_path).suffix or '.sqlite'}"
            dest = sqlite3.connect(target)
            try:
                conn.backup(dest)   # a consistent copy even if something else has the file open
            finally:
                dest.close()
            show(f"[CLEAR] Backup saved: {target}")

        with conn:
            for table, n in counts.items():
                if n is not None:
                    conn.execute(f"DELETE FROM {table}")
            if _has_sequence(conn):
                conn.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")   # ids start from 1 again
        conn.execute("VACUUM")   # give the space back to the disk
    finally:
        conn.close()

    if include_ratings:
        Path(calibration_file).unlink(missing_ok=True)
        show(f"[CLEAR] Deleted the score calibration: {Path(calibration_file).resolve()}")
    show("[CLEAR] Database cleared.")
    return {t: n or 0 for t, n in counts.items()}


def _has_sequence(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone())


# -------------------------------------------------------------------------------- documents


def archive_documents(apps_dir=APPLICATIONS_DIR, archive_dir=ARCHIVE_DIR, dry_run=False, show=print) -> Path | None:
    """Move every application folder into archive_dir/applications_<date>. Returns the new folder."""
    apps_dir = Path(apps_dir)
    items = sorted(apps_dir.iterdir()) if apps_dir.is_dir() else []
    if not items:
        show(f"[CLEAR] No application documents in {apps_dir}; nothing to archive.")
        return None
    show(f"[CLEAR] Documents: {len(items)} application folder(s) in {apps_dir}")
    destination = Path(archive_dir) / f"applications_{_stamp()}"
    if dry_run:
        show(f"[CLEAR] Dry run: they would be moved to {destination}")
        return None
    destination.mkdir(parents=True, exist_ok=False)
    for item in items:
        shutil.move(str(item), str(destination / item.name))
    show(f"[CLEAR] Moved {len(items)} item(s) to {destination}")
    return destination


# ------------------------------------------------------------------------------------ CLI


def _confirm(what: str, word: str) -> bool:
    return input(f"{what}\nType {word} to continue: ").strip() == word


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear the jobs database and/or archive application documents.")
    parser.add_argument("what", choices=["db", "docs", "all"], help="what to clear")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    parser.add_argument("--ratings", action="store_true", help="with db/all: also delete hand ratings and calibration")
    parser.add_argument("--no-backup", action="store_true", help="with db/all: don't copy the database first")
    args = parser.parse_args()

    do_db, do_docs = args.what in ("db", "all"), args.what in ("docs", "all")
    parts = []
    if do_db:
        parts.append("empty the jobs database" + (f" AND delete your hand ratings and {CALIBRATION_FILE.resolve()}" if args.ratings else ""))
    if do_docs:
        parts.append("move the application documents to an archive folder")
    if not args.dry_run and not args.yes:
        if not _confirm("This will " + " and ".join(parts) + ".", "CLEAR"):
            raise SystemExit("[CLEAR] Cancelled. Nothing was changed.")

    if do_db:
        clear_database(include_ratings=args.ratings, backup=not args.no_backup, dry_run=args.dry_run)
    if do_docs:
        archive_documents(dry_run=args.dry_run)