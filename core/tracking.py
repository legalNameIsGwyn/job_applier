"""Application tracking: where each application stands after you apply.

Two small tables live in the same database as the jobs:

  tracking         one row per application: current stage, where/how you applied (site, applicant system,
                   which resume + letter folder, score at the time), contact, interview and follow-up dates, notes
  tracking_events  one row every time the stage changes (this is what the funnel and "days to hear back" use)

Stages (in order of progress):  applied -> screening -> interview -> offer
Endings:                          rejected, ghosted, withdrawn

apply_jobs.py logs "applied" for you when you answer `a`. Use track.py to update everything else.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config.settings import DB_PATH

STAGES = ("applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn")
PROGRESS = ("applied", "screening", "interview", "offer")      # the forward path
ENDINGS = ("rejected", "ghosted", "withdrawn")
RESPONDED = ("screening", "interview", "offer", "rejected")    # any of these means the employer answered

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS tracking (
    job_url TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    applied_on TEXT,
    updated_on TEXT,
    site TEXT,
    ats TEXT,
    folder TEXT,
    score_at_apply REAL,
    contact_name TEXT,
    contact_email TEXT,
    interview_on TEXT,
    follow_up_on TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL,
    stage TEXT NOT NULL,
    on_date TEXT NOT NULL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracking_events_url ON tracking_events(job_url);
"""


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
    try:   # month/day with no year: this year
        d = datetime.strptime(t, "%m/%d").date().replace(year=date.today().year)
        return d.isoformat()
    except ValueError:
        raise ValueError(f"can't read the date '{text}' (try 2026-11-09, 11/09, today, tomorrow or +7)")


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_SQL)
    return conn


def _event(conn, job_url, stage, on_date, note=None):
    conn.execute("INSERT INTO tracking_events (job_url, stage, on_date, note) VALUES (?, ?, ?, ?)",
                 (job_url, stage, on_date, note))


def _job(conn, job_url) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE job_url = ?", (job_url,)).fetchone()


def log_applied(job_url: str, ats: str | None = None, folder: str | None = None, on_date: str | None = None,
                note: str | None = None, db_path: str = DB_PATH) -> bool:
    """Start tracking an application (stage 'applied'). Returns False if it was already tracked."""
    on_date = on_date or today()
    conn = connect(db_path)
    try:
        with conn:
            if conn.execute("SELECT 1 FROM tracking WHERE job_url = ?", (job_url,)).fetchone():
                return False
            job = _job(conn, job_url)
            conn.execute(
                """INSERT INTO tracking (job_url, stage, applied_on, updated_on, site, ats, folder, score_at_apply)
                   VALUES (?, 'applied', ?, ?, ?, ?, ?, ?)""",
                (job_url, on_date, on_date, job["site"] if job else None, ats, folder,
                 job["match_score"] if job else None))
            _event(conn, job_url, "applied", on_date, note)
        return True
    finally:
        conn.close()


def set_stage(job_url: str, stage: str, on_date: str | None = None, note: str | None = None,
              db_path: str = DB_PATH) -> None:
    """Move an application to a new stage (it must already be tracked: use log_applied first)."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of: {', '.join(STAGES)}")
    on_date = on_date or today()
    conn = connect(db_path)
    try:
        with conn:
            if not conn.execute("SELECT 1 FROM tracking WHERE job_url = ?", (job_url,)).fetchone():
                raise KeyError("that job isn't tracked yet (use: python track.py add <job>)")
            conn.execute("UPDATE tracking SET stage = ?, updated_on = ? WHERE job_url = ?", (stage, on_date, job_url))
            _event(conn, job_url, stage, on_date, note)
    finally:
        conn.close()


def update_fields(job_url: str, db_path: str = DB_PATH, **fields) -> None:
    """Set contact_name, contact_email, interview_on, follow_up_on or notes (None values are ignored)."""
    allowed = {"contact_name", "contact_email", "interview_on", "follow_up_on", "notes"}
    fields = {k: v for k, v in fields.items() if v is not None}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"can't set {', '.join(sorted(bad))}")
    if not fields:
        return
    conn = connect(db_path)
    try:
        with conn:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE tracking SET {sets} WHERE job_url = ?", (*fields.values(), job_url))
    finally:
        conn.close()


def append_note(job_url: str, text: str, db_path: str = DB_PATH) -> None:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT notes FROM tracking WHERE job_url = ?", (job_url,)).fetchone()
    finally:
        conn.close()
    old = (row["notes"] or "") if row else ""
    update_fields(job_url, db_path=db_path, notes=(old + "\n" if old else "") + f"[{today()}] {text}")


def resolve(ref: str, db_path: str = DB_PATH) -> tuple[str | None, list[sqlite3.Row]]:
    """Turn what you typed into a job_url. ref can be the job's number (the # in lists), a URL, or part of
    the company / title. Returns (job_url, []) if exactly one job matches, else (None, matches)."""
    conn = connect(db_path)
    try:
        ref = ref.strip()
        if ref.isdigit():
            rows = conn.execute("SELECT id, job_url, title, company FROM jobs WHERE id = ?", (int(ref),)).fetchall()
        elif ref.lower().startswith("http"):
            rows = conn.execute("SELECT id, job_url, title, company FROM jobs WHERE job_url = ?", (ref,)).fetchall()
            if not rows:
                return ref, []   # not in jobs (applied by hand to something else); track it by URL
        else:
            like = f"%{ref.lower()}%"
            rows = conn.execute(
                """SELECT j.id, j.job_url, j.title, j.company FROM jobs j
                   LEFT JOIN tracking t ON t.job_url = j.job_url
                   WHERE j.job_url IS NOT NULL AND (lower(j.company) LIKE ? OR lower(j.title) LIKE ?)
                   ORDER BY (t.job_url IS NULL), j.match_score DESC LIMIT 15""", (like, like)).fetchall()
            tracked = [r for r in rows if conn.execute(
                "SELECT 1 FROM tracking WHERE job_url = ?", (r["job_url"],)).fetchone()]
            if len(tracked) == 1:        # prefer the one already tracked
                return tracked[0]["job_url"], []
        if len(rows) == 1:
            return rows[0]["job_url"], []
        return None, rows
    finally:
        conn.close()


def get_tracked(stage: str | None = None, stale_days: int | None = None, active_only: bool = False,
                db_path: str = DB_PATH) -> list[sqlite3.Row]:
    """Tracked applications joined with job details, newest first."""
    conn = connect(db_path)
    try:
        sql = ("SELECT t.*, j.id AS job_id, j.title, j.company, j.location, j.match_score "
               "FROM tracking t LEFT JOIN jobs j ON j.job_url = t.job_url WHERE 1=1")
        args: list = []
        if stage:
            sql += " AND t.stage = ?"
            args.append(stage)
        if active_only:
            sql += f" AND t.stage NOT IN ({','.join('?' * len(ENDINGS))})"
            args += list(ENDINGS)
        if stale_days is not None:
            sql += " AND t.stage = 'applied' AND t.applied_on <= ?"
            args.append((date.today() - timedelta(days=stale_days)).isoformat())
        sql += " ORDER BY t.updated_on DESC, t.applied_on DESC"
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def get_events(job_url: str, db_path: str = DB_PATH) -> list[sqlite3.Row]:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT * FROM tracking_events WHERE job_url = ? ORDER BY on_date, id",
                            (job_url,)).fetchall()
    finally:
        conn.close()


def due_follow_ups(db_path: str = DB_PATH) -> list[sqlite3.Row]:
    """Active applications whose follow-up date is today or earlier."""
    conn = connect(db_path)
    try:
        return conn.execute(
            """SELECT t.*, j.id AS job_id, j.title, j.company FROM tracking t
               LEFT JOIN jobs j ON j.job_url = t.job_url
               WHERE t.follow_up_on IS NOT NULL AND t.follow_up_on <= ?
                 AND t.stage NOT IN ('rejected', 'ghosted', 'withdrawn', 'offer')
               ORDER BY t.follow_up_on""", (today(),)).fetchall()
    finally:
        conn.close()


def _local_date(utc_text: str | None) -> str:
    """SQLite's CURRENT_TIMESTAMP is UTC; turn it into your local calendar day."""
    try:
        return (datetime.fromisoformat(utc_text).replace(tzinfo=timezone.utc).astimezone().date().isoformat())
    except (TypeError, ValueError):
        return today()


def sync_applied(db_path: str = DB_PATH) -> int:
    """Start tracking every job apply_jobs.py recorded as 'applied' that isn't tracked yet."""
    conn = connect(db_path)
    try:
        try:
            rows = conn.execute("SELECT job_url, ats, updated_at FROM applications WHERE status = 'applied'").fetchall()
        except sqlite3.OperationalError:
            return 0
        todo = [r for r in rows if not conn.execute("SELECT 1 FROM tracking WHERE job_url = ?", (r["job_url"],)).fetchone()]
    finally:
        conn.close()
    for r in todo:
        log_applied(r["job_url"], ats=r["ats"], on_date=_local_date(r["updated_at"]), db_path=db_path)
    return len(todo)
