"""Score calibration: blend the model's score with a keyword score, tuned to your hand ratings.

final score = a * (w * model_score + (1 - w) * keyword_score) + b      (clipped to 0-10)

Before you have rated any jobs the defaults are w = DEFAULT_MODEL_WEIGHT, a = 1, b = 0
(config/settings.py). Each time you hand-rate jobs with rating.py, w, a and b are fitted to
ALL your ratings so far, and the new fit is ADDED to the history in calibration.json; the
latest one is the one in use. Past fits are kept, so you can watch the agreement improve.

A model score of 0 always stays 0 (clearance, citizenship, green card). It is a hard
disqualifier, not a low match, so it is never blended up.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from documents.application_maker import matched_skills, missing_terms
from config.settings import (
    CALIBRATION_FILE, CALIBRATION_HISTORY_LIMIT, DEFAULT_MODEL_WEIGHT, FULL_TRUST_RATINGS, MIN_RATINGS,
)
from core.db import DB_PATH, get_db_connection
from core.scorer import load_resume

DEFAULT_CALIBRATION = {"fitted": False, "w_model": DEFAULT_MODEL_WEIGHT, "a": 1.0, "b": 0.0}


# ------------------------------------------------------------------ keyword score


def keyword_score(title: str, description: str, resume: dict | None = None) -> float:
    """0-10 score from how many of your real skills the posting mentions.

    h = skills of yours the posting mentions, m = common terms it asks for that you
    don't have. score = 10 * h / (h + m + 2); the +2 stops a posting with one or two
    keywords from scoring extremely high or low.
    """
    resume = resume or load_resume()
    text = f"{title}\n{description or ''}"
    h = len(matched_skills(text, resume.get("skills", [])))
    m = len(missing_terms(text, resume))
    return round(10 * h / (h + m + 2), 1)


# ------------------------------------------------------------------- calibration


def _read_file() -> dict:
    """The calibration file as {"active": {...}, "history": [...]}; {} if missing or unreadable."""
    try:
        data = json.loads(Path(CALIBRATION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if "history" not in data and data.get("fitted"):  # a single fit saved by an earlier version
        data = {"active": data, "history": [data]}
    return data


def load_calibration() -> dict:
    """The calibration in use: your latest fit, or the default blend if you haven't rated yet."""
    active = _read_file().get("active")
    return active if active and active.get("fitted") else dict(DEFAULT_CALIBRATION)


def calibration_history() -> list[dict]:
    """Every fit so far, oldest first."""
    return _read_file().get("history", [])


def save_calibration(cal: dict) -> None:
    """Add a new fit to the history and make it the active one. Earlier fits are kept."""
    history = (calibration_history() + [cal])[-CALIBRATION_HISTORY_LIMIT:]
    Path(CALIBRATION_FILE).write_text(json.dumps({"active": cal, "history": history}, indent=2), encoding="utf-8")


def clear_calibration() -> None:
    """Forget every fit (used by `rating.py --reset`)."""
    Path(CALIBRATION_FILE).unlink(missing_ok=True)


def blend(model_score: float, kw_score: float, cal: dict | None = None) -> float:
    """Final 0-10 score from the raw model score and the keyword score."""
    if model_score is None or model_score <= 0:
        return 0.0
    cal = cal or load_calibration()
    z = cal["w_model"] * model_score + (1 - cal["w_model"]) * (kw_score or 0.0)
    return round(float(np.clip(cal["a"] * z + cal["b"], 0.0, 10.0)), 1)


# ----------------------------------------------------------------------- fitting


def spearman(x, y) -> float:
    """Rank correlation: 1 = same ordering, 0 = unrelated, -1 = reversed. NaN if undefined."""
    rx = pd.Series(x, dtype=float).rank()
    ry = pd.Series(y, dtype=float).rank()
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def _clean(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 3)


def fit_calibration(rows: list[tuple[float, float, float]], latest_batch_only: bool = False) -> dict | None:
    """Fit w, a, b to hand ratings. rows: (model_score, keyword_score, your_rating).

    Tries w = 0, 0.1 ... 1 and keeps the one whose blended scores rank the jobs most
    like you did (ties go to the lower average error, then to trusting the model more).
    Then fits a straight line so the blended scores land on your 0-10 scale. Returns
    None if there is too little data or the scores don't track your ratings at all.
    """
    if len(rows) < MIN_RATINGS:
        return None
    m, k, r = (np.array(col, dtype=float) for col in zip(*rows))

    best = None
    for w in np.round(np.arange(0, 1.01, 0.1), 1):
        z = w * m + (1 - w) * k
        if np.std(z) == 0:
            continue
        rho = spearman(z, r)
        if np.isnan(rho):
            continue
        a, b = np.polyfit(z, r, 1)
        if a <= 0:  # ordering runs against your ratings; a line through it would be nonsense
            continue
        mae = float(np.mean(np.abs(np.clip(a * z + b, 0, 10) - r)))
        key = (round(rho, 3), -mae, float(w))
        if best is None or key > best[0]:
            best = (key, float(w), float(a), float(b), mae)

    if best is None or best[0][0] <= 0:
        return None
    _, w_fit, a_fit, b_fit, _ = best
    # With few ratings the fit is noisy, so only part of the way from the defaults is used.
    # It reaches the full fit at FULL_TRUST_RATINGS ratings.
    trust = min(1.0, len(rows) / FULL_TRUST_RATINGS)
    w = round(DEFAULT_MODEL_WEIGHT + trust * (w_fit - DEFAULT_MODEL_WEIGHT), 2)
    a = 1.0 + trust * (a_fit - 1.0)
    b = trust * b_fit
    z = w * m + (1 - w) * k
    mae = float(np.mean(np.abs(np.clip(a * z + b, 0, 10) - r)))
    return {
        "fitted": True,
        "fitted_at": datetime.now().isoformat(timespec="seconds"),
        "n": len(rows),
        "latest_batch_only": latest_batch_only,
        "w_model": w,
        "a": round(a, 4),
        "b": round(b, 4),
        "trust": round(trust, 2),
        "w_fit": w_fit,
        "a_fit": round(a_fit, 4),
        "b_fit": round(b_fit, 4),
        "spearman_model": _clean(spearman(m, r)),
        "spearman_keyword": _clean(spearman(k, r)),
        "spearman_final": _clean(spearman(z, r)),
        "mae_model": round(float(np.mean(np.abs(m - r))), 2),
        "mae_final": round(mae, 2),
    }


def apply_calibration_to_db(db_path: str = DB_PATH, cal: dict | None = None) -> int:
    """Recompute match_score for every scored job with the given calibration.

    Safe to run repeatedly: it always starts from the raw model_score, never from a
    previously blended match_score. Filtered, failed and zero-scored jobs are untouched.
    Returns how many jobs were updated.
    """
    cal = cal or load_calibration()
    resume = load_resume()
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT id, title, description, COALESCE(model_score, match_score)
               FROM jobs
               WHERE status = 'scored' AND COALESCE(model_score, match_score) > 0
                 AND gaps NOT LIKE '%auto-rejected%'"""
        ).fetchall()
        with conn:
            for job_id, title, description, model in rows:
                kw = keyword_score(title, description, resume)
                conn.execute(
                    "UPDATE jobs SET match_score = ?, model_score = ?, keyword_score = ? WHERE id = ?",
                    (blend(model, kw, cal), model, kw, job_id),
                )
    finally:
        conn.close()
    return len(rows)
