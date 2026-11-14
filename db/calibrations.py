"""Per-profile calibration history, in the database instead of calibration.json.
Dicts have the same keys the JSON file used, so core/calibration.py's maths doesn't change."""

from sqlalchemy import delete, select, update

from config.settings import CALIBRATION_HISTORY_LIMIT, DB_PATH, DEFAULT_MODEL_WEIGHT
from db.models import Calibration, Job, JobScore
from db.session import current_profile_id, session_scope

DEFAULT_CALIBRATION = {"fitted": False, "w_model": DEFAULT_MODEL_WEIGHT, "a": 1.0, "b": 0.0}
_FIELDS = ("fitted_at", "n", "latest_batch_only", "w_model", "a", "b", "trust", "w_fit", "a_fit", "b_fit",
           "spearman_model", "spearman_keyword", "spearman_final", "mae_model", "mae_final")


def _to_dict(c: Calibration) -> dict:
    d = {f: getattr(c, f) for f in _FIELDS}
    d["fitted"] = True
    return d


def load_calibration(db_path: str = DB_PATH) -> dict:
    """The active fit for the profile, or the default blend if it has none."""
    with session_scope(db_path) as s:
        c = s.scalar(select(Calibration).where(Calibration.profile_id == current_profile_id(s),
                                               Calibration.is_active.is_(True)))
        return _to_dict(c) if c else dict(DEFAULT_CALIBRATION)


def calibration_history(db_path: str = DB_PATH) -> list[dict]:
    with session_scope(db_path) as s:
        rows = s.scalars(select(Calibration).where(Calibration.profile_id == current_profile_id(s))
                         .order_by(Calibration.id))
        return [_to_dict(c) for c in rows]


def save_calibration(cal: dict, db_path: str = DB_PATH) -> None:
    """Add a fit to the history and make it the active one."""
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        s.execute(update(Calibration).where(Calibration.profile_id == pid).values(is_active=False))
        s.add(Calibration(profile_id=pid, is_active=True, **{f: cal.get(f) for f in _FIELDS}))
        s.flush()
        old = s.scalars(select(Calibration.id).where(Calibration.profile_id == pid)
                        .order_by(Calibration.id.desc()).offset(CALIBRATION_HISTORY_LIMIT)).all()
        if old:
            s.execute(delete(Calibration).where(Calibration.id.in_(old)))


def clear_calibration(db_path: str = DB_PATH) -> None:
    with session_scope(db_path) as s:
        s.execute(delete(Calibration).where(Calibration.profile_id == current_profile_id(s)))


def recalc_rows(db_path: str = DB_PATH) -> list[tuple]:
    """(job_score_id, title, description, model_score) for every usable scored job of the profile."""
    with session_scope(db_path) as s:
        model = JobScore.model_score
        q = (select(JobScore.id, Job.title, Job.description, model).join(Job, Job.id == JobScore.job_id)
             .where(JobScore.profile_id == current_profile_id(s), JobScore.status == "scored", model > 0,
                    Job.is_duplicate.is_(False), ~JobScore.gaps.like("%auto-rejected%")))
        return [tuple(r) for r in s.execute(q).all()]


def update_final_scores(rows: list[tuple[int, float, float]], db_path: str = DB_PATH) -> None:
    """rows: (job_score_id, final_score, keyword_score)."""
    with session_scope(db_path) as s:
        for score_id, final, kw in rows:
            s.execute(update(JobScore).where(JobScore.id == score_id).values(match_score=final, keyword_score=kw))