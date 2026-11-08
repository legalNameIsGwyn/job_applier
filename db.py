"""SQLite database operations for storing scraped and scored jobs."""

import json
import sqlite3

from config.settings import DB_PATH  # edit the location in config/settings.py

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    job_url TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    match_score REAL NOT NULL,
    matched_skills TEXT NOT NULL,
    gaps TEXT NOT NULL,
    is_retry INTEGER DEFAULT 0,
    status TEXT DEFAULT 'scraped',
    model_score REAL,
    keyword_score REAL,
    apply_url TEXT
);
"""

# match_score is the FINAL score (model score blended with the keyword score and
# calibrated to your hand ratings). model_score keeps the raw model output so the
# calibration can be re-fitted later; keyword_score is the deterministic keyword score.

# Your hand ratings. rating is NULL when you skipped a job (so it isn't offered again).
CREATE_RATINGS_SQL = """
CREATE TABLE IF NOT EXISTS ratings (
    job_url TEXT PRIMARY KEY,
    rating REAL,
    batch INTEGER NOT NULL,
    rated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

# One row per job you have started applying to (apply_jobs.py).
# status: applied | skipped | opened (form filled but you did not confirm sending)
CREATE_APPLICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    job_url TEXT PRIMARY KEY,
    apply_url TEXT,
    ats TEXT,
    status TEXT NOT NULL,
    note TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_site_score ON jobs(site, match_score DESC);
"""

# A unique index (rather than a column constraint) so it can also be added
# to a database that was created before job_url existed.
CREATE_UNIQUE_URL_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_url ON jobs(job_url);
"""

# match_score value stored when scoring failed, so failures are distinguishable
# from a real score of 0 (clearance / citizenship auto-reject).
FAILED_SCORE = -1.0


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a fresh database connection."""
    return sqlite3.connect(db_path)


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize the database, migrating older databases (adds any missing columns)."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        cursor.execute(CREATE_RATINGS_SQL)
        cursor.execute(CREATE_APPLICATIONS_SQL)

        columns = {row[1] for row in cursor.execute("PRAGMA table_info(jobs)")}
        if "job_url" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN job_url TEXT")
        if "apply_url" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT")
        if "keyword_score" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN keyword_score REAL")
        if "model_score" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN model_score REAL")
            # Every score saved before this column existed is a raw model score; freeze it.
            cursor.execute("UPDATE jobs SET model_score = match_score WHERE match_score >= 0")

        cursor.execute(CREATE_INDEX_SQL)
        cursor.execute(CREATE_UNIQUE_URL_INDEX_SQL)
        conn.commit()
    finally:
        conn.close()
    print(f"[DB] Initialized database at {db_path}")


def get_scored_urls(db_path: str = DB_PATH) -> set[str]:
    """URLs of jobs already scored or filtered (failed ones are retried)."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT job_url FROM jobs WHERE job_url IS NOT NULL AND match_score >= 0"
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def save_job(
    job: dict,
    score: dict,
    db_path: str = DB_PATH,
    status: str | None = None,
    model_score: float | None = None,
    keyword_score: float | None = None,
) -> None:
    """Insert (or update, if the URL already exists) one scored job.

    job:           site, job_url, title, company, location, description, apply_url (optional:
                   the employer's own application link, when the job board gives one)
    score:         match_score (the final score), matched_skills, gaps
    status:        defaults to "scored" or "scoring_failed"; main.py passes "filtered"
    model_score:   the raw model score (defaults to match_score unless scoring failed)
    keyword_score: the keyword-match score used in the blend
    """
    failed = score["match_score"] < 0
    status = status or ("scoring_failed" if failed else "scored")
    if model_score is None and not failed:
        model_score = score["match_score"]

    conn = get_db_connection(db_path)
    try:
        with conn:  # commits on success, rolls back on error
            conn.execute(
                """
                INSERT INTO jobs
                    (site, job_url, title, company, location, description,
                     match_score, matched_skills, gaps, status, model_score, keyword_score, apply_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_url) DO UPDATE SET
                    match_score = excluded.match_score,
                    matched_skills = excluded.matched_skills,
                    gaps = excluded.gaps,
                    status = excluded.status,
                    model_score = excluded.model_score,
                    keyword_score = excluded.keyword_score,
                    apply_url = COALESCE(excluded.apply_url, apply_url),
                    is_retry = 1
                """,
                (
                    job.get("site") or "unknown",
                    job.get("job_url") or None,
                    job.get("title") or "",
                    job.get("company") or "",
                    job.get("location") or "",
                    job.get("description") or "",
                    float(score["match_score"]),
                    json.dumps(list(score.get("matched_skills", []))),
                    json.dumps(list(score.get("gaps", []))),
                    status,
                    None if model_score is None else float(model_score),
                    None if keyword_score is None else float(keyword_score),
                    job.get("apply_url") or None,
                ),
            )
    finally:
        conn.close()


def set_apply_url(job_url: str, apply_url: str, db_path: str = DB_PATH) -> bool:
    """Store the employer's own application link for a job. False if the job isn't in the database."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute("UPDATE jobs SET apply_url = ? WHERE job_url = ?", (apply_url, job_url))
        return cur.rowcount > 0
    finally:
        conn.close()


def record_application(job_url: str, status: str, apply_url: str | None = None,
                       ats: str | None = None, note: str | None = None, db_path: str = DB_PATH) -> None:
    """Remember what happened with a job (applied / skipped / opened)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO applications (job_url, apply_url, ats, status, note)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(job_url) DO UPDATE SET
                       apply_url = COALESCE(excluded.apply_url, apply_url),
                       ats = COALESCE(excluded.ats, ats),
                       status = excluded.status,
                       note = COALESCE(excluded.note, note),
                       updated_at = CURRENT_TIMESTAMP""",
                (job_url, apply_url, ats, status, note),
            )
    finally:
        conn.close()
