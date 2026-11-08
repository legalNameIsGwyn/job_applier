"""Show the top or bottom N scored jobs from the database.

Usage (from the project folder):
    python show_jobs.py                  # top 10
    python show_jobs.py -n 5 --bottom    # 5 lowest scores
    python show_jobs.py -n 20 --min-score 6 --days 3
    python show_jobs.py --failed         # jobs whose scoring failed
    python show_jobs.py -n 3 --full      # also print the job description

Or from code:
    from show_jobs import show_jobs
    show_jobs(10, "top")
"""

import argparse
import json
import sqlite3
import textwrap

from config.settings import SHOW_DEFAULT_COUNT
from db import DB_PATH


def get_jobs(
    n: int = 10,
    order: str = "top",
    min_score: float | None = None,
    max_score: float | None = None,
    days: int | None = None,
    include_zero: bool = True,
    failed_only: bool = False,
    db_path: str = DB_PATH,
) -> list[dict]:
    """Return the top or bottom N jobs as dicts.

    order:        "top" (highest score first) or "bottom" (lowest first)
    min_score / max_score: only jobs with a score in this range
    days:         only jobs scraped in the last N days
    include_zero: set False to hide the auto-rejected jobs (clearance / citizenship)
    failed_only:  show only jobs whose scoring failed (stored as -1)
    """
    if order not in ("top", "bottom"):
        raise ValueError("order must be 'top' or 'bottom'")

    where, params = [], []
    if failed_only:
        where.append("match_score < 0")
    else:
        where.append("match_score >= 0")  # failed jobs are hidden unless asked for
        if not include_zero:
            where.append("match_score > 0")
    if min_score is not None:
        where.append("match_score >= ?")
        params.append(min_score)
    if max_score is not None:
        where.append("match_score <= ?")
        params.append(max_score)
    if days is not None:
        where.append("scraped_at >= datetime('now', ?)")
        params.append(f"-{int(days)} days")

    direction = "DESC" if order == "top" else "ASC"
    sql = f"""
        SELECT title, company, location, job_url, match_score,
               matched_skills, gaps, description, scraped_at
        FROM jobs
        WHERE {' AND '.join(where)}
        ORDER BY match_score {direction}, scraped_at DESC
        LIMIT ?
    """
    params.append(int(n))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()

    for r in rows:
        for key in ("matched_skills", "gaps"):
            try:
                r[key] = json.loads(r[key])
            except (TypeError, ValueError):
                r[key] = [r[key]] if r[key] else []
    return rows


def show_jobs(n: int = 10, order: str = "top", full: bool = False, **filters) -> list[dict]:
    """Print the top or bottom N jobs, and return them. See get_jobs for filters."""
    jobs = get_jobs(n, order, **filters)
    label = "Top" if order == "top" else "Bottom"

    if not jobs:
        print("No jobs match those filters.")
        return jobs

    print(f"\n{label} {len(jobs)} jobs\n" + "=" * 60)
    for i, j in enumerate(jobs, start=1):
        print(f"\n{i}. [{j['match_score']:g}/10] {j['title']} - {j['company']}")
        print(f"   {j['location']}  (scraped {j['scraped_at']})")
        print(f"   {j['job_url']}")
        if j["matched_skills"]:
            print(f"   Matched: {', '.join(j['matched_skills'])}")
        if j["gaps"]:
            print(f"   Gaps:    {', '.join(j['gaps'])}")
        if full and j["description"]:
            print("   Description:")
            print(textwrap.indent(textwrap.fill(j["description"][:1500], 90), "     "))
    print()
    return jobs


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Show top or bottom scored jobs.")
    p.add_argument("-n", type=int, default=SHOW_DEFAULT_COUNT, help=f"how many jobs to show (default {SHOW_DEFAULT_COUNT})")
    p.add_argument("--bottom", action="store_true", help="show the lowest scores instead of the highest")
    p.add_argument("--min-score", type=float, help="only jobs scoring at least this")
    p.add_argument("--max-score", type=float, help="only jobs scoring at most this")
    p.add_argument("--days", type=int, help="only jobs scraped in the last N days")
    p.add_argument("--hide-zero", action="store_true", help="hide auto-rejected (score 0) jobs")
    p.add_argument("--failed", action="store_true", help="show only jobs whose scoring failed")
    p.add_argument("--full", action="store_true", help="include the job description")
    args = p.parse_args()

    show_jobs(
        args.n,
        "bottom" if args.bottom else "top",
        full=args.full,
        min_score=args.min_score,
        max_score=args.max_score,
        days=args.days,
        include_zero=not args.hide_zero,
        failed_only=args.failed,
    )
