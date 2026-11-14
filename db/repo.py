"""Saving jobs, scores and applications. Same function names as the old core/db.py, but every
score is stored for the active profile (db.session.select_profile)."""

import json

from sqlalchemy import select

from config.settings import DB_PATH
from db.models import Application, Job, JobScore, utcnow
from db.session import (
    active_profile_name, create_tables, current_profile_id, get_engine, get_or_create_profile, session_scope,
)

# match_score stored when scoring failed, so failures differ from a real 0 (auto-reject).
FAILED_SCORE = -1.0


def init_db(db_path: str = DB_PATH) -> None:
    """Create any missing tables and make sure the active profile exists."""
    create_tables(get_engine(db_path))
    with session_scope(db_path) as s:
        get_or_create_profile(s, active_profile_name())
    print(f"[DB] Initialized database at {db_path} (profile: {active_profile_name()})")


def get_scored_urls(db_path: str = DB_PATH) -> set[str]:
    """URLs already handled for the active profile: scored or filtered by it (failed ones are retried),
    plus any job known to be a duplicate."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        scored = s.scalars(
            select(Job.job_url).join(JobScore, JobScore.job_id == Job.id)
            .where(JobScore.profile_id == pid, JobScore.match_score >= 0, Job.job_url.is_not(None)))
        dupes = s.scalars(select(Job.job_url).where(Job.is_duplicate.is_(True), Job.job_url.is_not(None)))
        return set(scored) | set(dupes)


def save_job(
    job: dict,
    score: dict,
    db_path: str = DB_PATH,
    status: str | None = None,
    model_score: float | None = None,
    keyword_score: float | None = None,
    duplicate_of: str | None = None,
) -> None:
    """Insert or update one job (stored once) and the active profile's score for it.

    job:           site, job_url, title, company, location, description, apply_url, salary
    score:         match_score (the final score), matched_skills, gaps
    status:        defaults to "scored" or "scoring_failed"; "filtered" and "duplicate" are passed in
    duplicate_of:  with status="duplicate", the job_url of the posting this copies. A duplicate is
                   flagged on the job itself and gets no score row; its real scores aren't overwritten.
    """
    failed = score["match_score"] < 0
    status = status or ("scoring_failed" if failed else "scored")
    if model_score is None and not failed and status != "duplicate":
        model_score = score["match_score"]
    url = job.get("job_url") or None

    with session_scope(db_path) as s:
        row = s.scalar(select(Job).where(Job.job_url == url)) if url else None
        if row is None:
            row = Job(site=job.get("site") or "unknown", job_url=url, title=job.get("title") or "",
                        company=job.get("company") or "", location=job.get("location") or "",
                        description=job.get("description") or "", apply_url=job.get("apply_url") or None, 
                        salary=job.get("salary") or None, found_by_profile_id=current_profile_id(s))
            s.add(row)
            s.add(row)
            s.flush()
        else:
            if job.get("description") and not row.description:   # filtered jobs were saved before the page was fetched
                row.description = job["description"]
            if job.get("apply_url"):
                row.apply_url = job["apply_url"]
            if job.get("salary"):
                row.salary = job["salary"]

        if status == "duplicate":
            row.is_duplicate = True
            if duplicate_of:
                row.duplicate_of_id = s.scalar(select(Job.id).where(Job.job_url == duplicate_of))
            return

        pid = current_profile_id(s)
        values = dict(
            status=status, match_score=float(score["match_score"]),
            model_score=None if model_score is None else float(model_score),
            keyword_score=None if keyword_score is None else float(keyword_score),
            matched_skills=json.dumps(list(score.get("matched_skills", []))),
            gaps=json.dumps(list(score.get("gaps", []))),
        )
        existing = s.scalar(select(JobScore).where(JobScore.job_id == row.id, JobScore.profile_id == pid))
        if existing is None:
            s.add(JobScore(job_id=row.id, profile_id=pid, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.is_retry = 1


def set_apply_url(job_url: str, apply_url: str, db_path: str = DB_PATH) -> bool:
    """Store the employer's own application link for a job. False if the job isn't in the database."""
    with session_scope(db_path) as s:
        row = s.scalar(select(Job).where(Job.job_url == job_url))
        if row is None:
            return False
        row.apply_url = apply_url
        return True


def record_application(job_url: str, status: str, apply_url: str | None = None,
                       ats: str | None = None, note: str | None = None, db_path: str = DB_PATH) -> bool:
    """Remember what happened with a job (applied / skipped / opened / closed). False if the job isn't in the database."""
    with session_scope(db_path) as s:
        job_id = s.scalar(select(Job.id).where(Job.job_url == job_url))
        if job_id is None:
            return False
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        if app is None:
            s.add(Application(job_id=job_id, profile_id=current_profile_id(s), apply_url=apply_url,
                              ats=ats, status=status, note=note))
        else:
            app.status = status
            app.apply_url = apply_url or app.apply_url
            app.ats = ats or app.ats
            app.note = note or app.note
            app.updated_at = utcnow()
        return True