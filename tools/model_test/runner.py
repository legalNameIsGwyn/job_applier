"""Generate resumes and cover letters with several models and profiles, so you can compare them.

From the project folder:
    python -m tools.model_test docs --profiles software it_support --models qwen2.5:7b llama3.1:8b --url <job url>
    python -m tools.model_test docs --profiles software --models qwen2.5:7b llama3.1:8b --linkedin-url <linkedin job link>
    python -m tools.model_test docs --profiles software --models qwen2.5:7b llama3.1:8b --posting-file my_postings.json
    python -m tools.model_test docs ... --mode auto                # the compatibility score picks standard/bridge/boilerplate
    python -m tools.model_test docs ... --mode bridge --compat own # each model works out its own gaps (default: frozen)
    python -m tools.model_test docs ... --repeat 3          # same model, same input, 3 times: how much does it vary?
    python -m tools.model_test score --profiles software --models qwen2.5:7b llama3.1:8b --url <job url>   # job score + compatibility
    python -m tools.model_test compare --run NAME                   # look at any run side by side
    python -m tools.model_test docs ... --run friday        # name the run; run it again and finished cells are skipped

Every combination of posting x profile x repeat is run by every model, one after another, through the program's own
create_application(). Results: data/model_tests/<run>/<profile>/<model>/<posting>/r<N>/ holds the two .docx files,
notes.txt, log.txt (what the program printed) and result.json (what the model returned, timings, warnings).
Nothing is written to your jobs database or to profiles/<name>/applications.

Bridge and auto mode need each posting's gaps and compatibility. By default (--compat frozen) they are worked out once
per profile and posting with a reference model (--ref-model, default the first model) and every model writes from the
same numbers, so only the writing differs. --compat own lets each model work out its own, like the real pipeline.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from tools.model_test import postings as postings_mod
from tools.model_test.prep import KEYS as FROZEN_KEYS

PROJECT_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_DIR / "data" / "model_tests"
MODES = ("standard", "bridge", "boilerplate", "auto")


def _safe(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("._") or "x"


def _tagged(name: str) -> str:
    return name if ":" in name else name + ":latest"


# ------------------------------------------------------------------------------ checks before any model time is spent


def check_profiles(names: list[str]) -> None:
    from config.profile_loader import list_profiles, profile_dir
    have = list_profiles()
    for name in names:
        if name not in have:
            raise SystemExit(f"[MODEL TEST] No profile '{name}'. Existing profiles: {', '.join(have) or 'none'}.")
        if not (profile_dir(name) / "resume.json").is_file():
            raise SystemExit(f"[MODEL TEST] Profile '{name}' has no resume.json.")


def installed_models() -> set[str] | None:
    """Names `ollama list` shows, or None when Ollama can't be asked (then the models are tried anyway)."""
    try:
        import ollama
        listing = ollama.Client().list()
        items = listing["models"] if isinstance(listing, dict) else listing.models
        names = set()
        for m in items:
            name = (m.get("model") or m.get("name")) if isinstance(m, dict) else (getattr(m, "model", None) or getattr(m, "name", None))
            if name:
                names.add(_tagged(name))
        return names
    except Exception:
        return None


def check_models(models: list[str]) -> None:
    have = installed_models()
    if have is None:
        print("[MODEL TEST] Could not ask Ollama which models are installed; trying them anyway.")
        return
    missing = [m for m in models if _tagged(m) not in have]
    if missing:
        raise SystemExit(f"[MODEL TEST] Not installed: {', '.join(missing)}. Installed: {', '.join(sorted(have)) or 'none'}. "
                         "Install one with:  ollama pull NAME")


# ------------------------------------------------------------------------------------------------------------- running


def _spawn(module: str, extra: list[str], model: str, log_path: Path, timeout: int, scratch_db: Path) -> int | None:
    """Run one of this package's modules in a fresh process with `model` as OLLAMA_MODEL. None = timed out."""
    cmd = [sys.executable, "-m", module] + extra
    # OLLAMA_MODEL is how config/settings.py picks the model; JOBS_DB points any stray database use at a scratch file.
    env = {**os.environ, "OLLAMA_MODEL": model, "JOBS_DB": str(scratch_db), "PYTHONUTF8": "1", "NO_COLOR": "1"}
    with open(log_path, "wb") as log:
        try:
            return subprocess.run(cmd, cwd=PROJECT_DIR, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return None


def _read_result(result_file: Path, code, timeout: int, model: str, profile: str) -> dict:
    """The JSON a subprocess wrote, or a failure record when it wrote none. Fails it if the wrong model ran."""
    if not result_file.exists():
        why = f"timed out after {timeout}s" if code is None else f"exited with code {code} and no result (see the log next to it)"
        result_file.write_text(json.dumps({"ok": False, "error": why, "profile": profile}), encoding="utf-8")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if result.get("ok") and result.get("model_used") != model:
        result.update(ok=False, error=f"asked for model {model} but {result.get('model_used')} was used")
        result_file.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def run_cell(cell: dict, job_file: Path, mode: str, compat: str, timeout: int, scratch_db: Path) -> dict:
    out: Path = cell["dir"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    code = _spawn("tools.model_test.worker",
                  ["--profile", cell["profile"], "--job-file", str(job_file), "--out", str(out), "--mode", mode,
                   "--compat", compat], cell["model"], out / "log.txt", timeout, scratch_db)
    return _read_result(out / "result.json", code, timeout, cell["model"], cell["profile"])


def freeze(profile: str, posting: dict, run_dir: Path, ref_model: str, timeout: int, scratch_db: Path, force: bool) -> dict:
    """Gaps and compatibility for one posting under one profile, worked out once by the reference model."""
    out = run_dir / "frozen" / profile / f"{posting['id']}.json"
    if out.is_file() and not force:
        old = json.loads(out.read_text(encoding="utf-8"))
        if old.get("ok"):
            return old
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    code = _spawn("tools.model_test.prep",
                  ["--profile", profile, "--job-file", str(run_dir / "postings" / f"{posting['id']}.json"), "--out", str(out)],
                  ref_model, out.with_suffix(".log"), timeout, scratch_db)
    return _read_result(out, code, timeout, ref_model, profile)


def _row(cell: dict, r: dict) -> dict:
    """One line of run.json for a cell: just enough to build the summary and to find the cell again."""
    return {"profile": cell["profile"], "model": cell["model"], "posting": cell["posting"], "repeat": cell["repeat"],
            "dir": str(cell["dir"].relative_to(cell["run_dir"])), "ok": bool(r.get("ok")), "error": r.get("error"),
            "seconds": r.get("seconds"), "mode": r.get("mode"), "summary_fallback": r.get("summary_fallback"),
            "warnings": len(r.get("warnings") or []), "letter_words": r.get("letter_words"),
            "bridges": len(r.get("bridges") or []), "model_calls": len(r.get("ask_calls") or []),
            "match_score": r.get("match_score"), "compat_detail_pct": r.get("compat_detail_pct"),
            "gap_count": len(r["gaps"]) if "gaps" in r else None, "dropped": bool(r.get("drop_reason"))}


def _avg(rows: list[dict], key: str):
    values = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(values) / len(values), 1) if values else None


def summarize(rows: list[dict], kind: str = "docs") -> list[dict]:
    """One line per (profile, model)."""
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["profile"], r["model"]), []).append(r)
    out = []
    for (profile, model), g in groups.items():
        ok = [r for r in g if r["ok"]]
        line = {"profile": profile, "model": model, "cells": len(g), "ok": len(ok), "avg_seconds": _avg(ok, "seconds")}
        if kind == "score":
            line.update(avg_score=_avg(ok, "match_score"), avg_detail_pct=_avg(ok, "compat_detail_pct"),
                        avg_gaps=_avg(ok, "gap_count"), would_drop=sum(1 for r in ok if r["dropped"]))
        else:
            line.update(summary_fallbacks=sum(1 for r in ok if r["summary_fallback"]),
                        avg_warnings=_avg(ok, "warnings"), avg_letter_words=_avg(ok, "letter_words"))
        out.append(line)
    return out


COLUMNS = {
    "docs": [("profile", "profile"), ("model", "model"), ("ok", "ok"), ("avg_seconds", "secs"),
             ("summary_fallbacks", "summary fallbacks"), ("avg_warnings", "warnings"), ("avg_letter_words", "letter words")],
    "score": [("profile", "profile"), ("model", "model"), ("ok", "ok"), ("avg_seconds", "secs"), ("avg_score", "avg score"),
              ("avg_detail_pct", "avg detailed %"), ("avg_gaps", "avg gaps"), ("would_drop", "would drop")],
}


def print_summary(table: list[dict], kind: str = "docs") -> None:
    cols = COLUMNS[kind]
    lines = [[h for _, h in cols]] + [[f"{r['ok']}/{r['cells']}" if k == "ok" else str(r[k]) for k, _ in cols] for r in table]
    widths = [max(len(line[i]) for line in lines) for i in range(len(cols))]
    for i, line in enumerate(lines):
        print("  " + "  ".join(c.ljust(w) for c, w in zip(line, widths)).rstrip())
        if i == 0:
            print("  " + "  ".join("-" * w for w in widths))


# ----------------------------------------------------------------------------------- steps shared by docs and score


def load_postings(args, profiles: list[str], saved: Path) -> list[dict]:
    found = []
    try:
        for f in args.posting_file or []:
            found += postings_mod.from_file(f)
        if args.url:
            found += postings_mod.from_database(args.url)
        if args.linkedin_url:
            if "--profile" not in sys.argv:   # the scraper module loads the config; use a profile you are testing
                sys.argv += ["--profile", profiles[0]]
            found += postings_mod.from_linkedin(args.linkedin_url)
    except ValueError as e:
        raise SystemExit(f"[MODEL TEST] {e}")
    if not found and saved.is_file():
        found = json.loads(saved.read_text(encoding="utf-8"))   # resuming a named run
    found = postings_mod.unique(found)
    if not found:
        raise SystemExit("[MODEL TEST] Give at least one posting: --url JOB_URL (scraped), --linkedin-url LINK "
                         "or --posting-file FILE.json")
    return found


def start_run(run_dir: Path, found: list[dict], profiles: list[str], models: list[str], repeat: int) -> list[dict]:
    """Save the postings into the run folder and list every cell to run."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "postings").mkdir(exist_ok=True)
    (run_dir / "postings.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    for p in found:
        (run_dir / "postings" / f"{p['id']}.json").write_text(json.dumps(p, indent=1), encoding="utf-8")
    # Every model sees the same input before the next input starts, so an interrupted run still compares fairly.
    return [{"profile": prof, "model": m, "posting": p["id"], "repeat": r, "run_dir": run_dir,
             "dir": run_dir / prof / _safe(m) / p["id"] / f"r{r}"}
            for p in found for prof in profiles for r in range(1, repeat + 1) for m in models]


def execute(cells: list[dict], rows: list[dict], save, run_one, force: bool, skip_reason=None, note=None) -> None:
    """Run every cell, skipping finished ones. Stops after 3 failures in a row or on Ctrl-C (rows keeps what finished)."""
    failures_in_a_row = 0
    try:
        for n, cell in enumerate(cells, 1):
            label = f"{cell['profile']} | {cell['model']} | {cell['posting']} | r{cell['repeat']}"
            why = skip_reason(cell) if skip_reason else None
            if why:
                print(f"[{n}/{len(cells)}] not run ({why}): {label}")
                rows.append(_row(cell, {"ok": False, "error": why}))
                continue
            previous = cell["dir"] / "result.json"
            if previous.is_file() and not force:
                old = json.loads(previous.read_text(encoding="utf-8"))
                if old.get("ok"):
                    print(f"[{n}/{len(cells)}] skipped (already done): {label}")
                    rows.append(_row(cell, old))
                    continue
            print(f"[{n}/{len(cells)}] {label} ...", end=" ", flush=True)
            started = time.time()
            result = run_one(cell)
            rows.append(_row(cell, result))
            save(False)
            if result.get("ok"):
                failures_in_a_row = 0
                print(f"ok {time.time() - started:.0f}s{note(result) if note else ''}")
            else:
                failures_in_a_row += 1
                print(f"FAILED: {result.get('error')}")
                if failures_in_a_row >= 3:
                    print("[MODEL TEST] Stopped: 3 failures in a row. Is Ollama running? See log.txt in the failed folders.")
                    return
    except KeyboardInterrupt:
        print("\n[MODEL TEST] Interrupted. Run the same command with --run " + cells[0]["run_dir"].name + " to continue.")


def finish(run_dir: Path, rows: list[dict], cells: list[dict], kind: str) -> None:
    table = summarize(rows, kind)
    if table:
        print()
        print_summary(table, kind)
    print(f"\n[MODEL TEST] Results: {run_dir}")
    print(f"[MODEL TEST] To look at them: python -m tools.model_test compare --run {run_dir.name}"
          + ("" if len(rows) == len(cells) else "   (the run is not finished; repeat the command to continue)"))


def _run_dir(args) -> Path:
    return Path(args.out or RUNS_DIR) / (args.run or datetime.now().strftime("%Y%m%d-%H%M%S"))


# ------------------------------------------------------------------------------------------------------- commands


def cmd_docs(args) -> None:
    models = list(dict.fromkeys(args.models))
    profiles = list(dict.fromkeys(args.profiles))
    check_profiles(profiles)

    run_dir = _run_dir(args)
    found = load_postings(args, profiles, run_dir / "postings.json")
    ref_model = args.ref_model or models[0]
    check_models(models + ([ref_model] if ref_model not in models else []))
    cells = start_run(run_dir, found, profiles, models, args.repeat)
    print(f"[MODEL TEST] run '{run_dir.name}': {len(found)} posting(s) x {len(profiles)} profile(s) x {args.repeat} repeat(s) "
          f"x {len(models)} model(s) = {len(cells)} cell(s), mode {args.mode}")

    scratch_db = run_dir / "_unused.sqlite"
    rows: list[dict] = []
    meta = {"run": run_dir.name, "kind": "docs", "started": datetime.now().isoformat(timespec="seconds"), "mode": args.mode,
            "profiles": profiles, "models": models, "repeat": args.repeat, "compat": args.compat, "ref_model": ref_model,
            "postings": [{k: p[k] for k in ("id", "title", "company", "job_url")} for p in found]}

    def save(done: bool) -> None:
        (run_dir / "run.json").write_text(json.dumps({**meta, "finished": done, "cells": rows, "summary": summarize(rows)},
                                                      indent=1), encoding="utf-8")

    # Bridge and auto mode read each posting's gaps and compatibility. Frozen: work them out once, with the reference
    # model, so every model writes from the same numbers. (Gaps you put in a posting file are always used as given.)
    job_files, frozen_failed = {}, {}
    try:
        for prof in profiles:
            for p in found:
                job, jf = dict(p), run_dir / "jobs" / prof / f"{p['id']}.json"
                jf.parent.mkdir(parents=True, exist_ok=True)
                if args.mode in ("bridge", "auto") and args.compat == "frozen" and not (p.get("gaps") or p.get("compat_missing")):
                    print(f"[MODEL TEST] freezing gaps and compatibility with {ref_model}: {prof} | {p['id']} ...", end=" ", flush=True)
                    fr = freeze(prof, p, run_dir, ref_model, args.timeout, scratch_db, args.force)
                    if fr.get("ok"):
                        job.update({k: fr[k] for k in FROZEN_KEYS if k in fr})
                        print(f"ok ({fr.get('compat_detail_pct') if fr.get('compat_detail_pct') is not None else 'no detailed %'})")
                    else:
                        frozen_failed[(prof, p["id"])] = "frozen scoring failed: " + str(fr.get("error"))
                        print(f"FAILED: {fr.get('error')}")
                jf.write_text(json.dumps(job, indent=1), encoding="utf-8")
                job_files[(prof, p["id"])] = jf
    except KeyboardInterrupt:
        print("\n[MODEL TEST] Interrupted. Run the same command with --run " + run_dir.name + " to continue.")
        return

    execute(cells, rows, save,
            run_one=lambda c: run_cell(c, job_files[(c["profile"], c["posting"])], args.mode, args.compat, args.timeout, scratch_db),
            force=args.force, skip_reason=lambda c: frozen_failed.get((c["profile"], c["posting"])),
            note=lambda r: "  (summary fell back to your original)" if r.get("summary_fallback") else "")
    save(len(rows) == len(cells))
    finish(run_dir, rows, cells, "docs")


def run_score_cell(cell: dict, job_file: Path, timeout: int, scratch_db: Path) -> dict:
    out: Path = cell["dir"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    code = _spawn("tools.model_test.prep", ["--profile", cell["profile"], "--job-file", str(job_file), "--out", str(out / "result.json")],
                  cell["model"], out / "log.txt", timeout, scratch_db)
    return _read_result(out / "result.json", code, timeout, cell["model"], cell["profile"])


def cmd_score(args) -> None:
    models = list(dict.fromkeys(args.models))
    profiles = list(dict.fromkeys(args.profiles))
    check_profiles(profiles)

    run_dir = _run_dir(args)
    found = load_postings(args, profiles, run_dir / "postings.json")
    check_models(models)
    cells = start_run(run_dir, found, profiles, models, args.repeat)
    print(f"[MODEL TEST] scoring run '{run_dir.name}': {len(found)} posting(s) x {len(profiles)} profile(s) x {args.repeat} "
          f"repeat(s) x {len(models)} model(s) = {len(cells)} cell(s)")

    scratch_db = run_dir / "_unused.sqlite"
    rows: list[dict] = []
    meta = {"run": run_dir.name, "kind": "score", "started": datetime.now().isoformat(timespec="seconds"),
            "profiles": profiles, "models": models, "repeat": args.repeat,
            "postings": [{k: p[k] for k in ("id", "title", "company", "job_url")} for p in found]}

    def save(done: bool) -> None:
        (run_dir / "run.json").write_text(json.dumps({**meta, "finished": done, "cells": rows, "summary": summarize(rows, "score")},
                                                      indent=1), encoding="utf-8")

    execute(cells, rows, save,
            run_one=lambda c: run_score_cell(c, run_dir / "postings" / f"{c['posting']}.json", args.timeout, scratch_db),
            force=args.force,
            note=lambda r: f"  score {r.get('match_score'):g}" if r.get("match_score") is not None else "")
    save(len(rows) == len(cells))
    finish(run_dir, rows, cells, "score")


def _common_arguments(p) -> None:
    p.add_argument("--profiles", nargs="+", required=True, metavar="NAME", help="profiles to test (each uses its own resume.json)")
    p.add_argument("--models", nargs="+", required=True, metavar="MODEL", help="Ollama model names, e.g. qwen2.5:7b")
    p.add_argument("--url", action="append", metavar="JOB_URL", help="a scraped posting from your database (repeatable)")
    p.add_argument("--linkedin-url", action="append", metavar="LINK", help="a live linkedin.com/jobs/view/... posting (repeatable)")
    p.add_argument("--posting-file", action="append", metavar="FILE", help="JSON file of postings you provide (repeatable)")
    p.add_argument("--repeat", type=int, default=1, metavar="N", help="run each model N times on the same input")
    p.add_argument("--run", metavar="NAME", help="name the run folder; re-running the same name skips finished cells")
    p.add_argument("--timeout", type=int, default=900, metavar="SECONDS", help="give up on one cell after this long")
    p.add_argument("--force", action="store_true", help="redo cells that already finished")
    p.add_argument("--out", metavar="DIR", help="where runs are kept (default: data/model_tests)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.model_test", allow_abbrev=False,
                                     description="Compare how different models handle the program's steps.")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("docs", allow_abbrev=False, help="generate resumes and cover letters with each model")
    _common_arguments(d)
    d.add_argument("--mode", choices=MODES, default="standard", help="tailoring mode for every cell (default: standard)")
    d.add_argument("--compat", choices=("frozen", "own"), default="frozen",
                   help="bridge/auto mode: frozen = gaps and compatibility worked out once by --ref-model (default); "
                        "own = each model works out its own")
    d.add_argument("--ref-model", metavar="MODEL", help="model that does the frozen scoring (default: the first of --models)")
    d.set_defaults(func=cmd_docs)

    s = sub.add_parser("score", allow_abbrev=False, help="run the posting score and compatibility check with each model")
    _common_arguments(s)
    s.set_defaults(func=cmd_score)

    from tools.model_test import compare   # imported here because compare.py itself imports this module
    compare.register(sub)

    args = parser.parse_args()
    if getattr(args, "repeat", 1) < 1:
        parser.error("--repeat must be at least 1")
    args.func(args)
