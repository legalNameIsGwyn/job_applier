"""Re-score jobs that are already in the database. No scraping, no network except Ollama.

Use it after you change the prompt (config/prompts.py), your resume, the model, the filter
rules or the keyword lists, to see how the jobs you already have would score now.
It works on the active profile: --profile NAME, or DEFAULT_PROFILE in config/settings.py.

    python -m tools.rescore                  # every scored job, and any that failed before
    python -m tools.rescore --failed-only    # only jobs whose scoring failed
    python -m tools.rescore --include-filtered   # also re-check filtered jobs against the current rules
    python -m tools.rescore --include-unscored   # also score jobs this profile has never seen
                                                 # (for example jobs another profile scraped)
    python -m tools.rescore -n 20            # at most 20 jobs (oldest first)
    python -m tools.rescore --url <job url>  # one job
    python -m tools.rescore --yes            # don't ask for confirmation

Each job is saved as soon as it is scored, so Ctrl-C loses nothing. If the model fails on a
job that already had a score, the old score is kept. Your hand ratings are never touched.
"""

import argparse

from config.settings import DB_PATH, MAX_CONSECUTIVE_FAILURES
from core.calibration import blend, keyword_score
from core.filters import filter_reason
from core.scorer import MODEL, score_job
from db.calibrations import load_calibration
from db.queries import jobs_for_rescore
from db.repo import FAILED_SCORE, init_db, save_job
from db.session import active_profile_name, add_profile_arguments, apply_profile_arguments


def get_targets(failed_only=False, include_filtered=False, url=None, limit=None, include_unscored=False,
                db_path=DB_PATH):
    """Jobs to re-score, as dicts, oldest first. Jobs with no description are left out."""
    return jobs_for_rescore(failed_only, include_filtered, url, limit, include_unscored, db_path)


def rescore(failed_only=False, include_filtered=False, url=None, limit=None, assume_yes=False,
            include_unscored=False, db_path=DB_PATH) -> dict:
    """Re-score the selected jobs. Returns counts: updated, filtered, failed."""
    init_db(db_path)
    jobs = get_targets(failed_only, include_filtered, url, limit, include_unscored, db_path)
    if not jobs:
        print("[RESCORE] No matching jobs with a description.")
        return {"updated": 0, "filtered": 0, "failed": 0}

    print(f"[RESCORE] Profile '{active_profile_name()}': {len(jobs)} job(s) to re-score with model '{MODEL}'.")
    if not assume_yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        print("[RESCORE] Cancelled.")
        return {"updated": 0, "filtered": 0, "failed": 0}

    cal = load_calibration(db_path)   # read once, not once per job
    updated = filtered = failed = streak = 0
    changes = []  # (old, new, title, company)
    for i, job in enumerate(jobs, start=1):
        label = f"{job['title'][:50]} - {job['company'][:25]}"

        reason = filter_reason(job["title"], job["company"], job["description"])
        if reason:
            print(f"[RESCORE] {i}/{len(jobs)} FILTERED  {label}: {reason}")
            save_job(job, {"match_score": 0.0, "matched_skills": [], "gaps": [reason]},
                     db_path=db_path, status="filtered", model_score=0.0)
            filtered += 1
            continue

        old = job["match_score"]   # None for a job this profile has never scored
        try:
            score = score_job(job["title"], job["company"], job["location"], job["description"])
            model = score["match_score"]
            kw = keyword_score(job["title"], job["description"])
            new = blend(model, kw, cal)
            save_job(job, {**score, "match_score": new}, db_path=db_path, model_score=model, keyword_score=kw)
            streak = 0
            updated += 1
            changes.append((old, new, job["title"], job["company"]))
            before = "new" if old is None else "failed" if old == FAILED_SCORE else f"{old:g}"
            print(f"[RESCORE] {i}/{len(jobs)} {before} -> {new:g}  (model {model:g}, keywords {kw:g})  {label}")
        except Exception as e:
            failed += 1
            streak += 1
            print(f"[RESCORE] {i}/{len(jobs)} FAILED, old score kept  {label}: {e}")
            if streak >= MAX_CONSECUTIVE_FAILURES:
                print(f"[RESCORE] {MAX_CONSECUTIVE_FAILURES} failures in a row. Is Ollama running and "
                      f"is '{MODEL}' pulled? Stopping; progress so far is saved.")
                break

    scored_before = [c for c in changes if c[0] is not None and c[0] != FAILED_SCORE]
    print(f"\n[RESCORE] Updated {updated}, newly filtered {filtered}, failed {failed}.")
    if scored_before:
        avg = sum(c[1] - c[0] for c in scored_before) / len(scored_before)
        print(f"[RESCORE] Average change in score: {avg:+.2f}")
        print("[RESCORE] Biggest moves:")
        for old, new, title, company in sorted(scored_before, key=lambda c: abs(c[1] - c[0]), reverse=True)[:5]:
            print(f"   {old:g} -> {new:g}  {title[:45]} - {company[:25]}")
    return {"updated": updated, "filtered": filtered, "failed": failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-score jobs already in the database.")
    parser.add_argument("--failed-only", action="store_true", help="only jobs whose scoring failed")
    parser.add_argument("--include-filtered", action="store_true",
                        help="also re-check filtered jobs; ones that now pass the rules get scored")
    parser.add_argument("--include-unscored", action="store_true",
                        help="also score jobs this profile has never seen (e.g. scraped by another profile)")
    parser.add_argument("-n", "--limit", type=int, help="most jobs to re-score")
    parser.add_argument("--url", help="re-score just this job URL")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)
    rescore(args.failed_only, args.include_filtered, args.url, args.limit, args.yes, args.include_unscored)