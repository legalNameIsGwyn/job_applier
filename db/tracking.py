"""Application tracking (replaces core/tracking.py). Same functions; rows come back as dicts."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from config.settings import DB_PATH
from db.models import Application, Job, JobScore, Tracking, TrackingEvent
from db.session import current_profile_id, session_scope

STAGES = ("applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn")
PROGRESS = ("applied", "screening", "interview", "offer")
ENDINGS = ("rejected", "ghosted", "withdrawn")
RESPONDED = ("screening", "interview", "offer", "rejected")


def today() -> str:
    return date.today().isoformat()


def parse_date(text: str | None) -> str | None:
    """Accepts 2026-11-09, 11/09/2026, 11/09, 'today', 'tomorrow', or '+7' (days from now)."""
    if not text:
        return None
    t = text.strip().lower()
    if t == "today":
        return today()
    if t == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    if t.startswith(("+", "-")) and t[1:].isdigit():
        return (date.today() + timedelta(days=int(t))).isoformat()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.strptime(t, "%m/%d").date().replace(year=date.today().year).isoformat()
    except ValueError:
        raise ValueError(f"can't read the date '{text}' (try 2026-11-09, 11/09, today, tomorrow or +7)")


def _row(t: Tracking) -> dict:
    return {c.name: getattr(t, c.name) for c in Tracking.__table__.columns}


def _best_score():
    return select(func.max(JobScore.match_score)).where(JobScore.job_id == Job.id).correlate(Job).scalar_subquery()


def log_applied(job_url: str, ats: str | None = None, folder: str | None = None, on_date: str | None = None,
                note: str | None = None, db_path: str = DB_PATH) -> bool:
    """Start tracking an application (stage 'applied'). False if it was already tracked."""
    on_date = on_date or today()
    with session_scope(db_path) as s:
        if s.scalar(select(Tracking.id).where(Tracking.job_url == job_url)):
            return False
        job = s.scalar(select(Job).where(Job.job_url == job_url))
        pid = current_profile_id(s)
        score = (s.scalar(select(JobScore.match_score).where(JobScore.job_id == job.id, JobScore.profile_id == pid))
                 if job else None)
        t = Tracking(job_url=job_url, job_id=job.id if job else None, profile_id=pid, stage="applied",
                     applied_on=on_date, updated_on=on_date, site=job.site if job else None, ats=ats,
                     folder=folder, score_at_apply=score)
        s.add(t)
        s.flush()
        s.add(TrackingEvent(tracking_id=t.id, stage="applied", on_date=on_date, note=note))
    return True


def set_stage(job_url: str, stage: str, on_date: str | None = None, note: str | None = None,
              db_path: str = DB_PATH) -> None:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of: {', '.join(STAGES)}")
    on_date = on_date or today()
    with session_scope(db_path) as s:
        t = s.scalar(select(Tracking).where(Tracking.job_url == job_url))
        if t is None:
            raise KeyError("that job isn't tracked yet (use: python -m tools.track add <job>)")
        t.stage, t.updated_on = stage, on_date
        s.add(TrackingEvent(tracking_id=t.id, stage=stage, on_date=on_date, note=note))


def update_fields(job_url: str, db_path: str = DB_PATH, **fields) -> None:
    """Set contact_name, contact_email, interview_on, follow_up_on or notes (None values are ignored)."""
    allowed = {"contact_name", "contact_email", "interview_on", "follow_up_on", "notes"}
    fields = {k: v for k, v in fields.items() if v is not None}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"can't set {', '.join(sorted(bad))}")
    if not fields:
        return
    with session_scope(db_path) as s:
        t = s.scalar(select(Tracking).where(Tracking.job_url == job_url))
        if t is None:
            raise KeyError("that job isn't tracked yet")
        for k, v in fields.items():
            setattr(t, k, v)


def append_note(job_url: str, text: str, db_path: str = DB_PATH) -> None:
    with session_scope(db_path) as s:
        old = s.scalar(select(Tracking.notes).where(Tracking.job_url == job_url)) or ""
    update_fields(job_url, db_path=db_path, notes=(old + "\n" if old else "") + f"[{today()}] {text}")


def job_label(job_url: str, db_path: str = DB_PATH) -> dict | None:
    """{id, title, company} for a job in the jobs table, or None."""
    with session_scope(db_path) as s:
        r = s.execute(select(Job.id, Job.title, Job.company).where(Job.job_url == job_url)).first()
        return {"id": r[0], "title": r[1], "company": r[2]} if r else None


def get_tracking(job_url: str, db_path: str = DB_PATH) -> dict | None:
    with session_scope(db_path) as s:
        t = s.scalar(select(Tracking).where(Tracking.job_url == job_url))
        return _row(t) if t else None


def resolve(ref: str, db_path: str = DB_PATH) -> tuple[str | None, list[dict]]:
    """Turn what you typed into a job_url. ref = the job's number, a URL, or part of the company / title.
    Returns (job_url, []) for exactly one match, else (None, matches)."""
    ref = ref.strip()
    cols = (Job.id, Job.job_url, Job.title, Job.company)
    with session_scope(db_path) as s:
        if ref.isdigit():
            rows = s.execute(select(*cols).where(Job.id == int(ref))).all()
        elif ref.lower().startswith("http"):
            rows = s.execute(select(*cols).where(Job.job_url == ref)).all()
            if not rows:
                return ref, []   # applied by hand to something never scraped: track it by URL
        else:
            like = f"%{ref.lower()}%"
            rows = s.execute(
                select(*cols, Tracking.id.label("tid"))
                .outerjoin(Tracking, Tracking.job_url == Job.job_url)
                .where(Job.job_url.is_not(None), or_(func.lower(Job.company).like(like), func.lower(Job.title).like(like)))
                .order_by(Tracking.id.is_(None), _best_score().desc()).limit(15)).all()
            tracked = [r for r in rows if r.tid is not None]
            if len(tracked) == 1:
                return tracked[0].job_url, []
        matches = [{"id": r[0], "job_url": r[1], "title": r[2], "company": r[3]} for r in rows]
        return (matches[0]["job_url"], []) if len(matches) == 1 else (None, matches)


def get_tracked(stage: str | None = None, stale_days: int | None = None, active_only: bool = False,
                since: str | None = None, db_path: str = DB_PATH) -> list[dict]:
    """Tracked applications with job details (job_id, title, company, location, match_score), newest first.
    since = 'YYYY-MM-DD' keeps only applications made on or after that day."""
    q = (select(Tracking, Job.id, Job.title, Job.company, Job.location, _best_score().label("match_score"))
         .outerjoin(Job, Job.job_url == Tracking.job_url))
    if stage:
        q = q.where(Tracking.stage == stage)
    if active_only:
        q = q.where(Tracking.stage.not_in(ENDINGS))
    if stale_days is not None:
        q = q.where(Tracking.stage == "applied",
                    Tracking.applied_on <= (date.today() - timedelta(days=stale_days)).isoformat())
    if since:
        q = q.where(Tracking.applied_on >= since)
    q = q.order_by(Tracking.updated_on.desc(), Tracking.applied_on.desc())
    with session_scope(db_path) as s:
        out = []
        for t, jid, title, company, location, score in s.execute(q).all():
            d = _row(t)
            d.update(job_id=jid, title=title, company=company, location=location, match_score=score)
            out.append(d)
        return out


def get_events(job_url: str, db_path: str = DB_PATH) -> list[dict]:
    with session_scope(db_path) as s:
        rows = s.execute(select(TrackingEvent.stage, TrackingEvent.on_date, TrackingEvent.note)
                         .join(Tracking, Tracking.id == TrackingEvent.tracking_id)
                         .where(Tracking.job_url == job_url).order_by(TrackingEvent.on_date, TrackingEvent.id)).all()
        return [{"stage": r[0], "on_date": r[1], "note": r[2]} for r in rows]


def all_events(db_path: str = DB_PATH) -> list[dict]:
    """Every stage change (for stats): job_url, stage, on_date, oldest first."""
    with session_scope(db_path) as s:
        rows = s.execute(select(Tracking.job_url, TrackingEvent.stage, TrackingEvent.on_date)
                         .join(Tracking, Tracking.id == TrackingEvent.tracking_id)
                         .order_by(TrackingEvent.on_date, TrackingEvent.id)).all()
        return [{"job_url": r[0], "stage": r[1], "on_date": r[2]} for r in rows]


def due_follow_ups(db_path: str = DB_PATH) -> list[dict]:
    """Active applications whose follow-up date is today or earlier."""
    q = (select(Tracking, Job.id, Job.title, Job.company).outerjoin(Job, Job.job_url == Tracking.job_url)
         .where(Tracking.follow_up_on.is_not(None), Tracking.follow_up_on <= today(),
                Tracking.stage.not_in(ENDINGS + ("offer",))).order_by(Tracking.follow_up_on))
    with session_scope(db_path) as s:
        out = []
        for t, jid, title, company in s.execute(q).all():
            d = _row(t)
            d.update(job_id=jid, title=title, company=company)
            out.append(d)
        return out


def _local_date(utc_dt: datetime | None) -> str:
    """Stored times are UTC; turn one into your local calendar day."""
    try:
        return utc_dt.replace(tzinfo=timezone.utc).astimezone().date().isoformat()
    except AttributeError:
        return today()


def sync_applied(db_path: str = DB_PATH) -> int:
    """Start tracking every job recorded as 'applied' that isn't tracked yet."""
    with session_scope(db_path) as s:
        rows = s.execute(
            select(Job.job_url, Application.ats, Application.updated_at)
            .join(Application, Application.job_id == Job.id)
            .where(Application.status == "applied", Job.job_url.is_not(None),
                   Job.job_url.not_in(select(Tracking.job_url)))).all()
    for url, ats, updated in rows:
        log_applied(url, ats=ats, on_date=_local_date(updated), db_path=db_path)
    return len(rows)