"""Show the top or bottom N scored jobs for a profile.

Usage (from the project folder):
    python -m tools.show_jobs                  # top 10
    python -m tools.show_jobs -n 5 --bottom    # 5 lowest scores
    python -m tools.show_jobs -n 20 --min-score 6 --days 3
    python -m tools.show_jobs --failed         # jobs whose scoring failed
    python -m tools.show_jobs -n 3 --full      # also print the job description
    python -m tools.show_jobs --profile it_support

Or from code:
    from tools.show_jobs import show_jobs
    show_jobs(10, "top")

The query itself (get_jobs) lives in db/queries.py; this file only prints.
"""

import argparse
import textwrap

from config.settings import SHOW_DEFAULT_COUNT
from db.queries import get_jobs
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments


def show_jobs(n: int = 10, order: str = "top", full: bool = False, **filters) -> list[dict]:
    """Print the top or bottom N jobs, and return them. See db.queries.get_jobs for the filters."""
    jobs = get_jobs(n, order, **filters)
    label = "Top" if order == "top" else "Bottom"

    if not jobs:
        print("No jobs match those filters.")
        return jobs

    print(f"\n{label} {len(jobs)} jobs (profile: {active_profile_name()})\n" + "=" * 60)
    for i, j in enumerate(jobs, start=1):
        compat = f"  compat {j['compat_pct']:g}%" if j.get("compat_pct") is not None else ""
        print(f"\n{i}. #{j['id']} [{j['match_score']:g}/10]{compat} {j['title']} - {j['company']}")
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
    p.add_argument("--days", type=int, help="only jobs scored in the last N days")
    p.add_argument("--hide-zero", action="store_true", help="hide auto-rejected (score 0) jobs")
    p.add_argument("--failed", action="store_true", help="show only jobs whose scoring failed")
    p.add_argument("--full", action="store_true", help="include the job description")
    add_profile_arguments(p)
    args = p.parse_args()
    apply_profile_arguments(args)

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