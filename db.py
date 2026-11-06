"""SQLite database operations for storing scraped and scored jobs."""

import json
import sqlite3

DB_PATH = r"c:/Users/Gwyn/Desktop/Projects/job_scraper/jobs_db.sqlite"

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
    status TEXT DEFAULT 'scraped'
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
    """Initialize the database, migrating older databases that lack job_url."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)

        columns = {row[1] for row in cursor.execute("PRAGMA table_info(jobs)")}
        if "job_url" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN job_url TEXT")

        cursor.execute(CREATE_INDEX_SQL)
        cursor.execute(CREATE_UNIQUE_URL_INDEX_SQL)
        conn.commit()
    finally:
        conn.close()
    print(f"[DB] Initialized database at {db_path}")


def get_scored_urls(db_path: str = DB_PATH) -> set[str]:
    """URLs of jobs already scored successfully (failed ones are retried)."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT job_url FROM jobs WHERE job_url IS NOT NULL AND match_score >= 0"
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def save_job(job: dict, score: dict, db_path: str = DB_PATH) -> None:
    """Insert (or update, if the URL already exists) one scored job.

    job:   site, job_url, title, company, location, description
    score: match_score, matched_skills, gaps
    """
    failed = score["match_score"] < 0
    status = "scoring_failed" if failed else "scored"

    conn = get_db_connection(db_path)
    try:
        with conn:  # commits on success, rolls back on error
            conn.execute(
                """
                INSERT INTO jobs
                    (site, job_url, title, company, location, description,
                     match_score, matched_skills, gaps, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_url) DO UPDATE SET
                    match_score = excluded.match_score,
                    matched_skills = excluded.matched_skills,
                    gaps = excluded.gaps,
                    status = excluded.status,
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
                ),
            )
    finally:
        conn.close()