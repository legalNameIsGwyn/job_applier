"""Look at what different models produced for the same posting and profile, side by side.
Works on runs made by `docs` (resumes and letters) and by `score` (job score, gaps, compatibility).

From the project folder:
    python -m tools.model_test compare --run friday                    # terminal, every posting and profile in the run
    python -m tools.model_test compare --run friday --blind            # models shown as A, B, C in a random order
    python -m tools.model_test compare --run friday --blind --reveal   # print which letter was which model
    python -m tools.model_test compare --run friday --html             # one page you open in a browser (compare.html)
    python -m tools.model_test compare --run friday --posting ID --profile software --models qwen2.5:7b llama3.1:8b
    python -m tools.model_test compare --run friday --r 2              # the 2nd repeat instead of the 1st
    python -m tools.model_test compare --run friday --full             # also print each full resume

Without --run the most recent run is used. Blind letters are drawn once per posting and profile and saved in the run
folder (blind_key.json), so they stay the same every time you look.
Blind mode hides time, mode and length; the text itself and any warnings can still give a model away.
"""

import html
import json
import random
import shutil
import sys
import textwrap
from itertools import zip_longest
from pathlib import Path

from tools.model_test.runner import RUNS_DIR

MIN_COLUMN = 34   # narrower than this and the models are stacked instead of placed side by side


# ---------------------------------------------------------------------------------------------------- loading


def find_run(run: str | None, out: str | None) -> Path:
    base = Path(out or RUNS_DIR)
    if run:
        run_dir = base / run
    else:
        runs = list(base.glob("*/run.json"))
        if not runs:
            raise SystemExit(f"[COMPARE] No runs in {base}. Make one with: python -m tools.model_test docs ...")
        run_dir = max(runs, key=lambda p: p.stat().st_mtime).parent
        print(f"[COMPARE] Using the most recent run: {run_dir.name}")
    if not (run_dir / "run.json").is_file():
        have = ", ".join(sorted(p.parent.name for p in base.glob("*/run.json"))) or "none"
        raise SystemExit(f"[COMPARE] No run '{run_dir.name}' in {base}. Runs: {have}")
    return run_dir


def load_groups(meta: dict, profile, posting, models, rep: int) -> dict:
    """{(posting id, profile): [cell rows, in --models order]}"""
    order = {m: i for i, m in enumerate(meta["models"])}
    groups: dict = {}
    for row in meta["cells"]:
        if row["repeat"] != rep or (profile and row["profile"] != profile) or (posting and row["posting"] != posting):
            continue
        if models and row["model"] not in models:
            continue
        groups.setdefault((row["posting"], row["profile"]), []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: order.get(r["model"], 99))
    return groups


def load_result(run_dir: Path, row: dict) -> dict:
    f = run_dir / row["dir"] / "result.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"ok": False, "error": "no result.json"}


def resume_text(run_dir: Path, row: dict, result: dict) -> str:
    """The text of the generated resume .docx ('' if it can't be read)."""
    try:
        from docx import Document
        folder = run_dir / row["dir"] / result["folder"]
        path = next(folder.glob("*Resume.docx"))
        return "\n".join(p.text for p in Document(path).paragraphs if p.text.strip())
    except Exception:
        return ""


def blind_labels(run_dir: Path, key: str, models: list[str]) -> dict:
    """{"A": model, ...} drawn once per group and saved, so a group always shows the same letters."""
    path = run_dir / "blind_key.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if key not in saved or sorted(saved[key].values()) != sorted(models):
        shuffled = list(models)
        random.SystemRandom().shuffle(shuffled)
        saved[key] = {chr(65 + i): m for i, m in enumerate(shuffled)}
        path.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    return saved[key]


# --------------------------------------------------------------------------------------------- what a cell shows


VERDICT = {"yes": "met", "partial": "partial", "no": "MISSING"}


def score_sections(result: dict) -> list[tuple[str, list[str]]]:
    """What the posting score and the compatibility check returned."""
    out = []
    score = f"{result.get('match_score'):g} / 10" if result.get("match_score") is not None else "(none)"
    if result.get("blocked_reason"):
        score += f"  (set to 0 before the model was asked: {result['blocked_reason']})"
    out.append(("Job score", [score]))
    out.append(("Skills it matched", [", ".join(result.get("matched_skills") or []) or "(none)"]))
    out.append(("Gaps it listed", result.get("gaps") or ["(none)"]))
    parts = []
    if result.get("compat_pct") is not None:
        parts.append(f"rough {result['compat_pct']:g}%")
    if result.get("compat_detail_pct") is not None:
        parts.append(f"detailed {result['compat_detail_pct']:g}%" + (" (capped by a missing hard requirement)" if result.get("compat_capped") else ""))
    compat_lines = [" | ".join(parts) or "(not measured)"]
    if result.get("match_score") is not None and result.get("min_score") and 0 < result["match_score"] < result["min_score"]:
        compat_lines.append(f"(this score is below MIN_SCORE {result['min_score']:g}, where the program normally skips the "
                            "detailed check; it was run here so the models can be compared)")
    out.append(("Compatibility", compat_lines))
    if result.get("requirements"):
        out.append(("Requirements it found", [
            f"{VERDICT.get(r.get('met'), r.get('met'))}: {r['text']} ({r.get('kind')}, {'required' if r.get('required') else 'preferred'})"
            for r in result["requirements"]]))
    if result.get("drop_reason"):
        out.append(("The program would drop this job", [result["drop_reason"]]))
    if result.get("compat_error"):
        out.append(("Detailed check failed", [result["compat_error"]]))
    return out


def sections(result: dict) -> list[tuple[str, list[str]]]:
    """[(heading, paragraphs)] describing one result; the same content feeds the terminal and the HTML page."""
    if not result.get("ok"):
        return [("Error", [str(result.get("error"))])]
    if result.get("kind") == "score":
        return score_sections(result)
    t = result.get("tailored") or {}
    out = []
    if result.get("summary_fallback"):
        out.append(("Summary", ["(the model's summary was rejected, so your original summary was kept)"]))
    else:
        out.append(("Summary", [t.get("summary", "")]))
    skills = t.get("skills") or []
    out.append(("Skills (first 10 of the order used)", [", ".join(skills[:10]) + (" ..." if len(skills) > 10 else "")]))
    out.append(("Projects chosen", [", ".join(t.get("project_names") or []) or "(none)"]))
    if result.get("bridges"):
        out.append(("Bridge lines", [f"{b['requirement']}: {b['line']}" for b in result["bridges"]]))
    out.append(("Cover letter", result.get("paragraphs") or ["(none)"]))
    if result.get("warnings"):
        out.append(("Warnings", ["Warning: " + w for w in result["warnings"]]))
    return out


def status_line(result: dict) -> str:
    if not result.get("ok"):
        return "FAILED"
    if result.get("kind") == "score":
        return f"ok | {result.get('seconds')}s"
    return f"ok | {result.get('seconds')}s | mode {result.get('mode')} | letter {result.get('letter_words')} words"


# ---------------------------------------------------------------------------------------------------- terminal


def cell_lines(title: str, result: dict, width: int, resume: str = "", stats: bool = True) -> list[str]:
    """stats=False leaves out time, mode and length, which can hint at the model (used when blind)."""
    lines = [title[:width], "=" * min(len(title), width)]
    lines += (textwrap.wrap(status_line(result), width) if stats else []) + [""]
    for heading, paragraphs in sections(result):
        lines.append(heading.upper()[:width])
        for p in paragraphs:
            lines += (textwrap.wrap(p, width) or [""]) + [""]
    if resume:
        lines.append("FULL RESUME")
        for p in resume.splitlines():
            lines += textwrap.wrap(p, width) or [""]
    return lines


def print_group(titles: list[str], results: list[dict], resumes: list[str], width: int, stats: bool = True) -> None:
    n = len(titles)
    col = (width - 3 * (n - 1)) // n
    if n > 1 and col >= MIN_COLUMN:
        blocks = [cell_lines(t, r, col, x, stats) for t, r, x in zip(titles, results, resumes)]
        for row in zip_rows(blocks):
            print(" | ".join(cell.ljust(col) for cell in row).rstrip())
    else:
        for t, r, x in zip(titles, results, resumes):
            print("\n".join(cell_lines(t, r, width, x, stats)))
            print("-" * width)


def zip_rows(blocks: list[list[str]]):
    return zip_longest(*blocks, fillvalue="")


def pause(prompt: str, enabled: bool) -> None:
    if enabled and sys.stdin.isatty():
        try:
            input(prompt)
        except EOFError:
            pass


# -------------------------------------------------------------------------------------------------------- HTML

CSS = """
:root{--bg:#f6f6f3;--fg:#1c1c1a;--muted:#62625c;--card:#fff;--border:#d9d9d2;--accent:#1d5fa8;--warn:#8a4b00;--bad:#a12020}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#161614;--fg:#ecece6;--muted:#a3a39b;--card:#20201d;--border:#38382f;--accent:#7db3f0;--warn:#f0b35a;--bad:#f08a8a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1500px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.4rem;margin:0 0 4px} h2{font-size:1.15rem;margin:36px 0 2px} h3{font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:16px 0 4px}
.sub{color:var(--muted);margin:0 0 12px}
button{font:inherit;padding:6px 14px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:14px;align-items:start}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.card h4{margin:0;font-size:1.05rem;color:var(--accent)}
.status{color:var(--muted);font-size:.85rem;margin:2px 0 0}
.card p{margin:0 0 8px;overflow-wrap:anywhere}
.warn{color:var(--warn)} .bad{color:var(--bad);font-weight:600}
details{margin-top:12px} summary{cursor:pointer;color:var(--muted)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,Consolas,monospace;margin:8px 0 0}
"""


def html_card(title: str, real: str | None, result: dict, resume: str, stats: bool = True) -> str:
    esc = html.escape
    name = (f'<span class="model-name" data-label="{esc(title)}" data-real="{esc(real)}">{esc(title)}</span>'
            if real else esc(title))
    parts = [f'<div class="card"><h4>{name}</h4><div class="status">{esc(status_line(result)) if stats else ""}</div>']
    for heading, paragraphs in sections(result):
        cls = "bad" if heading == "Error" else "warn" if heading == "Warnings" else ""
        parts.append(f"<h3>{esc(heading)}</h3>")
        parts += [f'<p class="{cls}">{esc(p)}</p>' for p in paragraphs]
    if resume:
        parts.append(f"<details><summary>Full resume text</summary><pre>{esc(resume)}</pre></details>")
    return "".join(parts) + "</div>"


def build_html(run_dir: Path, meta: dict, groups: dict, rep: int, blind: bool) -> str:
    esc = html.escape
    postings = {p["id"]: p for p in meta["postings"]}
    body = [f"<h1>Model comparison: {esc(meta['run'])}</h1>",
            f'<p class="sub">{esc("scoring" if meta.get("kind") == "score" else "mode " + str(meta.get("mode")))} | repeat {rep} | '
            f'{"blind: models are shown as letters" if blind else "models named"}</p>']
    if blind:
        body.append('<button id="reveal">Reveal models</button>')
    for (posting_id, profile), rows in groups.items():
        post = postings.get(posting_id, {})
        body.append(f"<h2>{esc(post.get('title', posting_id))} at {esc(post.get('company', ''))}</h2>"
                    f'<p class="sub">profile: {esc(profile)}</p><div class="grid">')
        labels = blind_labels(run_dir, f"{profile}|{posting_id}|r{rep}", [r["model"] for r in rows]) if blind else {}
        by_model = {m: letter for letter, m in labels.items()}
        for row in (sorted(rows, key=lambda r: by_model[r["model"]]) if blind else rows):
            result = load_result(run_dir, row)
            title = f"Model {by_model[row['model']]}" if blind else row["model"]
            body.append(html_card(title, row["model"] if blind else None, result, resume_text(run_dir, row, result), not blind))
        body.append("</div>")
    script = ("<script>var b=document.getElementById('reveal');if(b){b.onclick=function(){"
              "document.querySelectorAll('.model-name').forEach(function(e){e.textContent=e.dataset.label+' = '+e.dataset.real});"
              "b.disabled=true}}</script>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Model comparison</title><style>{CSS}</style></head><body><main>{''.join(body)}</main>{script}</body></html>")


# ---------------------------------------------------------------------------------------------------- command


def cmd_compare(args) -> None:
    run_dir = find_run(args.run, args.out)
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    groups = load_groups(meta, args.profile, args.posting, args.models, args.rep)
    if not groups:
        ids = ", ".join(p["id"] for p in meta["postings"])
        raise SystemExit(f"[COMPARE] Nothing matches in run '{run_dir.name}' (repeat {args.rep}). "
                         f"Postings: {ids}. Profiles: {', '.join(meta['profiles'])}.")

    if args.html is not None:
        target = Path(args.html) if args.html else run_dir / "compare.html"
        target.write_text(build_html(run_dir, meta, groups, args.rep, args.blind), encoding="utf-8")
        print(f"[COMPARE] Wrote {target}. Open it in your browser."
              + ("  Models are hidden until you press Reveal." if args.blind else ""))
        return

    width = args.width or max(80, min(shutil.get_terminal_size((120, 24)).columns - 1, 200))
    postings = {p["id"]: p for p in meta["postings"]}
    items = list(groups.items())
    for i, ((posting_id, profile), rows) in enumerate(items, 1):
        post = postings.get(posting_id, {})
        print("\n" + "#" * width)
        print(f"# {post.get('title', posting_id)} at {post.get('company', '')} | profile: {profile} | repeat {args.rep}"
              f" | {i}/{len(items)}")
        print("#" * width)
        key = f"{profile}|{posting_id}|r{args.rep}"
        labels = blind_labels(run_dir, key, [r["model"] for r in rows]) if args.blind else {}
        by_model = {m: letter for letter, m in labels.items()}
        ordered = sorted(rows, key=lambda r: by_model.get(r["model"], "")) if args.blind else rows
        results = [load_result(run_dir, r) for r in ordered]
        resumes = [resume_text(run_dir, r, res) if args.full else "" for r, res in zip(ordered, results)]
        titles = [f"Model {by_model[r['model']]}" if args.blind else r["model"] for r in ordered]
        print_group(titles, results, resumes, width, stats=not args.blind)
        if args.blind:
            if args.reveal:
                print("Key: " + ", ".join(f"{letter} = {m}" for letter, m in sorted(labels.items())))
            else:
                pause("Press Enter to reveal which model was which ... ", not args.no_pause)
                if sys.stdin.isatty() and not args.no_pause:
                    print("Key: " + ", ".join(f"{letter} = {m}" for letter, m in sorted(labels.items())))
        if i < len(items):
            pause("Press Enter for the next one ... ", not args.no_pause)


def register(sub) -> None:
    c = sub.add_parser("compare", allow_abbrev=False, help="see the models' results side by side")
    c.add_argument("--run", metavar="NAME", help="run folder name (default: the most recent run)")
    c.add_argument("--out", metavar="DIR", help="where runs are kept (default: data/model_tests)")
    c.add_argument("--posting", metavar="ID", help="only this posting id (see run.json)")
    c.add_argument("--profile", metavar="NAME", help="only this profile")
    c.add_argument("--models", nargs="+", metavar="MODEL", help="only these models")
    c.add_argument("--r", dest="rep", type=int, default=1, metavar="N", help="which repeat to show (default 1)")
    c.add_argument("--blind", action="store_true", help="show models as A, B, C in a random order")
    c.add_argument("--reveal", action="store_true", help="with --blind: print the letter key without asking")
    c.add_argument("--html", nargs="?", const="", metavar="FILE", help="write a web page instead (default: <run>/compare.html)")
    c.add_argument("--full", action="store_true", help="also show each full resume (terminal)")
    c.add_argument("--no-pause", action="store_true", help="print everything without waiting for Enter")
    c.add_argument("--width", type=int, metavar="COLUMNS", help="terminal width to lay out for")
    c.set_defaults(func=cmd_compare)
