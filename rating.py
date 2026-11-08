"""Hand-rate a batch of jobs to check, and tune, how the scores are computed.

From the project folder:
    python rating.py                  # rate 20 jobs you haven't rated yet
    python rating.py -n 10            # a smaller batch
    python rating.py --latest-only    # tune using ONLY this batch's ratings
    python rating.py --report         # show the current calibration, no rating
    python rating.py --reset          # start over: delete all ratings and fits (asks first)

Or from code:
    from rating import rate_jobs
    rate_jobs()                       # 20 new jobs

Every call:
  1. Picks jobs you have never rated, spread across the whole score range (so the
     tuning sees good, middling and poor matches), in shuffled order. The model's
     score is hidden while you rate, so it can't sway you.
  2. Saves each rating immediately, so quitting part-way loses nothing.
  3. ADDS your new ratings to all the earlier ones, re-fits the score calibration to
     the whole pool, and rewrites the scores of all jobs in the database with it.
     The new fit is appended to the history in calibration.json; earlier fits are kept.
     (--latest-only, or FIT_ON_ALL_RATINGS = False in config/settings.py, fits on just
     the newest batch instead.) --reset is the only way to start from nothing.
"""

import argparse
import json
import random
import sqlite3
import textwrap

from calibration import (
    CALIBRATION_FILE, DEFAULT_CALIBRATION, MIN_RATINGS, apply_calibration_to_db, calibration_history,
    clear_calibration, fit_calibration, keyword_score, load_calibration, save_calibration,
)
from config.settings import (
    FIT_ON_ALL_RATINGS, RATING_BATCH_SIZE, RATING_DESC_CHARS, RATING_DESCRIPTION, RATING_SHOW_MODEL_NOTES,
    RATING_SUMMARY_BULLETS,
)
from db import DB_PATH, init_db
from job_info import salary_from_text, special_notes, summary_points

DEFAULT_BATCH = RATING_BATCH_SIZE  # all of these are set in config/settings.py
DESC_CHARS = RATING_DESC_CHARS

INSTRUCTIONS = """
Rate each job from 0 to 10 for how well it fits YOU:
    0 = I would never apply / not eligible     5 = maybe     10 = ideal
Type d to read the full posting, s to skip a job (it won't be offered again), q to stop and save.
Scores are hidden so they don't influence you.
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def eligible_jobs(db_path: str = DB_PATH) -> list[dict]:
    """Scored jobs you haven't rated or skipped, with a description to judge them by."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT j.job_url, j.title, j.company, j.location, j.description,
                      j.matched_skills, j.gaps, j.salary,
                      COALESCE(j.model_score, j.match_score) AS model_score
               FROM jobs j LEFT JOIN ratings r ON r.job_url = j.job_url
               WHERE r.job_url IS NULL AND j.job_url IS NOT NULL
                 AND j.status = 'scored'
                 AND COALESCE(j.model_score, j.match_score) > 0
                 AND j.gaps NOT LIKE '%auto-rejected%'
                 AND TRIM(j.description) <> ''"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def pick_batch(jobs: list[dict], n: int, rng: random.Random) -> list[dict]:
    """n jobs spread evenly across the model-score range (one random job per slice), shuffled."""
    if len(jobs) <= n:
        batch = list(jobs)
    else:
        jobs = sorted(jobs, key=lambda j: j["model_score"])
        batch = []
        for i in range(n):
            lo, hi = i * len(jobs) // n, (i + 1) * len(jobs) // n
            batch.append(jobs[rng.randrange(lo, hi)])
    rng.shuffle(batch)
    return batch


def _json_list(value) -> list[str]:
    try:
        items = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(i) for i in items] if isinstance(items, list) else []


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, 100, initial_indent=indent, subsequent_indent=indent + "  ")


def _show_job(i: int, total: int, job: dict, show) -> None:
    """One job's card: pay, notes, (optionally) the model's skills and gaps, and the posting."""
    description = job["description"] or ""
    show("\n" + "=" * 72)
    show(f"[{i}/{total}] {job['title']}")
    show(f"{job['company']}  |  {job['location']}")
    show(job["job_url"])
    show("-" * 72)

    salary = job.get("salary")
    if salary:
        show(f"Salary: {salary}")
    else:
        quoted = salary_from_text(description)
        show(f"Salary: {quoted} (quoted in the posting)" if quoted else "Salary: not listed")

    notes = special_notes(job["title"], job["location"], description)
    show("Special notes: " + ("; ".join(notes) if notes else "none"))

    if RATING_SHOW_MODEL_NOTES:
        skills, gaps = _json_list(job.get("matched_skills")), _json_list(job.get("gaps"))
        show("Matching skills (model): " + (", ".join(skills) if skills else "none listed"))
        show("Gaps (model): " + ("; ".join(gaps) if gaps else "none listed"))

    show("-" * 72)
    flat = " ".join(description.split())
    if RATING_DESCRIPTION == "full":
        show(textwrap.fill(flat, 100))
        return
    if RATING_DESCRIPTION == "excerpt":
        show(textwrap.fill(flat[:RATING_DESC_CHARS], 100) + (" ..." if len(flat) > RATING_DESC_CHARS else ""))
        return
    points = summary_points(description, RATING_SUMMARY_BULLETS)
    if not points:
        show(textwrap.fill(flat[:RATING_DESC_CHARS], 100) + (" ..." if len(flat) > RATING_DESC_CHARS else ""))
    for section, bullets in points.items():
        show(f"{section}:")
        for bullet in bullets:
            show(_wrap("- " + bullet))
    show("(d = read the full posting)")


def _show_full(job: dict, show) -> None:
    show("\n" + "-" * 72)
    show(textwrap.fill(" ".join((job["description"] or "").split()), 100))
    show("-" * 72)


def _ask_rating(ask, on_detail=None) -> float | None | str:
    """Returns a rating (0-10), None for skip, or 'quit'. d shows the full posting first."""
    while True:
        raw = ask("Your rating 0-10 (d = full posting, s = skip, q = quit): ").strip().lower()
        if raw in ("q", "quit"):
            return "quit"
        if raw in ("s", "skip"):
            return None
        if raw in ("d", "desc", "full") and on_detail:
            on_detail()
            continue
        try:
            value = float(raw)
        except ValueError:
            print("  Enter a number from 0 to 10, or d / s / q.")
            continue
        if 0 <= value <= 10:
            return value
        print("  Enter a number from 0 to 10, or d / s / q.")


def _strength(rho) -> str:
    if rho is None:
        return "n/a"
    return "strong" if rho >= 0.6 else "moderate" if rho >= 0.3 else "weak" if rho > 0 else "none"


def _fit_rows(db_path: str, batch: int | None = None) -> list[dict]:
    query = """SELECT COALESCE(j.model_score, j.match_score) AS model, j.keyword_score AS kw,
                      r.rating AS rating, j.title, j.company, j.description
               FROM ratings r JOIN jobs j ON j.job_url = r.job_url
               WHERE r.rating IS NOT NULL AND COALESCE(j.model_score, j.match_score) > 0"""
    params: tuple = ()
    if batch is not None:
        query += " AND r.batch = ?"
        params = (batch,)
    conn = _connect(db_path)
    try:
        rows = [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()
    for r in rows:
        if r["kw"] is None:
            r["kw"] = keyword_score(r["title"], r["description"])
    return rows


def recalibrate(batch: int | None = None, db_path: str = DB_PATH, show=print) -> dict | None:
    """Fit a new calibration to the saved ratings, add it to the history, rescore the database.

    batch=None uses every rating so far; a batch number uses only that batch.
    """
    rows = _fit_rows(db_path, batch)
    if len(rows) < MIN_RATINGS:
        show(f"\nYou have {len(rows)} usable rating(s); at least {MIN_RATINGS} are needed to tune the "
             "scores. Your ratings are saved. Run again to rate more.")
        return None

    cal = fit_calibration([(r["model"], r["kw"], r["rating"]) for r in rows], latest_batch_only=batch is not None)
    if cal is None:
        show("\nNone of the scores track your ratings well enough to tune them, so the calibration was "
             "left unchanged. This is usually a sign the model's prompt needs work, or that more "
             "ratings are needed. Your ratings are saved.")
        return None

    previous = load_calibration()
    save_calibration(cal)  # appended to the history; earlier fits are kept
    updated = apply_calibration_to_db(db_path, cal)
    _print_report(cal, rows, previous, calibration_history(), updated, show)
    return cal


def _print_report(cal: dict, rows: list[dict], previous: dict, history: list[dict], updated: int, show) -> None:
    show("\n" + "=" * 72)
    show(f"CALIBRATION RESULT  ({cal['n']} ratings"
         f"{', latest batch only' if cal['latest_batch_only'] else ', all batches'})")
    show("How well each score ranks jobs like you did (1.0 = identical, 0 = unrelated):")
    show(f"  model alone     : {cal['spearman_model']}  ({_strength(cal['spearman_model'])})")
    show(f"  keywords alone  : {cal['spearman_keyword']}  ({_strength(cal['spearman_keyword'])})")
    show(f"  final (blended) : {cal['spearman_final']}  ({_strength(cal['spearman_final'])})   <- now used")
    show(f"Average distance from your ratings: model {cal['mae_model']} points -> final {cal['mae_final']} points")
    show(f"Blend: {round(cal['w_model'] * 100)}% model / {round((1 - cal['w_model']) * 100)}% keywords")
    if previous.get("fitted"):
        show(f"(Added as fit #{len(history)}. The previous fit, from {previous['fitted_at']} on "
             f"{previous['n']} ratings, stays in the history.)")
    else:
        show("(First fit. It takes over from the default blend.)")
    trend = [h["spearman_final"] for h in history if h.get("spearman_final") is not None]
    if len(trend) > 1:
        show("Agreement with you, fit by fit: " + " -> ".join(f"{t:g}" for t in trend[-8:]))
    show(f"Rescored {updated} jobs in the database with it.")

    worst = sorted(rows, key=lambda r: abs(r["model"] - r["rating"]), reverse=True)[:5]
    show("\nWhere the model disagreed with you most:")
    for r in worst:
        show(f"  model {r['model']:>4g}  vs  you {r['rating']:>4g}   {r['title'][:40]} - {r['company'][:22]}")
    if cal["n"] < 30:
        show(f"\nNote: {cal['n']} ratings is a rough guide. The result firms up as you rate more "
             "(around 50+ is much steadier).")
    show("=" * 72)


def rate_jobs(
    n: int | None = None,
    latest_batch_only: bool | None = None,
    db_path: str = DB_PATH,
    ask=input,
    show=print,
    seed: int | None = None,
) -> dict | None:
    """Present n new jobs to hand-rate, then re-tune the scores on your ratings.

    n:                 jobs to show (default RATING_BATCH_SIZE in config/settings.py)
    latest_batch_only: True = fit on this batch only; False = fit on every rating you have
                       ever made; None (default) = follow FIT_ON_ALL_RATINGS in settings.

    Returns the new calibration (also saved to calibration.json), or None if there
    weren't enough ratings or nothing to tune. `ask`, `show` and `seed` exist so the
    function can be tested without a keyboard.
    """
    n = n or DEFAULT_BATCH
    if latest_batch_only is None:
        latest_batch_only = not FIT_ON_ALL_RATINGS
    init_db(db_path)
    jobs = eligible_jobs(db_path)
    if not jobs:
        show("\nNo unrated jobs to show. Run main.py to score more, then try again.")
        return None

    batch = pick_batch(jobs, n, random.Random(seed))
    if len(batch) < n:
        show(f"\nOnly {len(batch)} unrated jobs are available (asked for {n}). "
             "Run main.py to score more for the next round.")

    conn = _connect(db_path)
    try:
        batch_id = conn.execute("SELECT COALESCE(MAX(batch), 0) + 1 FROM ratings").fetchone()[0]
    finally:
        conn.close()

    show(INSTRUCTIONS)
    rated = 0
    for i, job in enumerate(batch, start=1):
        _show_job(i, len(batch), job, show)
        answer = _ask_rating(ask, lambda job=job: _show_full(job, show))
        if answer == "quit":
            break
        conn = _connect(db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO ratings (job_url, rating, batch) VALUES (?, ?, ?)",
                    (job["job_url"], answer, batch_id),
                )
        finally:
            conn.close()
        rated += answer is not None

    show(f"\nSaved {rated} rating(s) in batch {batch_id}.")
    return recalibrate(batch_id if latest_batch_only else None, db_path, show)


def reset_ratings(db_path: str = DB_PATH, ask=input, show=print) -> bool:
    """Delete every rating and the calibration history, and put all scores back on the default blend.

    This is the only thing that starts the tuning over; normal runs only ever add to it.
    """
    init_db(db_path)
    conn = _connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
    finally:
        conn.close()
    show(f"This deletes all {count} ratings (including skipped jobs) and the calibration history, "
         "and puts every job's score back on the default blend.")
    if ask("Type RESET to continue: ").strip() != "RESET":
        show("Cancelled. Nothing was changed.")
        return False
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM ratings")
    finally:
        conn.close()
    clear_calibration()
    updated = apply_calibration_to_db(db_path, dict(DEFAULT_CALIBRATION))
    show(f"Done. Rescored {updated} jobs with the default blend. You can start rating from scratch.")
    return True


def show_calibration(show=print) -> None:
    """Print the calibration currently in use."""
    cal = load_calibration()
    if not cal.get("fitted"):
        show(f"No calibration fitted yet (using the default 70% model / 30% keywords). "
             f"Rate at least {MIN_RATINGS} jobs with:  python rating.py")
        return
    show(f"Calibration from {cal['fitted_at']} ({cal['n']} ratings"
         f"{', latest batch only' if cal['latest_batch_only'] else ''}), stored in {CALIBRATION_FILE.name}")
    show(f"  Blend: {round(cal['w_model'] * 100)}% model / {round((1 - cal['w_model']) * 100)}% keywords, "
         f"then x{cal['a']} + {cal['b']}")
    show(f"  Agreement with your ratings: model {cal['spearman_model']} ({_strength(cal['spearman_model'])}), "
         f"keywords {cal['spearman_keyword']} ({_strength(cal['spearman_keyword'])}), "
         f"final {cal['spearman_final']} ({_strength(cal['spearman_final'])})")
    show(f"  Average distance from your ratings: model {cal['mae_model']} -> final {cal['mae_final']} points")
    history = calibration_history()
    trend = [h["spearman_final"] for h in history if h.get("spearman_final") is not None]
    if len(trend) > 1:
        show(f"  {len(history)} fits so far; agreement with you, fit by fit: " + " -> ".join(f"{t:g}" for t in trend[-8:]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Hand-rate jobs to check and tune the scores.")
    p.add_argument("-n", type=int, default=DEFAULT_BATCH, help=f"jobs per batch (default {DEFAULT_BATCH})")
    p.add_argument("--latest-only", action="store_true", help="tune using only this batch's ratings")
    p.add_argument("--all-ratings", action="store_true", help="tune using every rating (overrides settings)")
    p.add_argument("--report", action="store_true", help="show the current calibration and exit")
    p.add_argument("--reset", action="store_true", help="delete all ratings and fits and start over (asks first)")
    args = p.parse_args()

    if args.reset:
        reset_ratings()
    elif args.report:
        show_calibration()
    else:
        latest = True if args.latest_only else (False if args.all_ratings else None)
        rate_jobs(args.n, latest_batch_only=latest)