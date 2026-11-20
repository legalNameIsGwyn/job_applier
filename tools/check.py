"""Check jobs that are already in the database. No scraping, and no model calls.

Use it after you change the blocker rules or your resume, to see which saved jobs the rules would now drop.
It works on the active profile: --profile NAME, or DEFAULT_PROFILE in config/settings.py.

    python -m tools.check --blockers             # block saved jobs that need a clearance or citizenship
                                                 # (lists them, asks, then marks them blocked and clears the description)
    python -m tools.check --blockers --show-all  # list every job, not just the first 15 per group
    python -m tools.check --blockers --yes       # don't ask for confirmation

To add a check, write a function(assume_yes, show_all, db_path) and add it to CHECKS at the bottom of this file;
it gets its own --flag automatically. (tools.rescore scores jobs again with the model; this tool never does.)
"""

import argparse
import json
import re

from sqlalchemy import select

from config.settings import DB_PATH
from core.compat import drop_reason
from core.console import INDENT, link, paint, section, tag
from core.scorer import blocked_reason
from db.models import Application, Job, JobScore
from db.repo import init_db
from db.session import (
    active_profile_name, add_profile_arguments, apply_profile_arguments, current_profile_id, session_scope,
)


# ------------------------------------------------------------------------------------ --blockers


def _with_kind(item: dict) -> dict:
    """Rows saved before 'kind' was stored: a hard item that mentions a clearance counts as kind 'clearance'."""
    if "kind" not in item and item.get("hard") and re.search(r"clearance", str(item.get("text", "")), re.I):
        return {**item, "kind": "clearance"}
    return item


def _group(reason: str) -> str:
    """Which heading a blocked job is listed under."""
    if "citizen" in reason.lower():
        return "U.S. citizenship"
    return "Security clearance" if '("' in reason else "Clearance from the saved detailed check"


def _fit(text: str, width: int) -> str:
    """One line, cut to `width` characters with an ellipsis."""
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def _show_found(found: list, show_all: bool = False, per_group: int = 15) -> None:
    """The jobs about to be blocked, grouped by reason: an aligned line (title, company, matched words), then its link."""
    groups = {}
    for _, _, title, company, reason, url in found:
        match = re.search(r'\("(.*?)"\)', reason)
        groups.setdefault(_group(reason), []).append((title, company, match.group(1) if match else "", url))
    for name, items in sorted(groups.items(), key=lambda g: -len(g[1])):
        print()
        print(section(name, paint(f"{len(items)} job(s)", "gray")))
        for title, company, phrase, url in (items if show_all else items[:per_group]):
            print(f"   {_fit(title, 46):<46}  {_fit(company, 28):<28}  " + (paint(f'"{phrase}"', "gray") if phrase else ""))
            if url:
                print(INDENT + "  " + link(url))
        if not show_all and len(items) > per_group:
            print(paint(f"   … and {len(items) - per_group} more (add --show-all to list every one)", "gray"))
    print()


def check_blockers(assume_yes=False, show_all=False, db_path=DB_PATH) -> dict:
    """Block saved jobs that the current blocker rules would have dropped. No model calls.

    Checks this profile's scored, failed and filtered jobs: the built-in rules (clearance, citizenship) on the saved
    description, and the saved detailed check's required clearance items (DROP_ON_MISSING_KINDS). Jobs you
    already have an application for are left alone. A blocked job gets status 'blocked', score 0 and the reason.
    Its description is cleared unless another profile still has the job scored (descriptions are shared).
    Returns counts: blocked, cleared.
    """
    init_db(db_path)
    found = []   # (score id, job id, title, company, reason, job url)
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        applied = set(s.scalars(select(Application.job_id)))
        rows = s.execute(
            select(Job, JobScore).join(JobScore, JobScore.job_id == Job.id)
            .where(JobScore.profile_id == pid, Job.is_duplicate.is_(False),
                   JobScore.status.in_(("scored", "scoring_failed", "filtered")))
            .order_by(Job.id)).all()
        for job, score in rows:
            if job.id in applied:
                continue
            reason = blocked_reason(job.title, job.description) if (job.description or "").strip() else None
            if not reason:
                try:
                    missing = [_with_kind(m) for m in json.loads(score.compat_missing or "[]") if isinstance(m, dict)]
                except ValueError:
                    missing = []
                reason = drop_reason({"missing": missing})
            if reason:
                found.append((score.id, job.id, job.title, job.company, reason, job.job_url))

    if not found:
        tag("CHECK", f"Profile '{active_profile_name()}': no saved job needs blocking.")
        return {"blocked": 0, "cleared": 0}

    tag("CHECK", f"Profile '{active_profile_name()}': {len(found)} saved job(s) would now be blocked (no model needed).")
    _show_found(found, show_all)
    if not assume_yes and input("Block them and clear their descriptions? [y/N] ").strip().lower() not in ("y", "yes"):
        tag("CHECK", "Cancelled.")
        return {"blocked": 0, "cleared": 0}

    cleared = 0
    with session_scope(db_path) as s:
        pid = current_profile_id(s)
        for score_id, job_id, _, _, reason, _ in found:
            score = s.get(JobScore, score_id)
            score.status, score.match_score, score.model_score, score.keyword_score = "blocked", 0.0, 0.0, None
            score.matched_skills, score.gaps = "[]", json.dumps([reason])
            score.compat_pct = score.compat_detail_pct = None
            score.compat_missing, score.compat_capped = "[]", 0
            others = s.scalars(select(JobScore).where(JobScore.job_id == job_id, JobScore.profile_id != pid)).all()
            if all(o.status == "blocked" for o in others):   # no other profile still uses the description
                job = s.get(Job, job_id)
                if job.description:
                    job.description = ""
                    cleared += 1
    tag("CHECK", f"Blocked {len(found)} job(s), cleared {cleared} description(s).")
    return {"blocked": len(found), "cleared": cleared}


# ------------------------------------------------------------------------------------ the tool

# flag name -> (function, help text). Each function takes (assume_yes, show_all, db_path).
CHECKS = {
    "blockers": (check_blockers, "block saved jobs that need a clearance or citizenship, and clear their descriptions"),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check jobs already in the database (no scraping, no model).")
    for name, (_, text) in CHECKS.items():
        parser.add_argument(f"--{name}", action="store_true", help=text)
    parser.add_argument("--show-all", action="store_true", help="list every job, not just the first 15 per group")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)
    chosen = [name for name in CHECKS if getattr(args, name)]
    if not chosen:
        parser.print_help()
    for name in chosen:
        CHECKS[name][0](args.yes, args.show_all)