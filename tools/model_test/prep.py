"""The scoring steps that decide a posting's score, gaps and compatibility, using the program's own scorer and compat check.

Bridge mode and "auto" mode depend on these. For a fair document comparison they are computed ONCE, with one
reference model (--ref-model), and every model then writes from the same numbers ("frozen", the default). With
--compat own each model computes its own first, which is how the real pipeline behaves.

The `score` command runs this once per model so you can look at the results side by side (compare.py); the
frozen document runs use only the numbers in KEYS. Run by runner.py as a subprocess (a profile and a model are fixed per process); compute() is also called by worker.py.
Uses the raw model score; the keyword blend and your calibration are not applied, because only gaps and
compatibility are needed here.
"""

import argparse
import json
import time
import traceback
from pathlib import Path

# What gets copied onto the posting. These are the field names create_application() and choose_mode() read.
KEYS = ("match_score", "gaps", "compat_pct", "compat_detail_pct", "compat_missing", "compat_capped")


def compute(job: dict) -> dict:
    from core import compat
    from core.scorer import load_resume, score_job

    from config.settings import MIN_SCORE
    resume = load_resume()
    score = score_job(job["title"], job["company"], job.get("location", ""), job["description"])
    out = {"match_score": score["match_score"], "matched_skills": score["matched_skills"], "gaps": score["gaps"],
           "compat_pct": compat.rough_pct(score["matched_skills"], score["gaps"]),
           "compat_detail_pct": None, "compat_missing": [], "compat_capped": False,
           "requirements": [], "drop_reason": None, "blocked_reason": None, "min_score": MIN_SCORE}
    if score["match_score"] <= 0:   # auto-rejected (clearance and the like) before the model was asked: nothing to measure
        out["blocked_reason"] = (score["gaps"] or [None])[0]
        return out

    # compat.detailed() only returns the totals; judge_all() holds each requirement's verdict, so watch it as it runs
    judged, real_judge_all = [], compat.judge_all

    def watched_judge_all(reqs, res):
        verdicts = real_judge_all(reqs, res)
        judged.extend(verdicts)
        return verdicts

    compat.judge_all = watched_judge_all
    try:
        detail = compat.detailed(job, resume)
        if detail:
            out.update(compat_detail_pct=detail["detail_pct"], compat_missing=detail["missing"],
                       compat_capped=detail["capped"], drop_reason=compat.drop_reason(detail))
        out["requirements"] = [{k: r.get(k) for k in ("text", "kind", "required", "met")} for r in judged]
    except Exception as e:   # the real pipeline also carries on without the detailed check
        out["compat_error"] = f"{type(e).__name__}: {e}"
    finally:
        compat.judge_all = real_judge_all
    return out


def main() -> None:
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument("--profile", required=True)   # read by the config loader from the command line
    p.add_argument("--job-file", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"profile": args.profile, "kind": "score", "ok": False, "error": None}
    started = time.time()
    try:
        from config.settings import ACTIVE_PROFILE
        from core.scorer import MODEL
        result["model_used"], result["profile_used"] = MODEL, ACTIVE_PROFILE
        if ACTIVE_PROFILE != args.profile:
            raise RuntimeError(f"asked for profile '{args.profile}' but '{ACTIVE_PROFILE}' was loaded")
        result.update(compute(json.loads(Path(args.job_file).read_text(encoding="utf-8"))))
        result["ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
    finally:
        result["seconds"] = round(time.time() - started, 1)
        out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
