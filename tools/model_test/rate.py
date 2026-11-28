"""Rate the resumes and cover letters the models wrote, blind, then see which model does best.

From the project folder:
    python -m tools.model_test rate --run friday                      # rate resumes and letters
    python -m tools.model_test rate --run friday --what letters       # only letters (or: resumes)
    python -m tools.model_test rate --run friday --profile software   # only one profile
    python -m tools.model_test rate --run friday --redo               # rate again what you already rated
    python -m tools.model_test rate --run friday --report             # just the results, no rating

For each posting and profile you see the models as Model A, B, C (the same letters as `compare --blind`), then rate each
resume and each letter from 0 to 10 and may add a short note. Every rating is saved the moment you give it
(<run>/ratings.jsonl), so quitting loses nothing. Anything you skip, or haven't reached, is offered again next time.
When you stop, the letters are revealed and the averages per model are printed.

The resume view shows what the model decides: the summary, the order of your skills and which projects were chosen.
Everything else in a resume is copied from your resume.json, so type d to read the whole resume if you want to.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from tools.model_test import compare

RATINGS_FILE = "ratings.jsonl"
KINDS = {"resumes": "resume", "letters": "letter"}

INSTRUCTIONS = """
Rate each one from 0 to 10 as something YOU would send:
    0 = unusable (invented facts, wrong, embarrassing)     5 = needs real editing     10 = send as it is
The models are hidden. Times and lengths are hidden too. Type d to read the full resume,
s to skip (it is offered again next time), q to stop and see the results.
"""


# ---------------------------------------------------------------------------------------------------- storage


def _key(rec: dict) -> tuple:
    return rec["kind"], rec["profile"], rec["posting"], rec["repeat"], rec["model"]


def load_ratings(run_dir: Path) -> dict:
    """{key: record}; when something was rated twice (--redo) the later rating counts."""
    path, out = run_dir / RATINGS_FILE, {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                out[_key(rec)] = rec
            except (json.JSONDecodeError, KeyError):
                continue   # a half-written last line must not lose the rest
    return out


def save_rating(run_dir: Path, rec: dict) -> None:
    with open(run_dir / RATINGS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ------------------------------------------------------------------------------------------------------ asking


def ask_score(prompt: str, show_full, ask=input):
    """("score", 0-10) | ("skip", None) | ("quit", None). d shows the full text and asks again."""
    while True:
        try:
            reply = ask(prompt).strip().lower()
        except EOFError:
            return "quit", None
        if reply in ("", "s"):
            return "skip", None
        if reply == "q":
            return "quit", None
        if reply == "d":
            show_full()
            continue
        try:
            value = float(reply)
        except ValueError:
            value = -1
        if 0 <= value <= 10:
            return "score", round(value, 1)
        print("  Type a number from 0 to 10, d for the full text, s to skip, q to stop and save.")


# ----------------------------------------------------------------------------------------------------- report


def _avg(values: list[float]) -> str:
    return f"{sum(values) / len(values):.1f} ({len(values)})" if values else "-"


def _table(headers: list[str], rows: list[list[str]]) -> None:
    lines = [headers] + rows
    widths = [max(len(str(line[i])) for line in lines) for i in range(len(headers))]
    for n, line in enumerate(lines):
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(line, widths)).rstrip())
        if n == 0:
            print("  " + "  ".join("-" * w for w in widths))


def print_report(run_dir: Path, meta: dict, ratings: dict) -> None:
    if not ratings:
        print("\n[RATE] No ratings yet.")
        return
    scores: dict = {}   # (profile, model) -> {"resume": [...], "letter": [...]}
    for rec in ratings.values():
        scores.setdefault((rec["profile"], rec["model"]), {"resume": [], "letter": []})[rec["kind"]].append(rec["score"])
    fallbacks: dict = {}
    for cell in meta["cells"]:
        if cell.get("ok") and cell.get("summary_fallback"):
            k = (cell["profile"], cell["model"])
            fallbacks[k] = fallbacks.get(k, 0) + 1

    print(f"\n[RATE] Results for run '{run_dir.name}' (the models are now named). Average score, with how many ratings in ( ).")
    rows = []
    for model in meta["models"]:
        mine = {k: v for k, v in scores.items() if k[1] == model}
        if not mine:
            continue
        for profile in meta["profiles"]:
            s = mine.get((profile, model))
            if s:
                rows.append([profile, model, _avg(s["resume"]), _avg(s["letter"]), str(fallbacks.get((profile, model), 0))])
        if len(mine) > 1:
            both = {"resume": [x for v in mine.values() for x in v["resume"]], "letter": [x for v in mine.values() for x in v["letter"]]}
            rows.append(["all profiles", model, _avg(both["resume"]), _avg(both["letter"]),
                         str(sum(n for (p, m), n in fallbacks.items() if m == model))])
    print()
    _table(["profile", "model", "resume", "letter", "summary fallbacks"], rows)

    noted = sorted((r for r in ratings.values() if r.get("note")), key=lambda r: r["score"])
    if noted:
        print("\n  Your notes, lowest score first:")
        for r in noted:
            print(f"   {r['score']:>4g}  {r['kind']:<6} {r['model']} | {r['profile']} | {r['posting'][:40]}: {r['note']}")


# ---------------------------------------------------------------------------------------------------- command


def cmd_rate(args) -> None:
    run_dir = compare.find_run(args.run, args.out)
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if args.report:
        print_report(run_dir, meta, load_ratings(run_dir))
        return

    kinds = [KINDS[w] for w in dict.fromkeys(args.what or ["resumes", "letters"])]
    groups = compare.load_groups(meta, args.profile, args.posting, args.models, args.rep)
    if not groups:
        raise SystemExit(f"[RATE] Nothing matches in run '{run_dir.name}' (repeat {args.rep}). "
                         f"Postings: {', '.join(p['id'] for p in meta['postings'])}. Profiles: {', '.join(meta['profiles'])}.")

    ratings = load_ratings(run_dir)
    width = args.width or max(80, min(shutil.get_terminal_size((120, 24)).columns - 1, 200))
    postings = {p["id"]: p for p in meta["postings"]}
    print(INSTRUCTIONS)
    stopped, done_now = False, 0

    try:
        for gi, ((posting_id, profile), rows) in enumerate(groups.items(), 1):
            # the same letters as `compare --blind`; models that failed keep their letter but can't be rated
            labels = compare.blind_labels(run_dir, f"{profile}|{posting_id}|r{args.rep}", [r["model"] for r in rows])
            letter_of = {m: letter for letter, m in labels.items()}
            usable = sorted((r for r in rows if r["ok"]), key=lambda r: letter_of[r["model"]])
            results = {r["model"]: compare.load_result(run_dir, r) for r in usable}

            def todo(kind):
                return [r for r in usable if args.redo or (kind, profile, posting_id, args.rep, r["model"]) not in ratings]

            if not any(todo(k) for k in kinds):
                continue
            post = postings.get(posting_id, {})
            print("\n" + "#" * width)
            print(f"# {post.get('title', posting_id)} at {post.get('company', '')} | profile: {profile} | {gi}/{len(groups)}")
            print("#" * width)
            compare.print_group([f"Model {letter_of[r['model']]}" for r in usable], [results[r["model"]] for r in usable],
                                [""] * len(usable), width, stats=False)

            for kind in kinds:
                for row in todo(kind):
                    model, label = row["model"], letter_of[row["model"]]

                    def show_full(row=row, model=model):
                        text = compare.resume_text(run_dir, row, results[model])
                        print("\n" + (text or "  (could not read the resume file)") + "\n")

                    action, score = ask_score(f"\n  Rate the {kind} of Model {label} (0-10, d, s, q): ", show_full)
                    if action == "quit":
                        stopped = True
                        break
                    if action == "skip":
                        continue
                    try:
                        note = input("  Note (Enter for none): ").strip()
                    except EOFError:
                        note = ""
                    rec = {"kind": kind, "profile": profile, "posting": posting_id, "repeat": args.rep, "model": model,
                           "label": label, "score": score, "note": note, "at": datetime.now().isoformat(timespec="seconds")}
                    save_rating(run_dir, rec)
                    ratings[_key(rec)] = rec
                    done_now += 1
                if stopped:
                    break
            if stopped:
                break
    except KeyboardInterrupt:
        print("\n[RATE] Stopped. Everything you rated is saved.")

    print(f"\n[RATE] {done_now} new rating(s) saved to {run_dir / RATINGS_FILE}")
    print_report(run_dir, meta, ratings)


def register(sub) -> None:
    r = sub.add_parser("rate", allow_abbrev=False, help="rate the resumes and cover letters, blind")
    r.add_argument("--run", metavar="NAME", help="run folder name (default: the most recent run)")
    r.add_argument("--out", metavar="DIR", help="where runs are kept (default: data/model_tests)")
    r.add_argument("--what", nargs="+", choices=tuple(KINDS), help="what to rate (default: resumes and letters)")
    r.add_argument("--posting", metavar="ID", help="only this posting id")
    r.add_argument("--profile", metavar="NAME", help="only this profile")
    r.add_argument("--models", nargs="+", metavar="MODEL", help="only these models")
    r.add_argument("--r", dest="rep", type=int, default=1, metavar="N", help="which repeat to rate (default 1)")
    r.add_argument("--redo", action="store_true", help="rate again what you already rated (the new rating replaces the old)")
    r.add_argument("--report", action="store_true", help="show the results so far; rate nothing")
    r.add_argument("--width", type=int, metavar="COLUMNS", help="terminal width to lay out for")
    r.set_defaults(func=cmd_rate)
