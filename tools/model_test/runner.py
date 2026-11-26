"""Generate resumes and cover letters with several models and profiles, so you can compare them.

From the project folder:
    python -m tools.model_test docs --profiles software it_support --models qwen2.5:7b llama3.1:8b --url <job url>
    python -m tools.model_test docs --profiles software --models qwen2.5:7b llama3.1:8b --posting-file my_postings.json
    python -m tools.model_test docs ... --repeat 3          # same model, same input, 3 times: how much does it vary?
    python -m tools.model_test docs ... --run friday        # name the run; run it again and finished cells are skipped

Every combination of posting x profile x repeat is run by every model, one after another, through the program's own
create_application(). Results: data/model_tests/<run>/<profile>/<model>/<posting>/r<N>/ holds the two .docx files,
notes.txt, log.txt (what the program printed) and result.json (what the model returned, timings, warnings).
Nothing is written to your jobs database or to profiles/<name>/applications.
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


def run_cell(cell: dict, job_file: Path, mode: str, timeout: int, scratch_db: Path) -> dict:
    out: Path = cell["dir"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "tools.model_test.worker", "--profile", cell["profile"],
           "--job-file", str(job_file), "--out", str(out), "--mode", mode]
    # OLLAMA_MODEL is how config/settings.py picks the model; JOBS_DB points any stray database use at a scratch file.
    env = {**os.environ, "OLLAMA_MODEL": cell["model"], "JOBS_DB": str(scratch_db), "PYTHONUTF8": "1", "NO_COLOR": "1"}
    code = None
    with open(out / "log.txt", "wb") as log:
        try:
            code = subprocess.run(cmd, cwd=PROJECT_DIR, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            pass
    result_file = out / "result.json"
    if not result_file.exists():
        why = f"timed out after {timeout}s" if code is None else f"worker exited with code {code} and no result (see log.txt)"
        result_file.write_text(json.dumps({"ok": False, "error": why, "profile": cell["profile"]}), encoding="utf-8")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if result.get("ok") and result.get("model_used") != cell["model"]:
        result.update(ok=False, error=f"asked for model {cell['model']} but {result.get('model_used')} was used")
        result_file.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def _row(cell: dict, r: dict) -> dict:
    return {"profile": cell["profile"], "model": cell["model"], "posting": cell["posting"], "repeat": cell["repeat"],
            "dir": str(cell["dir"].relative_to(cell["run_dir"])), "ok": bool(r.get("ok")), "error": r.get("error"),
            "seconds": r.get("seconds"), "mode": r.get("mode"), "summary_fallback": r.get("summary_fallback"),
            "warnings": len(r.get("warnings") or []), "letter_words": r.get("letter_words"),
            "bridges": len(r.get("bridges") or []), "model_calls": len(r.get("ask_calls") or [])}


def summarize(rows: list[dict]) -> list[dict]:
    """One line per (profile, model)."""
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["profile"], r["model"]), []).append(r)
    out = []
    for (profile, model), g in groups.items():
        ok = [r for r in g if r["ok"]]
        avg = lambda key: round(sum(r[key] or 0 for r in ok) / len(ok), 1) if ok else None
        out.append({"profile": profile, "model": model, "cells": len(g), "ok": len(ok),
                    "avg_seconds": avg("seconds"), "summary_fallbacks": sum(1 for r in ok if r["summary_fallback"]),
                    "avg_warnings": avg("warnings"), "avg_letter_words": avg("letter_words")})
    return out


def print_summary(table: list[dict]) -> None:
    cols = [("profile", "profile"), ("model", "model"), ("ok", "ok"), ("avg_seconds", "secs"),
            ("summary_fallbacks", "summary fallbacks"), ("avg_warnings", "warnings"), ("avg_letter_words", "letter words")]
    lines = [[h for _, h in cols]] + [[f"{r['ok']}/{r['cells']}" if k == "ok" else str(r[k]) for k, _ in cols] for r in table]
    widths = [max(len(line[i]) for line in lines) for i in range(len(cols))]
    for i, line in enumerate(lines):
        print("  " + "  ".join(c.ljust(w) for c, w in zip(line, widths)))
        if i == 0:
            print("  " + "  ".join("-" * w for w in widths))


def cmd_docs(args) -> None:
    models = list(dict.fromkeys(args.models))
    profiles = list(dict.fromkeys(args.profiles))
    check_profiles(profiles)

    run_dir = Path(args.out or RUNS_DIR) / (args.run or datetime.now().strftime("%Y%m%d-%H%M%S"))
    saved = run_dir / "postings.json"
    found = []
    try:
        for f in args.posting_file or []:
            found += postings_mod.from_file(f)
        if args.url:
            found += postings_mod.from_database(args.url)
    except ValueError as e:
        raise SystemExit(f"[MODEL TEST] {e}")
    if not found and saved.is_file():
        found = json.loads(saved.read_text(encoding="utf-8"))   # resuming a named run
    found = postings_mod.unique(found)
    if not found:
        raise SystemExit("[MODEL TEST] Give at least one posting: --url JOB_URL (scraped) or --posting-file FILE.json")
    if args.mode == "bridge" and not any(p.get("gaps") or p.get("compat_missing") for p in found):
        print("[MODEL TEST] Note: bridge mode needs each posting's gaps (\"gaps\" in a posting file). Without them the "
              "standard letter is written.")
    check_models(models)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "postings").mkdir(exist_ok=True)
    saved.write_text(json.dumps(found, indent=1), encoding="utf-8")
    for p in found:
        (run_dir / "postings" / f"{p['id']}.json").write_text(json.dumps(p, indent=1), encoding="utf-8")

    # Every model sees the same input before the next input starts, so an interrupted run still compares fairly.
    cells = [{"profile": prof, "model": m, "posting": p["id"], "repeat": r, "run_dir": run_dir,
              "dir": run_dir / prof / _safe(m) / p["id"] / f"r{r}"}
             for p in found for prof in profiles for r in range(1, args.repeat + 1) for m in models]
    print(f"[MODEL TEST] run '{run_dir.name}': {len(found)} posting(s) x {len(profiles)} profile(s) x {args.repeat} repeat(s) "
          f"x {len(models)} model(s) = {len(cells)} cell(s), mode {args.mode}")

    scratch_db = run_dir / "_unused.sqlite"
    rows, failures_in_a_row = [], 0
    meta = {"run": run_dir.name, "started": datetime.now().isoformat(timespec="seconds"), "mode": args.mode,
            "profiles": profiles, "models": models, "repeat": args.repeat,
            "postings": [{k: p[k] for k in ("id", "title", "company", "job_url")} for p in found]}

    def save(done: bool) -> None:
        (run_dir / "run.json").write_text(json.dumps({**meta, "finished": done, "cells": rows, "summary": summarize(rows)},
                                                      indent=1), encoding="utf-8")

    try:
        for n, cell in enumerate(cells, 1):
            label = f"{cell['profile']} | {cell['model']} | {cell['posting']} | r{cell['repeat']}"
            previous = cell["dir"] / "result.json"
            if previous.is_file() and not args.force:
                old = json.loads(previous.read_text(encoding="utf-8"))
                if old.get("ok"):
                    print(f"[{n}/{len(cells)}] skipped (already done): {label}")
                    rows.append(_row(cell, old))
                    continue
            print(f"[{n}/{len(cells)}] {label} ...", end=" ", flush=True)
            started = time.time()
            result = run_cell(cell, run_dir / "postings" / f"{cell['posting']}.json", args.mode, args.timeout, scratch_db)
            rows.append(_row(cell, result))
            save(False)
            if result.get("ok"):
                failures_in_a_row = 0
                flag = "  (summary fell back to your original)" if result.get("summary_fallback") else ""
                print(f"ok {time.time() - started:.0f}s{flag}")
            else:
                failures_in_a_row += 1
                print(f"FAILED: {result.get('error')}")
                if failures_in_a_row >= 3:
                    print("[MODEL TEST] Stopped: 3 failures in a row. Is Ollama running? See log.txt in the failed folders.")
                    break
    except KeyboardInterrupt:
        print("\n[MODEL TEST] Interrupted. Run the same command with --run " + run_dir.name + " to continue.")
    save(len(rows) == len(cells))

    table = summarize(rows)
    if table:
        print()
        print_summary(table)
    print(f"\n[MODEL TEST] Results: {run_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.model_test", allow_abbrev=False,
                                     description="Compare how different models handle the program's steps.")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("docs", allow_abbrev=False, help="generate resumes and cover letters with each model")
    d.add_argument("--profiles", nargs="+", required=True, metavar="NAME", help="profiles to test (each uses its own resume.json)")
    d.add_argument("--models", nargs="+", required=True, metavar="MODEL", help="Ollama model names, e.g. qwen2.5:7b")
    d.add_argument("--url", action="append", metavar="JOB_URL", help="a scraped posting from your database (repeatable)")
    d.add_argument("--posting-file", action="append", metavar="FILE", help="JSON file of postings you provide (repeatable)")
    d.add_argument("--mode", choices=MODES, default="standard", help="tailoring mode for every cell (default: standard)")
    d.add_argument("--repeat", type=int, default=1, metavar="N", help="run each model N times on the same input")
    d.add_argument("--run", metavar="NAME", help="name the run folder; re-running the same name skips finished cells")
    d.add_argument("--timeout", type=int, default=900, metavar="SECONDS", help="give up on one cell after this long")
    d.add_argument("--force", action="store_true", help="redo cells that already finished")
    d.add_argument("--out", metavar="DIR", help="where runs are kept (default: data/model_tests)")
    d.set_defaults(func=cmd_docs)

    args = parser.parse_args()
    if getattr(args, "repeat", 1) < 1:
        parser.error("--repeat must be at least 1")
    args.func(args)
