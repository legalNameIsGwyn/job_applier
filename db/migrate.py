"""One-time copy of the old database into the new schema. The old file is never changed.

    python -m db.migrate            # writes data\\jobs_db_new.sqlite and checks every row count
    python -m db.migrate --force    # delete an earlier jobs_db_new.sqlite and start over
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from config.settings import CALIBRATION_FILE, DB_PATH
from db.models import Application, Calibration, Job, JobScore, Profile, Rating, Tracking, TrackingEvent, utcnow
from db.session import DEFAULT_PROFILE, create_tables, make_engine

OLD_DB = Path(DB_PATH)
NEW_DB = OLD_DB.with_name("jobs_db_new.sqlite")
BACKUP_DIR = OLD_DB.parent / "backups"


def _dt(text):
    if not text:
        return utcnow()
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return utcnow()


def _rows(conn, table: str) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    except sqlite3.OperationalError:   # table doesn't exist in this old database
        return []


def _json_list(text) -> list:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def migrate(force: bool = False) -> bool:
    if not OLD_DB.exists():
        sys.exit(f"[MIGRATE] No database at {OLD_DB}.")
    if NEW_DB.exists():
        if not force:
            sys.exit(f"[MIGRATE] {NEW_DB.name} already exists. Use --force to rebuild it.")
        NEW_DB.unlink()

    old = sqlite3.connect(OLD_DB.as_uri() + "?mode=ro", uri=True)   # read-only: cannot change the old file
    old.row_factory = sqlite3.Row

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"jobs_db_before_orm_{datetime.now():%Y%m%d_%H%M%S}.sqlite"
    dest = sqlite3.connect(backup)
    old.backup(dest)
    dest.close()
    print(f"[MIGRATE] Backup of the old database: {backup}")

    engine = make_engine(NEW_DB)
    create_tables(engine)

    old_jobs = _rows(old, "jobs")
    old_ratings = _rows(old, "ratings")
    old_apps = _rows(old, "applications")
    old_tracking = _rows(old, "tracking")
    old_events = _rows(old, "tracking_events")

    history, active = [], {}
    try:
        data = json.loads(Path(CALIBRATION_FILE).read_text(encoding="utf-8"))
        active = data.get("active") or {}
        history = data.get("history") or ([active] if active else [])
    except (OSError, ValueError):
        pass

    with Session(engine) as s:
        profile = Profile(name=DEFAULT_PROFILE)
        s.add(profile)
        s.flush()
        pid = profile.id

        # ---- jobs and scores (ids are kept, so the # numbers you know still work)
        label_to_id = {f"Duplicate of: {r['title']} - {r['company']}": r["id"]
                       for r in old_jobs if r.get("status") != "duplicate"}
        job_id_by_url, pending_originals, unresolved = {}, {}, 0
        for r in old_jobs:
            dup = r.get("status") == "duplicate"
            s.add(Job(id=r["id"], site=r.get("site") or "unknown", job_url=r.get("job_url"),
                      title=r.get("title") or "", company=r.get("company") or "", location=r.get("location") or "",
                      description=r.get("description") or "", scraped_at=_dt(r.get("scraped_at")),
                      apply_url=r.get("apply_url"), salary=r.get("salary"), is_duplicate=dup,
                      found_by_profile_id=pid))
            if r.get("job_url"):
                job_id_by_url[r["job_url"]] = r["id"]
            if dup:
                gaps = _json_list(r.get("gaps"))
                original = label_to_id.get(gaps[0]) if gaps else None
                if original:
                    pending_originals[r["id"]] = original
                else:
                    unresolved += 1
            else:
                s.add(JobScore(job_id=r["id"], profile_id=pid, status=r.get("status") or "scored",
                               match_score=r["match_score"], model_score=r.get("model_score"),
                               keyword_score=r.get("keyword_score"), matched_skills=r.get("matched_skills") or "[]",
                               gaps=r.get("gaps") or "[]", is_retry=r.get("is_retry") or 0,
                               scored_at=_dt(r.get("scraped_at"))))
        s.flush()
        for job_id, original_id in pending_originals.items():
            s.get(Job, job_id).duplicate_of_id = original_id

        # ---- ratings
        for r in old_ratings:
            s.add(Rating(job_url=r["job_url"], job_id=job_id_by_url.get(r["job_url"]), profile_id=pid,
                         rating=r.get("rating"), batch=r["batch"], rated_at=_dt(r.get("rated_at"))))

        # ---- calibrations (the last fit in the history is the active one)
        for i, h in enumerate(history):
            s.add(Calibration(profile_id=pid, fitted_at=h.get("fitted_at") or "", n=h.get("n") or 0,
                              latest_batch_only=bool(h.get("latest_batch_only")), w_model=h.get("w_model"),
                              a=h.get("a"), b=h.get("b"), trust=h.get("trust"), w_fit=h.get("w_fit"),
                              a_fit=h.get("a_fit"), b_fit=h.get("b_fit"), spearman_model=h.get("spearman_model"),
                              spearman_keyword=h.get("spearman_keyword"), spearman_final=h.get("spearman_final"),
                              mae_model=h.get("mae_model"), mae_final=h.get("mae_final"),
                              is_active=(i == len(history) - 1)))

        # ---- applications
        skipped_apps = 0
        for r in old_apps:
            job_id = job_id_by_url.get(r["job_url"])
            if job_id is None:
                skipped_apps += 1
                continue
            s.add(Application(job_id=job_id, profile_id=pid, apply_url=r.get("apply_url"), ats=r.get("ats"),
                              status=r["status"], note=r.get("note"), updated_at=_dt(r.get("updated_at"))))

        # ---- tracking and its events
        tracking_id_by_url = {}
        for r in old_tracking:
            t = Tracking(job_url=r["job_url"], job_id=job_id_by_url.get(r["job_url"]), profile_id=pid,
                         stage=r["stage"], applied_on=r.get("applied_on"), updated_on=r.get("updated_on"),
                         site=r.get("site"), ats=r.get("ats"), folder=r.get("folder"),
                         score_at_apply=r.get("score_at_apply"), contact_name=r.get("contact_name"),
                         contact_email=r.get("contact_email"), interview_on=r.get("interview_on"),
                         follow_up_on=r.get("follow_up_on"), notes=r.get("notes"))
            s.add(t)
            s.flush()
            tracking_id_by_url[r["job_url"]] = t.id
        skipped_events = 0
        for r in old_events:
            tid = tracking_id_by_url.get(r["job_url"])
            if tid is None:
                skipped_events += 1
                continue
            s.add(TrackingEvent(tracking_id=tid, stage=r["stage"], on_date=r["on_date"], note=r.get("note")))
        s.commit()
    old.close()

    # ---- verify: every row accounted for, same job ids, no broken links
    new = sqlite3.connect(NEW_DB)
    count = lambda table: new.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    expected = {
        "jobs": len(old_jobs),
        "job_scores": sum(1 for r in old_jobs if r.get("status") != "duplicate"),
        "ratings": len(old_ratings),
        "calibrations": len(history),
        "applications": len(old_apps) - skipped_apps,
        "tracking": len(old_tracking),
        "tracking_events": len(old_events) - skipped_events,
    }
    ok = True
    print("\n[MIGRATE] table              old/expected   new")
    for table, want in expected.items():
        got = count(table)
        ok &= got == want
        print(f"          {table:<18} {want:>10}   {got:>5}   {'ok' if got == want else 'MISMATCH'}")
    same_ids = ({r["id"] for r in old_jobs} == {row[0] for row in new.execute("SELECT id FROM jobs")})
    broken = new.execute("PRAGMA foreign_key_check").fetchall()
    integrity = new.execute("PRAGMA integrity_check").fetchone()[0]
    new.close()
    ok &= same_ids and not broken and integrity == "ok"
    print(f"          job ids identical: {same_ids};  broken links: {len(broken)};  integrity: {integrity}")

    notes = []
    if unresolved:
        notes.append(f"{unresolved} duplicate(s) are marked as duplicates but their original couldn't be identified")
    if skipped_apps:
        notes.append(f"{skipped_apps} application record(s) pointed at jobs that no longer exist and were not copied")
    if skipped_events:
        notes.append(f"{skipped_events} tracking event(s) had no tracking row and were not copied")
    for note in notes:
        print(f"[MIGRATE] Note: {note}.")
    print(f"\n[MIGRATE] {'Done' if ok else 'PROBLEM: do not use the new file'}. Old database untouched; new one: {NEW_DB}")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy the old database into the new schema.")
    parser.add_argument("--force", action="store_true", help="replace an earlier jobs_db_new.sqlite")
    raise SystemExit(0 if migrate(parser.parse_args().force) else 1)