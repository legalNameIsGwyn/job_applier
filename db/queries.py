"""Read queries the tools share: job lists, apply candidates, rescore targets, duplicates, summary and stats."""

import json
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select

from config.settings import DB_PATH
from core.csv_log import handled_urls
from db.models import Application, Job, JobScore, utcnow
from db.session import current_profile_id, session_scope


def _since(days) -> datetime:
    return utcnow() - timedelta(days=float(days))


def _json_list(value) -> list:
    try:
        items = json.loads(value)
    except (TypeError, ValueError):
        return [value] if value else []
    return items if isinstance(items, list) else []


def _on_score(pid):
    return and_(JobScore.job_id == Job.id, JobScore.profile_id == pid)


# ------------------------------------------------------------------- job lists


def get_jobs(n: int = 10, order: str = "top", min_score: float | None = None, max_score: float | None = None,
             days: float | None = None, include_zero: bool = True, failed_only: bool = False,
             db_path: str = DB_PATH) -> list[dict]:
    """Top or bottom N jobs the active profile scored. Duplicates are left out."""
    if order not in ("top", "bottom"):
        raise ValueError("order must be 'top' or 'bottom'")
    with session_scope(db_path) as s:
        q = (select(Job, JobScore).join(JobScore, JobScore.job_id == Job.id)
             .where(JobScore.profile_id == current_profile_id(s), Job.is_duplicate.is_(False)))
        if failed_only:
            q = q.where(JobScore.match_score < 0)
        else:
            q = q.where(JobScore.match_score >= 0)
            if not include_zero:
                q = q.where(JobScore.match_score > 0)
        if min_score is not None:
            q = q.where(JobScore.match_score >= min_score)
        if max_score is not None:
            q = q.where(JobScore.match_score <= max_score)
        if days is not None:
            q = q.where(JobScore.scored_at >= _since(days))
        col = JobScore.match_score
        q = q.order_by(col.desc() if order == "top" else col.asc(), JobScore.scored_at.desc()).limit(int(n))
        return [dict(id=j.id, title=j.title, company=j.company, location=j.location, job_url=j.job_url,
                     match_score=sc.match_score, compat_pct=sc.compat_pct, compat_detail_pct=sc.compat_detail_pct,
                     compat_missing=_json_list(sc.compat_missing), compat_capped=bool(sc.compat_capped),
                     matched_skills=_json_list(sc.matched_skills),
                     gaps=_json_list(sc.gaps), description=j.description, salary=j.salary, apply_url=j.apply_url,
                     scraped_at=str(j.scraped_at)) for j, sc in s.execute(q).all()]


def get_job_by_url(url: str, db_path: str = DB_PATH) -> dict | None:
    with session_scope(db_path) as s:
        r = s.execute(select(Job, JobScore).outerjoin(JobScore, _on_score(current_profile_id(s)))
                      .where(Job.job_url == url)).first()
        if not r:
            return None
        j, sc = r
        return dict(id=j.id, title=j.title, company=j.company, location=j.location, job_url=j.job_url,
                    description=j.description, match_score=sc.match_score if sc else None,
                    compat_pct=sc.compat_pct if sc else None, compat_detail_pct=sc.compat_detail_pct if sc else None,
                    compat_missing=_json_list(sc.compat_missing) if sc else [], compat_capped=bool(sc and sc.compat_capped),
                    gaps=_json_list(sc.gaps) if sc else [])

def application_statuses(statuses=("applied", "closed"), db_path: str = DB_PATH) -> dict[str, str]:
    """{job_url: status} for jobs with an applications row in one of these statuses."""
    with session_scope(db_path) as s:
        rows = s.execute(select(Job.job_url, Application.status).join(Application, Application.job_id == Job.id)
                         .where(Application.status.in_(statuses), Job.job_url.is_not(None))).all()
        return {url: status for url, status in rows}


def applied_urls(db_path: str = DB_PATH) -> set[str]:
    """job_urls the bot already applied to or found closed: no documents are needed for these."""
    return set(application_statuses(db_path=db_path))

def get_candidates(min_score: float, days: float, include_opened: bool = False, url: str | None = None,
                   db_path: str = DB_PATH) -> list[dict]:
    """Scored jobs worth applying to that you haven't dealt with yet, best first."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(Job, JobScore.match_score).outerjoin(JobScore, _on_score(pid))
             .outerjoin(Application, Application.job_id == Job.id).where(Job.job_url.is_not(None)))
        if url:
            q = q.where(Job.job_url == url)
        else:
            fresh = Application.status.is_(None)
            q = q.where(JobScore.status == "scored", JobScore.match_score >= min_score,
                        JobScore.scored_at >= _since(days), Job.is_duplicate.is_(False),
                        or_(fresh, Application.status == "opened") if include_opened else fresh)
            q = q.order_by(JobScore.match_score.desc())
        rows = [dict(title=j.title, company=j.company, location=j.location, job_url=j.job_url,
                     description=j.description, match_score=score or 0.0, apply_url=j.apply_url, site=j.site)
                for j, score in s.execute(q).all()]        
        if url:
            return rows    # you named this job yourself with --url, so no skipping
        handled = handled_urls()
        return [r for r in rows if r["job_url"] not in handled]
        


def clear_missing_link_markers(markers, db_path: str = DB_PATH) -> int:
    """Forget "no link found" results so those jobs are searched for again."""
    with session_scope(db_path) as s:
        rows = s.scalars(select(Job).where(Job.apply_url.in_(list(markers)))).all()
        for j in rows:
            j.apply_url = None
        return len(rows)


# --------------------------------------------------------------------- rescore


def jobs_for_rescore(failed_only: bool = False, include_filtered: bool = False, url: str | None = None,
                     limit: int | None = None, include_unscored: bool = False, db_path: str = DB_PATH) -> list[dict]:
    """Jobs to score again, oldest first. include_unscored also returns jobs this profile has never seen
    (status 'new', match_score None), e.g. jobs another profile scraped. Jobs without a description are left out."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(Job, JobScore).outerjoin(JobScore, _on_score(pid))
             .where(Job.job_url.is_not(None), func.trim(Job.description) != "", Job.is_duplicate.is_(False)))
        if url:
            q = q.where(Job.job_url == url)
        else:
            statuses = ["scoring_failed"] if failed_only else ["scored", "scoring_failed"]
            if include_filtered and not failed_only:
                statuses.append("filtered")
            cond = JobScore.status.in_(statuses)
            if include_unscored and not failed_only:
                cond = or_(cond, JobScore.id.is_(None))
            q = q.where(cond)
        q = q.order_by(Job.id)
        if limit:
            q = q.limit(limit)
        return [dict(job_url=j.job_url, site=j.site, title=j.title, company=j.company, location=j.location,
                     description=j.description, status=sc.status if sc else "new",
                     match_score=sc.match_score if sc else None, model_score=sc.model_score if sc else None)
                for j, sc in s.execute(q).all()]


# ------------------------------------------------------------------ duplicates


def load_known(db_path: str = DB_PATH) -> list[dict]:
    """Jobs to compare new ones against: not duplicates, and scored by at least one profile."""
    with session_scope(db_path) as s:
        q = select(Job).where(Job.is_duplicate.is_(False),
                              exists().where(JobScore.job_id == Job.id, JobScore.status == "scored"))
        return [dict(job_url=j.job_url, title=j.title, company=j.company, location=j.location,
                     description=j.description) for j in s.scalars(q)]


def dedupe_candidates(db_path: str = DB_PATH) -> list[dict]:
    """Jobs for the duplicate sweep: best score across profiles, and any application status."""
    with session_scope(db_path) as s:
        q = (select(Job, func.max(JobScore.match_score), Application.status)
             .join(JobScore, JobScore.job_id == Job.id).outerjoin(Application, Application.job_id == Job.id)
             .where(JobScore.status == "scored", Job.is_duplicate.is_(False)).group_by(Job.id, Application.status))
        return [dict(id=j.id, job_url=j.job_url, title=j.title, company=j.company, location=j.location,
                     description=j.description, match_score=score, apply_url=j.apply_url, application=app)
                for j, score, app in s.execute(q).all()]


def mark_duplicates(pairs: list[tuple[int, int]], db_path: str = DB_PATH) -> None:
    """pairs: (duplicate job id, original job id). Scores are left as they were."""
    with session_scope(db_path) as s:
        for dup_id, original_id in pairs:
            job = s.get(Job, dup_id)
            job.is_duplicate, job.duplicate_of_id = True, original_id


# --------------------------------------------------------------------- summary


def status_counts(days: float | None = None, db_path: str = DB_PATH) -> dict:
    """{status: count} for the active profile, with duplicates under 'duplicate'. days limits to recent jobs."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(JobScore.status, func.count()).join(Job, Job.id == JobScore.job_id)
             .where(JobScore.profile_id == pid, Job.is_duplicate.is_(False)).group_by(JobScore.status))
        dq = select(func.count()).select_from(Job).where(Job.is_duplicate.is_(True))
        if days is not None:
            q = q.where(JobScore.scored_at >= _since(days))
            dq = dq.where(Job.scraped_at >= _since(days))
        out = {status: n for status, n in s.execute(q).all()}
        dupes = s.scalar(dq)
        if dupes:
            out["duplicate"] = dupes
        return out


def application_counts(db_path: str = DB_PATH) -> dict:
    with session_scope(db_path) as s:
        return {st: n for st, n in s.execute(select(Application.status, func.count()).group_by(Application.status)).all()}


def unfinished_applications(limit: int = 10, db_path: str = DB_PATH) -> list[dict]:
    with session_scope(db_path) as s:
        q = (select(Job.title, Job.company, Job.job_url).join(Application, Application.job_id == Job.id)
             .where(Application.status == "opened").order_by(Application.updated_at.desc()).limit(limit))
        return [dict(title=t, company=c, job_url=u) for t, c, u in s.execute(q).all()]


# ----------------------------------------------------------------------- stats


def stats_jobs(since: str | None = None, db_path: str = DB_PATH) -> list[dict]:
    """Jobs for the stats funnel: id, site, title, company, match_score, status, scraped_at, job_url.
    since = 'YYYY-MM-DD'. Duplicates appear with status 'duplicate' and score 0."""
    cut = datetime.strptime(since, "%Y-%m-%d") if since else None
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        q = (select(Job, JobScore.status, JobScore.match_score).outerjoin(JobScore, _on_score(pid)))
        if cut:
            q = q.where(Job.scraped_at >= cut)
        out = []
        for j, status, score in s.execute(q).all():
            if j.is_duplicate:
                status, score = "duplicate", 0.0
            elif status is None:
                continue   # never seen by this profile
            out.append(dict(id=j.id, site=j.site, title=j.title, company=j.company, match_score=score,
                            status=status, scraped_at=str(j.scraped_at), job_url=j.job_url))
        return out
