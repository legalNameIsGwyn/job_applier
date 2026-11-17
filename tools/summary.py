"""A summary of what the pipeline found, and what is waiting for you.

    python -m tools.summary                  # last 24 hours, printed in the terminal
    python -m tools.summary --days 7         # last week
    python -m tools.summary --html           # also save reports\\summary_<date>.html and open it
    python -m tools.summary --top 15 --min-score 6
    python -m tools.summary --profile it_support

Scores, ratings and "ready to apply" are for the active profile; applications and follow-ups cover
everything you have tracked. main.py prints this at the end of every run (SUMMARY_AFTER_RUN in
config/settings.py). Nothing here scrapes, scores or opens a browser; it only reads the database.
"""

import argparse
import html
import webbrowser
from datetime import datetime
from pathlib import Path

import config.settings as _settings
import db.tracking as tracking
from config.settings import DB_PATH
from db import ratings as R
from db.queries import application_counts, get_candidates, get_jobs, status_counts, unfinished_applications
from core.compat import compat_label
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments

SUMMARY_DAYS = getattr(_settings, "SUMMARY_DAYS", 1)            # how far back "new" reaches
SUMMARY_TOP = getattr(_settings, "SUMMARY_TOP", 10)             # best matches listed
MIN_SCORE = getattr(_settings, "MIN_SCORE", 5)  # a "match" scores at least this
SUMMARY_DIR = Path(getattr(_settings, "SUMMARY_DIR", Path(DB_PATH).resolve().parent / "reports"))

def gather(days: float = SUMMARY_DAYS, top: int = SUMMARY_TOP, min_score: float = MIN_SCORE,
           db_path: str = DB_PATH) -> dict:
    """Everything the summary shows, as plain data."""
    data = {"days": days, "min_score": min_score, "profile": active_profile_name(),
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    data["new_by_status"] = status_counts(days, db_path)
    data["total_by_status"] = status_counts(None, db_path)
    data["top_new"] = get_jobs(top, "top", min_score=min_score, days=days, include_zero=False, db_path=db_path)
    data["failed"] = data["total_by_status"].get("scoring_failed", 0)
    data["applications"] = application_counts(db_path)
    data["unfinished"] = unfinished_applications(10, db_path)
    data["ratings"] = R.usable_rating_count(db_path)
    data["unrated_scored"] = R.unrated_count(db_path)
    try:   # application tracking
        data["follow_ups"] = tracking.due_follow_ups(db_path)
        data["quiet"] = len(tracking.get_tracked(stale_days=14, db_path=db_path))
    except Exception:
        data["follow_ups"], data["quiet"] = [], 0
    data["ready"], data["blocked"] = _apply_readiness(min_score, days, db_path)
    return data


def _apply_readiness(min_score, days, db_path):
    """Which jobs apply_jobs.py could fill right now, and why the others can't be (no network, no browser)."""
    try:
        from apply_jobs import APPLY_WINDOW_DAYS, target_for
    except Exception:
        return [], {}
    ready, blocked = [], {}
    try:
        for job in get_candidates(_settings.MIN_SCORE, max(days, APPLY_WINDOW_DAYS), db_path=db_path):
            link, ats, reason = target_for(job)
            if reason:
                blocked.setdefault(reason, []).append(job)
            else:
                ready.append({**job, "ats": ats, "link": link})
    except Exception:
        return [], {}
    return ready, blocked


# ------------------------------------------------------------------------------ text


def _job_line(job: dict) -> str:
    salary = f"  [{job['salary']}]" if job.get("salary") else ""
    label = compat_label(job)
    compat = f"  ({label})" if label else ""
    return f"  {job['match_score']:>4g}  {job['title'][:45]} - {job['company'][:25]}{compat}{salary}"


def render_text(d: dict) -> str:
    new, total = d["new_by_status"], d["total_by_status"]
    when = "the last 24 hours" if d["days"] == 1 else f"the last {d['days']:g} days"
    lines = ["=" * 60, f"SUMMARY  ({d['generated']})  profile: {d['profile']}", "=" * 60,
             f"New in {when}: {sum(new.values())} job(s)  "
             f"(scored {new.get('scored', 0)}, filtered {new.get('filtered', 0)}, "
             f"duplicates {new.get('duplicate', 0)}, failed {new.get('scoring_failed', 0)})",
             f"In the database: {sum(total.values())} job(s)  "
             f"(scored {total.get('scored', 0)}, filtered {total.get('filtered', 0)}, "
             f"duplicates {total.get('duplicate', 0)})"]

    lines += ["", f"BEST NEW MATCHES (score {d['min_score']:g}+)"]
    lines += [_job_line(j) + f"\n        {j['apply_url'] if (j['apply_url'] or '').startswith('http') else j['job_url']}"
              for j in d["top_new"]] or ["  none"]

    lines += ["", f"RECOMMENDED TO APPLY: {len(d['ready'])} job(s)  (python apply_jobs.py --top 3)"]
    lines += [f"  {j['match_score']:>4g}  {j['title'][:40]} - {j['company'][:22]}  [{j['ats']}]" for j in d["ready"][:10]]
    if d["blocked"]:
        lines.append("CAN'T BE FILLED YET")
        for reason, jobs in sorted(d["blocked"].items(), key=lambda kv: -len(kv[1])):
            lines.append(f"  {len(jobs):>3}  {reason}")

    todo = []
    if d["failed"]:
        todo.append(f"{d['failed']} job(s) failed scoring: python -m tools.rescore --failed-only")
    if d["unfinished"]:
        todo.append(f"{len(d['unfinished'])} application(s) opened but not finished: "
                    "python apply_jobs.py --include-opened")
    for f in d.get("follow_ups", []):
        todo.append(f"follow up with {f['company']} ({f['title']}), due {f['follow_up_on']}: python -m tools.track show {f['job_id']}")
    if d.get("quiet"):
        todo.append(f"{d['quiet']} application(s) with no answer for 14+ days: python -m tools.track list --stale 14")
    if d["ratings"] < 10:
        todo.append(f"only {d['ratings']} hand rating(s): python -m tools.rating (10+ tunes the scores, 50+ is steadier)")
    elif d["unrated_scored"]:
        todo.append(f"{d['unrated_scored']} scored job(s) not rated yet: python -m tools.rating")
    lines += ["", "NEEDS YOU"] + ([f"  - {t}" for t in todo] or ["  nothing"])

    apps = d["applications"]
    if apps:
        lines += ["", "APPLICATIONS  " + ", ".join(f"{k} {v}" for k, v in sorted(apps.items()))]
    lines.append("=" * 60)
    return "\n".join(lines)


# ------------------------------------------------------------------------------ html


def render_html(d: dict) -> str:
    e = html.escape

    def link(job):
        url = job["apply_url"] if (job.get("apply_url") or "").startswith("http") else job["job_url"]
        return f'<a href="{e(url)}">{e(job["title"])}</a>'

    def rows(jobs, extra=None):
        if not jobs:
            return "<p class=none>none</p>"
        body = "".join(
            f"<tr><td class=s>{j['match_score']:g}</td><td>{link(j)}<br><span>{e(j['company'])}"
            f"{' · ' + e(j['location']) if j.get('location') else ''}"
            f"{' · ' + e(j['salary']) if j.get('salary') else ''}</span></td>"
            f"<td>{e(extra(j)) if extra else ''}</td></tr>" for j in jobs)
        return f"<table>{body}</table>"

    new, total = d["new_by_status"], d["total_by_status"]
    when = "24 hours" if d["days"] == 1 else f"{d['days']:g} days"
    blocked = "".join(f"<li><b>{len(j)}</b> {e(r)}</li>" for r, j in sorted(d["blocked"].items(), key=lambda kv: -len(kv[1])))
    todo = []
    if d["failed"]:
        todo.append(f"{d['failed']} job(s) failed scoring: <code>python -m tools.rescore --failed-only</code>")
    if d["unfinished"]:
        todo.append(f"{len(d['unfinished'])} application(s) opened, not finished: <code>python apply_jobs.py --include-opened</code>")
    if d["ratings"] < 10:
        todo.append(f"Only {d['ratings']} hand rating(s): <code>python -m tools.rating</code>")
    elif d["unrated_scored"]:
        todo.append(f"{d['unrated_scored']} scored job(s) not rated: <code>python -m tools.rating</code>")
    apps = ", ".join(f"{e(k)} {v}" for k, v in sorted(d["applications"].items())) or "none yet"
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job summary {e(d['generated'])}</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#1c1c1c;background:#fff}}
h1{{font-size:1.4rem}}h2{{font-size:1rem;margin:1.6rem 0 .4rem;text-transform:uppercase;letter-spacing:.05em;color:#555}}
table{{border-collapse:collapse;width:100%}}td{{padding:.45rem .5rem;border-bottom:1px solid #e5e5e5;vertical-align:top}}
td.s{{font-weight:700;width:3rem}}span{{color:#666;font-size:.9em}}.none{{color:#888}}code{{background:#f1f1f1;padding:.1rem .3rem;border-radius:3px}}
.stats span{{display:inline-block;margin-right:1.2rem;color:#1c1c1c}}a{{color:#0b57d0}}
@media(prefers-color-scheme:dark){{body{{background:#161616;color:#e8e8e8}}td{{border-color:#333}}code{{background:#2a2a2a}}a{{color:#8ab4f8}}span,h2{{color:#aaa}}.stats span{{color:#e8e8e8}}}}
</style></head><body><h1>Job summary</h1><p>{e(d['generated'])} &middot; profile: {e(d['profile'])}</p>
<h2>New in the last {when}</h2><p class=stats><span><b>{sum(new.values())}</b> new</span><span><b>{new.get('scored', 0)}</b> scored</span>
<span><b>{new.get('filtered', 0)}</b> filtered</span><span><b>{new.get('duplicate', 0)}</b> duplicates</span><span><b>{new.get('scoring_failed', 0)}</b> failed</span></p>
<p>Database total: {sum(total.values())} jobs, {total.get('scored', 0)} scored.</p>
<h2>Best new matches ({d['min_score']:g}+)</h2>{rows(d['top_new'])}
<h2>Ready to apply ({len(d['ready'])})</h2>{rows(d['ready'][:10], lambda j: j['ats'])}
{'<h2>Can&#39;t be filled yet</h2><ul>' + blocked + '</ul>' if blocked else ''}
<h2>Needs you</h2>{'<ul>' + ''.join(f'<li>{t}</li>' for t in todo) + '</ul>' if todo else '<p class=none>nothing</p>'}
<h2>Applications</h2><p>{apps}</p></body></html>"""


# -------------------------------------------------------------------------------- API


def print_summary(days: float = SUMMARY_DAYS, top: int = SUMMARY_TOP, min_score: float = MIN_SCORE,
                  html_report: bool = False, open_it: bool = False) -> None:
    data = gather(days, top, min_score)
    print("\n" + render_text(data))
    if html_report:
        SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        path = SUMMARY_DIR / f"summary_{datetime.now():%Y-%m-%d_%H%M}.html"
        path.write_text(render_html(data), encoding="utf-8")
        print(f"[SUMMARY] Saved {path}")
        if open_it:
            webbrowser.open(path.resolve().as_uri())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summary of new jobs and what needs you.")
    parser.add_argument("--days", type=float, default=SUMMARY_DAYS, help="how far back 'new' reaches")
    parser.add_argument("--top", type=int, default=SUMMARY_TOP)
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--html", action="store_true", help="also save an HTML report and open it")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)
    print_summary(args.days, args.top, args.min_score, html_report=args.html, open_it=args.html)