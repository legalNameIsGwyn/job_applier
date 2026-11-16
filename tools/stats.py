"""Analytics: how your job search is going.

    python -m tools.stats                 # everything, all time
    python -m tools.stats --days 30       # only jobs scraped / applications made in the last 30 days
    python -m tools.stats --section funnel,score     # funnel | score | breakdown | trends  (comma separated)
    python -m tools.stats --profile it_support

The job counts (scraped, scored, good matches) are for the active profile. Applications and what
happened to them cover everything you have tracked, whichever profile found the job.
Funnel: scraped -> scored -> good matches -> applied -> heard back -> interview -> offer.
"Heard back" means the employer answered: screening, interview, offer or a rejection. Ghosted and withdrawn don't count.
Small numbers are noisy: with only a handful of applications, treat percentages as hints, not facts.
"""

import argparse
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

import db.tracking as T
from config import settings as _s
from config.settings import DB_PATH
from db.queries import stats_jobs
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments

GOOD_SCORE = getattr(_s, "MIN_SCORE", 6)
MIN_SAMPLE = 5   # below this many applications, say so
TITLE_BUCKETS = ("python", "backend", "full stack", "fullstack", "frontend", "front end", "data", "devops",
                 "cloud", "qa", "test", "support", "junior", "associate", "intern", "software engineer",
                 "software developer", "developer")


def pct(n, d) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def _since(days):
    return (date.today() - timedelta(days=days)).isoformat() if days else None


def gather(days: int | None = None, db_path=DB_PATH) -> dict:
    """All the numbers, as plain data (so tests and other scripts can use them)."""
    T.sync_applied(db_path)
    since = _since(days)
    jobs = stats_jobs(since, db_path)
    tr = T.get_tracked(since=since, db_path=db_path)
    events = defaultdict(dict)   # job_url -> stage -> first date
    for e in T.all_events(db_path):
        events[e["job_url"]].setdefault(e["stage"], e["on_date"])
    for t in tr:
        reached = events.get(t["job_url"], {})
        t["reached"] = set(reached) | {t["stage"]}
        t["heard"] = bool(t["reached"] & set(T.RESPONDED))
        t["interviewed"] = bool(t["reached"] & {"interview", "offer"})
        t["offered"] = "offer" in t["reached"]
        dates = [d for s, d in reached.items() if s in T.RESPONDED]
        t["first_response_on"] = min(dates) if dates else None
    return {"jobs": jobs, "tracked": tr, "days": days}


# ---------------------------------------------------------------------------------- sections

def funnel(data) -> list[str]:
    jobs, tr = data["jobs"], data["tracked"]
    scored = [j for j in jobs if j["status"] == "scored" and (j["match_score"] or 0) >= 0]
    good = [j for j in scored if j["match_score"] >= GOOD_SCORE]
    applied = len(tr)
    heard = sum(t["heard"] for t in tr)
    interviewed = sum(t["interviewed"] for t in tr)
    offered = sum(t["offered"] for t in tr)
    rejected = sum("rejected" in t["reached"] for t in tr)
    ghosted = sum(t["stage"] == "ghosted" for t in tr)
    waiting = sum(t["stage"] == "applied" for t in tr)
    rows = [("Scraped", len(jobs), None),
            ("Scored", len(scored), len(jobs)),
            (f"Good matches (score {GOOD_SCORE}+)", len(good), len(scored)),
            ("Applied", applied, len(good)),
            ("Heard back", heard, applied),
            ("Interview", interviewed, applied),
            ("Offer", offered, applied)]
    out = ["FUNNEL", f"  {'':<30}{'count':>6}   % of step before"]
    for name, n, base in rows:
        out.append(f"  {name:<30}{n:>6}   {pct(n, base) if base is not None else ''}")
    out.append(f"  Still waiting: {waiting}   rejected: {rejected}   ghosted: {ghosted}")
    if applied and applied < MIN_SAMPLE:
        out.append(f"  (Only {applied} application(s) so far: percentages will jump around.)")
    if good and applied > len(good):
        out.append("  (More applied than good matches: some applications scored below the cutoff or were tracked by hand.)")
    return out


def score_vs_outcome(data) -> list[str]:
    tr = [t for t in data["tracked"] if t.get("score_at_apply") is not None or t.get("match_score") is not None]
    out = ["SCORE VS OUTCOME  (does a higher score get more answers?)"]
    if not tr:
        return out + ["  No tracked applications with a score yet."]
    bands = [(0, 6, "under 6"), (6, 7, "6 - 7"), (7, 8, "7 - 8"), (8, 9, "8 - 9"), (9, 10.01, "9 - 10")]
    out.append(f"  {'score':<10}{'applied':>8}{'heard':>8}{'rate':>7}{'interview':>11}{'rate':>7}")
    for lo, hi, label in bands:
        group = [t for t in tr if lo <= (t["score_at_apply"] if t["score_at_apply"] is not None else t["match_score"]) < hi]
        if not group:
            continue
        h = sum(t["heard"] for t in group)
        i = sum(t["interviewed"] for t in group)
        out.append(f"  {label:<10}{len(group):>8}{h:>8}{pct(h, len(group)):>7}{i:>11}{pct(i, len(group)):>7}")
    scores = [(t["score_at_apply"] if t["score_at_apply"] is not None else t["match_score"]) for t in tr]
    if len(tr) >= 8:
        heard_avg = [s for s, t in zip(scores, tr) if t["heard"]]
        quiet_avg = [s for s, t in zip(scores, tr) if not t["heard"]]
        if heard_avg and quiet_avg:
            out.append(f"  Average score: {statistics.mean(heard_avg):.1f} when they answered, "
                       f"{statistics.mean(quiet_avg):.1f} when they didn't.")
    else:
        out.append(f"  ({len(tr)} application(s): need roughly 20+ before this says much.)")
    return out


def _group(tr, keyfn):
    groups = defaultdict(list)
    for t in tr:
        for k in keyfn(t):
            groups[k].append(t)
    return groups


def _table(title, groups, limit=8) -> list[str]:
    out = [f"  By {title}", f"    {'':<28}{'applied':>8}{'heard':>8}{'rate':>7}{'interview':>11}"]
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]
    for key, group in ranked:
        h = sum(t["heard"] for t in group)
        i = sum(t["interviewed"] for t in group)
        out.append(f"    {str(key)[:27]:<28}{len(group):>8}{h:>8}{pct(h, len(group)):>7}{i:>11}")
    return out


def breakdown(data) -> list[str]:
    tr = data["tracked"]
    out = ["BREAKDOWN  (what's working)"]
    if not tr:
        return out + ["  No tracked applications yet."]
    out += _table("job site", _group(tr, lambda t: [(t["site"] or "unknown")]))
    out += _table("applicant system", _group(tr, lambda t: [(t["ats"] or "unknown")]))
    out += _table("company", _group(tr, lambda t: [(t["company"] or "unknown")]), limit=6)

    def buckets(t):
        title = (t["title"] or "").lower()
        found = [b for b in TITLE_BUCKETS if b in title]
        return found or ["other"]
    out += _table("title keyword (a job can count in several)", _group(tr, buckets), limit=8)
    return out


def _week(d: str) -> str:
    dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
    return (dt - timedelta(days=dt.weekday())).isoformat()   # the Monday of that week


def trends(data) -> list[str]:
    jobs, tr = data["jobs"], data["tracked"]
    out = ["TRENDS  (weeks start Monday)"]
    scraped = defaultdict(int)
    for j in jobs:
        if j["scraped_at"]:
            scraped[_week(j["scraped_at"])] += 1
    applied = defaultdict(int)
    heard = defaultdict(int)
    for t in tr:
        if t["applied_on"]:
            applied[_week(t["applied_on"])] += 1
            heard[_week(t["applied_on"])] += t["heard"]
    weeks = sorted(set(scraped) | set(applied))[-8:]
    if not weeks:
        return out + ["  Nothing yet."]
    out.append(f"  {'week of':<12}{'scraped':>9}{'applied':>9}{'heard back':>12}")
    for w in weeks:
        out.append(f"  {w:<12}{scraped.get(w, 0):>9}{applied.get(w, 0):>9}{heard.get(w, 0):>12}")
    waits = []
    for t in tr:
        if t["first_response_on"] and t["applied_on"]:
            d = (datetime.strptime(t["first_response_on"], "%Y-%m-%d") - datetime.strptime(t["applied_on"], "%Y-%m-%d")).days
            waits.append(max(d, 0))
    if waits:
        out.append(f"  Days to hear back: median {statistics.median(waits):g}, fastest {min(waits)}, slowest {max(waits)} "
                   f"({len(waits)} answered)")
    open_ages = [(date.today() - datetime.strptime(t["applied_on"], "%Y-%m-%d").date()).days
                 for t in tr if t["stage"] == "applied" and t["applied_on"]]
    if open_ages:
        out.append(f"  Waiting on {len(open_ages)}; the oldest has been quiet {max(open_ages)} day(s).")
    return out


SECTIONS = {"funnel": funnel, "score": score_vs_outcome, "breakdown": breakdown, "trends": trends}


def report(days=None, sections=None, db_path=DB_PATH) -> str:
    data = gather(days, db_path)
    title = (f"JOB SEARCH STATS ({'last ' + str(days) + ' days' if days else 'all time'}; "
             f"job counts for profile '{active_profile_name()}', applications from all profiles)")
    blocks = [[title]] + [SECTIONS[s](data) for s in (sections or SECTIONS)]
    return "\n\n".join("\n".join(b) for b in blocks)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Job search analytics.", epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="only the last N days")
    ap.add_argument("--section", help="comma separated: " + ", ".join(SECTIONS))
    add_profile_arguments(ap)
    a = ap.parse_args()
    apply_profile_arguments(a)
    chosen = [s.strip() for s in a.section.split(",")] if a.section else None
    if chosen and any(s not in SECTIONS for s in chosen):
        ap.error("section must be among: " + ", ".join(SECTIONS))
    print(report(a.days, chosen))