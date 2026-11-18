"""Terminal output for the pipeline: stage headers, job lines, [TAG] lines and job blocks.

Everything prints in one column, INDENT spaces in, so a run reads top to bottom. Colors are bright
ANSI colors that read well on dark and light terminals; they switch off when the output is not a
terminal (piped to a file) or when NO_COLOR is set.
"""

import os
import re
import shutil
import sys
import textwrap

if os.name == "nt":
    os.system("")   # switches ANSI colors on in older Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

INDENT = "   "
LABEL = 8                                    # say() labels are padded to this width
WIDTH = max(74, min(100, shutil.get_terminal_size((74, 24)).columns - 2))   # stage rules and wrapped text
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

_CODES = {
    "red": "91", "green": "92", "yellow": "93", "blue": "94", "magenta": "95", "cyan": "96",
    "white": "97", "gray": "90", "orange": "38;5;208", "gold": "38;5;220", "pink": "38;5;213",
    "lime": "38;5;118", "sky": "38;5;117",
}

# Color of each [TAG] label. Anything not listed is white.
TAG_COLORS = {
    "SCRAPER": "cyan", "FILTER": "yellow", "SCORER": "blue", "PIPELINE": "blue", "DEDUPE": "gray",
    "COMPAT": "sky", "DOCS": "magenta", "APPLY": "green", "BRIDGE": "orange", "CSV": "gold",
    "SUMMARY": "white", "TRACK": "pink",
}

_DECISIONS = {"ok": ("✔", "green"), "bad": ("✗", "red"), "skip": ("≡", "gray"), "warn": ("⚠", "yellow")}
_ANSI = re.compile(r"\033\[[0-9;]*m")


def paint(text, color: str, bold: bool = False) -> str:
    if not COLOR:
        return str(text)
    return f"\033[{'1;' if bold else ''}{_CODES[color]}m{text}\033[0m"


def visible_len(text: str) -> int:
    return len(_ANSI.sub("", text))


def wrap(text: str, first: str = INDENT, rest: str | None = None, color: str | None = None,
         bold: bool = False, w: int | None = None) -> str:
    """Wrap plain text; first/rest are the leading text of the first and following lines."""
    rest = INDENT if rest is None else rest
    w = w or WIDTH
    room = w - max(visible_len(first), visible_len(rest))
    lines = []
    for part in str(text).split("\n"):   # explicit line breaks are kept
        lines += textwrap.wrap(" ".join(part.split()), room, break_long_words=False,
                               break_on_hyphens=False) or ([""] if lines else [])
    lines = lines or [""]
    body = [paint(ln, color, bold) if color else ln for ln in lines]
    return "\n".join([first + body[0]] + [rest + ln for ln in body[1:]])


def score_color(score) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "gray"
    return "green" if score >= 7 else "yellow" if score >= 5 else "gray"


def fmt_score(score) -> str:
    """7 -> '7.0', 6.15 -> '6.2'; lines up in a column."""
    try:
        return f"{float(score):.1f}"
    except (TypeError, ValueError):
        return "n/a"


def cmd(text: str) -> str:
    """A shell command the user can run."""
    return paint(text, "cyan", True)


# ------------------------------------------------------------------------------------ building blocks


def banner(profile: str, mode: str, model: str, name: str, min_score, when: str) -> None:
    """The box at the top of a run."""
    rows = [("profile", profile), ("mode", mode), ("model", model), ("resume", name),
            ("documents", f"for jobs scoring {min_score:g}+"), ("started", when)]
    inner = max(len("JOB SCRAPER"), *(11 + len(str(v)) for _, v in rows)) + 4
    edge = lambda s: paint(s, "blue", True)
    print()
    print(" " + edge("┏" + "━" * inner + "┓"))
    print(" " + edge("┃") + "  " + paint("JOB SCRAPER".ljust(inner - 2), "white", True) + edge("┃"))
    for key, value in rows:
        text = paint(key.ljust(11), "gray") + paint(str(value), "white")
        print(" " + edge("┃") + "  " + text + " " * (inner - 2 - visible_len(text)) + edge("┃"))
    print(" " + edge("┗" + "━" * inner + "┛"))


def step(n, title: str, desc: str = "", right: str = "") -> None:
    """ ━━ 2  PRE-FILTER ━━━━━━━━   (n=None leaves the number out; right is shown at the end of the rule)"""
    head = f" ━━ {n}  {title} " if n is not None else f" ━━ {title} "
    tail = f" {right}" if right else ""
    fill = max(3, WIDTH - len(head) - len(tail))
    print()
    print(paint(" ━━ ", "blue", True) + paint(head[4:], "white", True)
          + paint("━" * fill, "blue", True) + paint(tail, "gray"))
    if desc:
        print()
        print(wrap(desc, color="gray"))


def job_head(title: str, company: str, url: str = "") -> None:
    """   Title · Company   (wrapped)  then the URL on its own line."""
    text = f"{title} · {company}" if company else title
    lines = textwrap.wrap(text, WIDTH - len(INDENT)) or [""]
    split = len(title)
    out, used = [], 0
    for ln in lines:   # title in bold white, the company part in white
        start = used
        used += len(ln) + 1
        if start >= split:
            out.append(paint(ln, "white"))
        elif start + len(ln) <= split:
            out.append(paint(ln, "white", True))
        else:
            cut = split - start
            out.append(paint(ln[:cut], "white", True) + paint(ln[cut:], "white"))
    print("\n".join(INDENT + ln for ln in out))
    if url:
        print(INDENT + paint(url, "gray"))


def decision(kind: str, text: str) -> None:
    """   ✔ scored: ...   The word before the first ':' is bold in the decision's color."""
    mark, color = _DECISIONS.get(kind, ("•", "white"))
    word, sep, rest = text.partition(":")
    lead = INDENT + paint(mark, color, True) + " "
    if sep:
        body = textwrap.wrap(f"{word}:{rest}", WIDTH - len(INDENT) - 2) or [""]
        first = body[0]
        first = paint(first[:len(word) + 1], color, True) + first[len(word) + 1:]
        print("\n".join([lead + first] + [INDENT + "  " + ln for ln in body[1:]]))
    else:
        print(wrap(text, lead, INDENT + "  ", color=color))


def say(label: str, text: str, color: str | None = None) -> None:
    """   found    84 unique jobs ...   (label gray, padded to LABEL)"""
    first = INDENT + paint(label.ljust(LABEL), "gray") + " "
    print(wrap(text, first, INDENT + " " * (LABEL + 1), color=color))


def note(text: str) -> None:
    print(wrap(text, color="gray"))


def tag(name: str, text: str = "") -> None:
    """   [SCRAPER] text   with the tag in its own color."""
    color = TAG_COLORS.get(name.upper(), "white")
    label = paint("[", "gray") + paint(name.upper(), color, True) + paint("]", "gray")
    first = INDENT + label + " "
    print(wrap(text, first, INDENT + " " * (len(name) + 3)) if text else INDENT + label)


def section(title: str, extra: str = "") -> str:
    """A bold heading inside a stage, e.g. 'BEST NEW MATCHES (5+)'."""
    return INDENT + paint(title, "white", True) + (f"  {extra}" if extra else "")


# ----------------------------------------------------------------------------------- job blocks


def _field(label: str, value: str, color: str | None = None, bold: bool = False, w: int | None = None) -> str:
    first = INDENT + paint(label.ljust(LABEL), "gray") + " "
    return wrap(value, first, INDENT + " " * (LABEL + 1), color=color, bold=bold, w=w)


def _bullets(label: str, items: list[str], color: str | None = None, w: int | None = None) -> list[str]:
    """First item next to the label, the rest as '→ item' lines below it."""
    pad = INDENT + " " * (LABEL + 1)
    out = [_field(label, items[0], color, w=w)]
    for item in items[1:]:
        out.append(wrap(item, pad + paint("→ ", "gray"), pad + "  ", color=color, w=w))
    return out


def _site(job: dict) -> str:
    url = job.get("apply_url") if (job.get("apply_url") or "").startswith("http") else job.get("job_url", "")
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


def _gaps(job: dict) -> list[str]:
    """The scorer's gaps plus the detailed check's missing requirements, without repeats. HARD ones first."""
    out, seen = [], set()
    missing = [m for m in (job.get("compat_missing") or []) if isinstance(m, dict) and m.get("text")]
    for m in sorted(missing, key=lambda m: not m.get("hard")):
        key = m["text"].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(("HARD " if m.get("hard") else "") + m["text"].strip())
    for g in job.get("gaps") or []:
        key = str(g).strip().lower()
        if key and key not in seen and not any(key in s or s in key for s in seen):
            seen.add(key)
            out.append(str(g).strip())
    return out[:5]


def _short_note(note: str) -> str:
    """'Asks for 2+ year(s) of experience' -> '2+ yrs experience', and similar, to keep the notes line short."""
    note = note.replace("Work setup mentioned: ", "")
    note = re.sub(r"^Asks for (\d+)\+ year\(s\) of experience$", r"\1+ yrs experience", note)
    note = re.sub(r"^Mentions a degree: ", "degree: ", note)
    return note


def job_block(job: dict, mode: str | None = None) -> None:
    """A job's full picture: score, details, a short description, requirements, gaps and notes.

    Uses only what is already stored (no model calls). Lines with nothing to show are left out.
    """
    from core.job_info import eligibility_flags, posting_summary, salary_from_text, special_notes, summary_points

    w = WIDTH
    desc = job.get("description") or ""
    url = job["apply_url"] if (job.get("apply_url") or "").startswith("http") else job.get("job_url", "")
    job_head(job.get("title", ""), job.get("company", ""), url)

    score = job.get("match_score")
    color = score_color(score)
    detail, rough = job.get("compat_detail_pct"), job.get("compat_pct")
    if detail is not None:
        compat = f"{detail:g}% compatibility" + (" (capped)" if job.get("compat_capped") else "")
        compat += f" ({rough:g}% rough)" if rough is not None else ""
    elif rough is not None:
        compat = f"{rough:g}% compatibility (rough)"
    else:
        compat = "compatibility n/a"
    print(INDENT + paint("score".ljust(LABEL), "gray") + " "
          + paint(f"{fmt_score(score)}/10", color, True) + paint(" suitability", color)
          + paint(" · ", "gray") + paint(compat, score_color((detail if detail is not None else rough or 0) / 10)))

    salary = job.get("salary") or salary_from_text(desc)
    details = [p for p in (job.get("location"), _site(job), f"{mode} documents" if mode else "") if p]
    if details:
        print(INDENT + paint("details".ljust(LABEL), "gray") + " "
              + paint(" · ", "gray").join(paint(p, "white") for p in details))
    if salary:
        print(INDENT + paint("salary".ljust(LABEL), "gray") + " " + paint(salary, "lime", True))

    about = posting_summary(desc, 2)
    if about:
        about = about if len(about) <= 260 else about[:257].rsplit(" ", 1)[0] + "..."
        print(_field("about", about, w=w))

    reqs = summary_points(desc, per_section=3, width=110).get("Requirements", [])
    if reqs:
        print("\n".join(_bullets("requires", reqs, w=w)))

    has = [str(s) for s in (job.get("matched_skills") or [])][:6]
    if has:
        print(_field("has", ", ".join(has), "green", w=w))

    gaps = _gaps(job)
    if gaps:
        pad = INDENT + " " * (LABEL + 1)
        for i, g in enumerate(gaps):
            hard = g.startswith("HARD ")
            text = g[5:] if hard else g
            lead = INDENT + paint("gaps".ljust(LABEL), "gray") + " " if i == 0 else pad + paint("→ ", "gray")
            if hard:
                lead += paint("HARD ", "red", True)
            print(wrap(text, lead, pad + "  ", color="red", w=w))

    notes = [_short_note(n) for n in special_notes(job.get("title", ""), job.get("location", ""), desc)]
    if notes:
        print(_field("notes", " · ".join(notes), "yellow", w=w))

    for flag in eligibility_flags(job.get("title", ""), desc):
        decision("warn", f"eligibility: {flag}")
