"""Clear job data from the database and/or archive the generated application documents.

    python -m tools.clear db --profile software      # clear ONE profile's scores and applications
    python -m tools.clear db --profile-all           # clear EVERY profile (all jobs, scores, applications)
    python -m tools.clear docs                       # move every application folder into an archive folder
    python -m tools.clear all --profile-all          # db (all profiles) and docs

    python -m tools.clear db --profile software --dry-run   # show what would happen; change nothing
    python -m tools.clear db --profile-all --yes             # don't ask for confirmation
    python -m tools.clear db --profile software --ratings    # ALSO delete that profile's ratings and calibrations
    python -m tools.clear db --profile-all --no-backup       # skip the backup copy of the database

db needs --profile NAME or --profile-all (one of them, never both), so nothing is cleared by accident.

What each one does
  db --profile NAME   Deletes that profile's scores and application records. A job is deleted too when
                      nobody else needs it: it was found or scored by this profile, and no other profile has
                      scored it or applied to it. Jobs other profiles still use stay.
  db --profile-all    Deletes every job, every score and every application record, for all profiles.
  Either way          Your hand ratings and calibrations are KEPT unless you add --ratings (ratings are keyed
                      by job URL, so they still count when the same jobs are scraped again). Application
                      tracking (track.py) and the profiles themselves are never deleted. Before anything is
                      deleted the whole database file is copied to BACKUP_DIR, so this can be undone by copying
                      it back.
  docs                Moves the folders in APPLICATIONS_DIR into a new, dated folder in ARCHIVE_DIR. Nothing is
                      deleted. Jobs left without documents get new ones the next time main.py runs.

Other files (resume.json, learned_answers.json, browser_profile, config) are never touched.
Locations come from config/settings.py (DB_PATH, APPLICATIONS_DIR); BACKUP_DIR and ARCHIVE_DIR are
optional settings there and default to folders inside data/.
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select

import config.settings as _settings
from db.models import Application, Calibration, Job, JobScore, Profile, Rating
from db.session import create_tables, get_engine, session_scope

DB_PATH = _settings.DB_PATH
APPLICATIONS_DIR = Path(_settings.APPLICATIONS_DIR)
_DATA_DIR = Path(DB_PATH).resolve().parent
BACKUP_DIR = Path(getattr(_settings, "BACKUP_DIR", _DATA_DIR / "backups"))
ARCHIVE_DIR = Path(getattr(_settings, "ARCHIVE_DIR", _DATA_DIR / "archived_applications"))


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ------------------------------------------------------------------------------ database


def _count(session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _profile_id(session, name: str) -> int:
    pid = session.scalar(select(Profile.id).where(Profile.name == name))
    if pid is None:
        known = ", ".join(session.scalars(select(Profile.name).order_by(Profile.name))) or "none"
        raise SystemExit(f"[CLEAR] No profile named '{name}'. Existing profiles: {known}.")
    return pid


def _job_ids_for_profile(session, pid: int) -> list[int]:
    """Jobs that go away with this profile: it found or scored them, and no other profile needs them."""
    used_elsewhere = (exists().where(JobScore.job_id == Job.id, JobScore.profile_id != pid)
                      | exists().where(Application.job_id == Job.id, Application.profile_id != pid))
    mine = or_(exists().where(JobScore.job_id == Job.id, JobScore.profile_id == pid),
               Job.found_by_profile_id == pid)
    return list(session.scalars(select(Job.id).where(mine, ~used_elsewhere)))


def clear_database(db_path=DB_PATH, profile: str | None = None, all_profiles: bool = False,
                   include_ratings=False, backup=True, backup_dir=BACKUP_DIR, dry_run=False,
                   show=print) -> dict | None:
    """Clear one profile's data (profile=NAME) or everything (all_profiles=True).
    Returns {what: rows affected} (None if there is no database)."""
    if bool(profile) == bool(all_profiles):
        raise ValueError("give exactly one of profile=NAME or all_profiles=True")
    if not Path(db_path).exists():
        show(f"[CLEAR] No database at {db_path}; nothing to clear.")
        return None
    create_tables(get_engine(db_path))   # also refuses a database that still has the old schema

    with session_scope(db_path) as s:
        pid = None if all_profiles else _profile_id(s, profile)
        if pid is None:
            counts = {"jobs": _count(s, Job), "scores": _count(s, JobScore), "applications": _count(s, Application)}
            ratings, calibrations = _count(s, Rating), _count(s, Calibration)
        else:
            counts = {"jobs": len(_job_ids_for_profile(s, pid)), "scores": _count(s, JobScore, JobScore.profile_id == pid),
                      "applications": _count(s, Application, Application.profile_id == pid)}
            ratings = _count(s, Rating, Rating.profile_id == pid)
            calibrations = _count(s, Calibration, Calibration.profile_id == pid)

    scope = "ALL profiles" if all_profiles else f"profile '{profile}'"
    show(f"[CLEAR] {scope}: " + ", ".join(f"{n} {what}" for what, n in counts.items()))
    if include_ratings:
        show(f"[CLEAR] Also deleting {ratings} hand rating(s) and {calibrations} calibration fit(s).")
    elif ratings or calibrations:
        show(f"[CLEAR] Keeping {ratings} hand rating(s) and {calibrations} calibration fit(s) "
             "(add --ratings to delete them too).")
    if dry_run:
        show("[CLEAR] Dry run: nothing was changed.")
        return counts

    if backup:
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        target = Path(backup_dir) / f"{Path(db_path).stem}_{_stamp()}{Path(db_path).suffix or '.sqlite'}"
        source, dest = sqlite3.connect(db_path), sqlite3.connect(target)
        try:
            source.backup(dest)   # a consistent copy even if something else has the file open
        finally:
            dest.close()
            source.close()
        show(f"[CLEAR] Backup saved: {target}")

    with session_scope(db_path) as s:
        if pid is None:
            s.execute(delete(Application))
            s.execute(delete(JobScore))
            s.execute(delete(Job))
            if include_ratings:
                s.execute(delete(Rating))
                s.execute(delete(Calibration))
        else:
            job_ids = _job_ids_for_profile(s, pid)   # worked out before this profile's scores disappear
            s.execute(delete(Application).where(Application.profile_id == pid))
            s.execute(delete(JobScore).where(JobScore.profile_id == pid))
            for i in range(0, len(job_ids), 500):
                s.execute(delete(Job).where(Job.id.in_(job_ids[i:i + 500])))
            if include_ratings:
                s.execute(delete(Rating).where(Rating.profile_id == pid))
                s.execute(delete(Calibration).where(Calibration.profile_id == pid))

    with get_engine(db_path).connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("VACUUM")   # give the space back to the disk
    show("[CLEAR] Database cleared.")
    return counts


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
    return input(f"{what}\nAre you sure? Type {word} to continue: ").strip() == word


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear job data and/or archive application documents.")
    parser.add_argument("what", choices=["db", "docs", "all"], help="what to clear")
    parser.add_argument("--profile", metavar="NAME", help="with db/all: clear only this profile's data")
    parser.add_argument("--profile-all", action="store_true", help="with db/all: clear every profile's data")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    parser.add_argument("--ratings", action="store_true", help="with db/all: also delete hand ratings and calibrations")
    parser.add_argument("--no-backup", action="store_true", help="with db/all: don't copy the database first")
    args = parser.parse_args()

    do_db, do_docs = args.what in ("db", "all"), args.what in ("docs", "all")
    if do_db and bool(args.profile) == bool(args.profile_all):
        parser.error("db needs exactly one of --profile NAME or --profile-all")

    parts = []
    if do_db:
        scope = "EVERY profile" if args.profile_all else f"profile '{args.profile}'"
        parts.append(f"clear the jobs data of {scope}" + (" AND delete the hand ratings and calibrations" if args.ratings else ""))
    if do_docs:
        parts.append("move the application documents to an archive folder")
    if not args.dry_run and not args.yes:
        word = "CLEAR ALL" if (do_db and args.profile_all) else "CLEAR"
        if not _confirm("This will " + " and ".join(parts) + ".", word):
            raise SystemExit("[CLEAR] Cancelled. Nothing was changed.")

    if do_db:
        clear_database(profile=args.profile, all_profiles=args.profile_all, include_ratings=args.ratings,
                       backup=not args.no_backup, dry_run=args.dry_run)
    if do_docs:
        archive_documents(dry_run=args.dry_run)