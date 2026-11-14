"""Your hand ratings, per profile. Ratings are keyed by job_url, so they survive clearing the jobs table."""

from sqlalchemy import and_, delete, func, select

from config.settings import DB_PATH
from db.models import Calibration, Job, JobScore, Rating, utcnow
from db.session import current_profile_id, session_scope

_MODEL = func.coalesce(JobScore.model_score, JobScore.match_score)


def _usable_scored(q, pid):
    """Restrict a query on Job + JobScore to jobs this profile really scored (not rejects or duplicates)."""
    return q.where(JobScore.profile_id == pid, JobScore.status == "scored", _MODEL > 0,
                   Job.is_duplicate.is_(False), ~JobScore.gaps.like("%auto-rejected%"))


def eligible_jobs(rerate: bool = False, db_path: str = DB_PATH) -> list[dict]:
    """Jobs to rate. rerate=False: scored jobs you haven't rated or skipped.
    rerate=True: jobs you already gave a rating (skipped ones are not offered), with last_rated_at."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(Job, JobScore, Rating).join(JobScore, JobScore.job_id == Job.id)
             .outerjoin(Rating, and_(Rating.job_url == Job.job_url, Rating.profile_id == pid))
             .where(func.trim(Job.description) != "", Job.job_url.is_not(None)))
        q = _usable_scored(q, pid)
        q = q.where(Rating.rating.is_not(None)) if rerate else q.where(Rating.id.is_(None))
        out = []
        for job, sc, r in s.execute(q).all():
            d = dict(job_url=job.job_url, title=job.title, company=job.company, location=job.location,
                     description=job.description, matched_skills=sc.matched_skills, gaps=sc.gaps,
                     salary=job.salary, model_score=sc.model_score if sc.model_score is not None else sc.match_score)
            if r is not None:
                d["old_rating"] = r.rating
                d["last_rated_at"] = r.rerated_at or r.rated_at
            out.append(d)
        return out


def load_pool(db_path: str = DB_PATH) -> list[dict]:
    """Scored or duplicate jobs (with your rating, if any) to compare against while rating."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(Job, JobScore.status, Rating.rating)
             .outerjoin(JobScore, and_(JobScore.job_id == Job.id, JobScore.profile_id == pid))
             .outerjoin(Rating, and_(Rating.job_url == Job.job_url, Rating.profile_id == pid))
             .where(Job.job_url.is_not(None)))
        out = []
        for job, status, rating in s.execute(q).all():
            if job.is_duplicate:
                status = "duplicate"
            elif status != "scored":
                continue
            out.append(dict(job_url=job.job_url, title=job.title, company=job.company, location=job.location,
                            description=job.description, status=status,
                            scraped_at=job.scraped_at.strftime("%Y-%m-%d %H:%M:%S"), rating=rating))
        return out


def next_batch_id(db_path: str = DB_PATH) -> int:
    with session_scope(db_path) as s:
        return s.scalar(select(func.coalesce(func.max(Rating.batch), 0) + 1)
                        .where(Rating.profile_id == current_profile_id(s)))


def save_rating(job_url: str, rating: float | None, batch: int, rerate: bool = False,
                db_path: str = DB_PATH) -> None:
    """Save a rating (None = skipped). When re-rating, a skip leaves the old rating alone, and a new
    rating replaces the old one, which moves to previous_rating."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        row = s.scalar(select(Rating).where(Rating.job_url == job_url, Rating.profile_id == pid))
        if row is not None and rerate:
            if rating is None:
                return
            row.previous_rating, row.rating, row.batch, row.rerated_at = row.rating, rating, batch, utcnow()
            return
        job_id = s.scalar(select(Job.id).where(Job.job_url == job_url))
        if row is None:
            s.add(Rating(job_url=job_url, job_id=job_id, profile_id=pid, rating=rating, batch=batch))
        else:
            row.rating, row.batch, row.rated_at, row.job_id = rating, batch, utcnow(), job_id


def mark_duplicate(job_url: str, original_url: str | None = None, db_path: str = DB_PATH) -> None:
    """You flagged a job as a copy: it leaves the tuning and the rankings (for every profile)."""
    with session_scope(db_path) as s:
        job = s.scalar(select(Job).where(Job.job_url == job_url))
        if job is None:
            return
        job.is_duplicate = True
        if original_url:
            job.duplicate_of_id = s.scalar(select(Job.id).where(Job.job_url == original_url))


def fit_rows(batch: int | None = None, db_path: str = DB_PATH) -> list[dict]:
    """Rated, usable jobs for fitting: model, kw (may be None), rating, title, company, description."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(_MODEL, JobScore.keyword_score, Rating.rating, Job.title, Job.company, Job.description)
             .select_from(Rating).join(Job, Job.job_url == Rating.job_url)
             .join(JobScore, JobScore.job_id == Job.id).where(Rating.profile_id == pid, Rating.rating.is_not(None)))
        q = _usable_scored(q, pid)
        if batch is not None:
            q = q.where(Rating.batch == batch)
        return [dict(model=r[0], kw=r[1], rating=r[2], title=r[3], company=r[4], description=r[5])
                for r in s.execute(q).all()]


def usable_rating_count(db_path: str = DB_PATH) -> int:
    return len(fit_rows(None, db_path))


def unrated_count(db_path: str = DB_PATH) -> int:
    return len(eligible_jobs(False, db_path))


def rating_count(db_path: str = DB_PATH) -> int:
    """Every rating row for the profile, skips included."""
    with session_scope(db_path) as s:
        return s.scalar(select(func.count()).select_from(Rating).where(Rating.profile_id == current_profile_id(s)))


def reset_ratings(db_path: str = DB_PATH) -> None:
    """Delete this profile's ratings and calibration history."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        s.execute(delete(Rating).where(Rating.profile_id == pid))
        s.execute(delete(Calibration).where(Calibration.profile_id == pid))