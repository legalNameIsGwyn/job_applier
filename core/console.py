"""Terminal output for the pipeline: stage headers, job lines, [TAG] lines and job blocks.

Everything prints in one column, INDENT spaces in, so a run reads top to bottom. Colors are bright
ANSI colors that read well on dark and light terminals; they switch off when the output is not a
terminal (piped to a file) or when NO_COLOR is set.
"""

import logging
import os
import re
import shutil
import sys
import textwrap

import config.settings as _settings

if os.name == "nt":
    os.system("")   # switches ANSI colors on in older Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

INDENT = "   "
LABEL = 8                                    # say() labels are padded to this width
WIDTH = max(74, min(100, shutil.get_terminal_size((74, 24)).columns - 2))   # stage rules and wrapped text
_force = getattr(_settings, "CONSOLE_COLOR", None)   # True = always color, False = never (config/settings.py)
COLOR = bool(_force) if _force is not None else sys.stdout.isatty() and not os.environ.get("NO_COLOR")

_CODES = {
    "red": "91", "green": "92", "yellow": "93", "blue": "94", "magenta": "95", "cyan": "96",
    "white": "97", "gray": "90", "orange": "38;5;208", "gold": "38;5;220", "pink": "38;5;213",
    "lime": "38;5;118", "sky": "38;5;117", "teal": "38;5;80", "lavender": "38;5;183", "mint": "38;5;114",
}

# What each part of the output is colored. These are the defaults; CONSOLE_COLORS in config/settings.py
# overrides any of them. A color is a name from `python -m core.console --colors`, a number 0-255, or "#rrggbb".
# "auto" (suitability, compat) means green / yellow / gray depending on how high the number is.

DEFAULT_COLORS = {
    "heading": "white", "label": "gray", "value": "white", "rule": "blue",
    "job_title": "white", "company": "sky", "location": "teal", "suitability": "auto", "compat": "auto",
    "site": "pink", "docs": "lavender", "salary": "lime", "blocker": "red",
    "about": "blue", "requires": "gold", "has": "green", "gaps": "orange", "notes": "magenta", "link": "gray",
}

COLORS = {**DEFAULT_COLORS, **getattr(_settings, "CONSOLE_COLORS", {})}

# Color of each [TAG] label. Anything not listed is white. CONSOLE_TAG_COLORS in config/settings.py overrides.

TAG_COLORS = {
    "SCRAPER": "cyan", "FILTER": "yellow", "SCORER": "blue", "PIPELINE": "blue", "DEDUPE": "gray",
    "COMPAT": "sky", "DOCS": "magenta", "APPLY": "green", "BRIDGE": "orange", "CSV": "gold",
    "SUMMARY": "white", "TRACK": "pink",
}

TAG_COLORS.update({k.upper(): v for k, v in getattr(_settings, "CONSOLE_TAG_COLORS", {}).items()})

_DECISIONS = {"ok": ("✔", "green"), "bad": ("✗", "red"), "skip": ("≡", "gray"), "warn": ("⚠", "yellow")}
_ANSI = re.compile(r"\033\[[0-9;]*m")


def _code(color) -> str:
    """ANSI code for a color: a name from _CODES, a number 0-255, or '#rrggbb'. Anything else prints as white."""
    text = str(color).strip()
    if text in _CODES:
        return _CODES[text]
    if text.isdigit() and int(text) <= 255:
        return f"38;5;{int(text)}"
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return "38;2;{};{};{}".format(*(int(text[i:i + 2], 16) for i in (1, 3, 5)))
    return _CODES["white"]


def role(name: str, auto: str = "white") -> str:
    """The color set for a part of the output (DEFAULT_COLORS, CONSOLE_COLORS); 'auto' gives the color passed in."""
    color = COLORS.get(name, DEFAULT_COLORS.get(name, "white"))
    return auto if str(color) == "auto" else color


def paint(text, color: str, bold: bool = False) -> str:
    if not COLOR:
        return str(text)
    return f"\033[{'1;' if bold else ''}{_code(color)}m{text}\033[0m"


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
    """The slim header at the top of a run: a title, then two short rows of settings."""
    rows = [
        [("profile", profile), ("mode", mode), ("model", model)],
        [("resume", name), ("docs", f"{min_score:g}+"), ("started", when)],
    ]
    dot = paint("  ·  ", "gray")
    print()
    print(INDENT + paint("JOB SCRAPER", role("heading"), True))
    for row in rows:
        print(INDENT + dot.join(paint(k, role("label")) + " " + paint(str(v), role("value")) for k, v in row))


def step(n, title: str, desc: str = "", right: str = "") -> None:
    """ ━━ 2  PRE-FILTER ━━━━━━━━   (n=None leaves the number out; right is shown at the end of the rule)"""
    head = f" ━━ {n}  {title} " if n is not None else f" ━━ {title} "
    tail = f" {right}" if right else ""
    fill = max(3, WIDTH - len(head) - len(tail))
    print()
    print(paint(" ━━ ", role("rule"), True) + paint(head[4:], role("heading"), True)
          + paint("━" * fill, role("rule"), True) + paint(tail, "gray"))
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
    first = INDENT + paint(label.ljust(LABEL), role("label")) + " "
    print(wrap(text, first, INDENT + " " * (LABEL + 1), color=color))


def note(text: str) -> None:
    print(wrap(text, color="gray"))


def tag(name: str, text: str = "", kind: str | None = None) -> None:
    """   [SCRAPER] text   with the tag in its own color.

    kind "bad" or "warn" adds a red ✗ or a yellow ⚠ after the tag and colors the text to match.
    """
    color = TAG_COLORS.get(name.upper(), "white")
    label = paint("[", "gray") + paint(name.upper(), color, True) + paint("]", "gray")
    first, rest = INDENT + label + " ", INDENT + " " * (len(name) + 3)
    if not text:
        print(INDENT + label)
    elif kind in _DECISIONS:
        mark, mark_color = _DECISIONS[kind]
        print(wrap(text, first + paint(mark, mark_color, True) + " ", rest + "  ", color=mark_color))
    else:
        print(wrap(text, first, rest))


def section(title: str, extra: str = "") -> str:
    """A bold heading inside a stage, e.g. 'BEST NEW MATCHES (5+)'."""
    return INDENT + paint(title, role("heading"), True) + (f"  {extra}" if extra else "")


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

# ------------------------------------------------------------------------- library log messages


class _LibraryLogs(logging.Handler):
    """Shows warnings and errors from jobspy as [SCRAPER] lines instead of 'ERROR:jobspy.linkedin:...'."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            site = record.name.split(".", 1)[1] if "." in record.name else record.name
            tag("SCRAPER", f"{site}: {record.getMessage()}", "bad" if record.levelno >= logging.ERROR else "warn")
        except Exception:
            self.handleError(record)


def route_library_logs() -> None:
    """Send jobspy's own log messages through tag(). Its wording is kept; every message is shown."""
    lib = logging.getLogger("jobspy")
    lib.handlers = [h for h in lib.handlers if not isinstance(h, _LibraryLogs)] + [_LibraryLogs(logging.WARNING)]
    lib.propagate = False   # otherwise the root handler (core/scorer.py) prints each message a second time

# ------------------------------------------------------------------------------------- preview

SAMPLE_JOB = {
    "title": "Intermediate Developer (Web Content Administrator)",
    "company": "Example Tech Solutions, Inc",
    "location": "Springfield, VA, USA",
    "job_url": "https://careers.example.com/jobs/12345",
    "apply_url": None,
    "match_score": 6.0, "compat_pct": 76.9, "compat_detail_pct": 41.7, "compat_capped": False,
    "compat_missing": [
        {"text": "U.S. citizen", "hard": True, "required": True},
        {"text": "Three years of experience with HTML, jQuery, Web Services, and SharePoint Designer", "hard": False},
        {"text": "Experience working with end users for requirements gathering", "hard": False},
    ],
    "matched_skills": ["HTML5", "JavaScript", "SharePoint", "Manual Testing", "Quality Assurance"],
    "gaps": ["Two years of experience developing and implementing workflow systems"],
    "salary": "$55k-$70k/yr",
    "description": (
        "Example Tech Solutions specializes in the delivery of professional business and information management "
        "services. We offer government and commercial clients a comprehensive portfolio of services that identify, "
        "design and deliver technology solutions for their teams.\n\n"
        "Requirements\n"
        "- Associate's degree in a technical or related field, or an Information Technology (IT) software "
        "development certification\n"
        "- Three (3) years of experience with HyperText Markup Language (HTML), jQuery, Web Services, and "
        "SharePoint Designer\n"
        "- Two (2) years of experience developing and implementing workflow systems\n\n"
        "This is a contract position. U.S. citizenship is required.\n"
    ),
}


def demo() -> None:
    """python -m core.console   Prints every kind of output once, so you can check colors without running the pipeline."""
    from datetime import datetime

    banner("software", "SEMI-AUTO", "qwen2.5:7b", "Jane Doe", 5, datetime.now().strftime("%a %Y-%m-%d %H:%M"))
    step(1, "SCRAPE", "Searching linkedin, indeed for 2 search term(s) in Norfolk, VA.")
    print()
    for name in TAG_COLORS:
        tag(name, f"{name.title()} lines look like this")
    logging.getLogger("jobspy.linkedin").error("response status code 429 (blocked: use a proxy)")
    logging.getLogger("jobspy.linkedin").warning("empty page at start=20 (the end of the results, or throttled)")

    step(3, "SCORE", "One line per job.")
    print()
    job_head("Junior Software Engineer", "Example Tech Solutions, Inc", "https://careers.example.com/jobs/1")
    decision("ok", "scored: 7.4/10 suitability")
    decision("bad", "filtered: senior-level title ('Senior')")
    decision("skip", "duplicate: same posting as one already saved")
    decision("warn", "documents: no employer link found")
    say("found", "84 unique jobs across 2 sites, 12 new")
    note("Gray text explains a section.")

    step(5, "RESULTS", right="sample job")
    print()
    print(section("BEST NEW MATCHES (5+)", paint("1 shown", "gray")))
    print()
    job_block(SAMPLE_JOB, "bridge")

    print()
    print(section("COLORS IN USE", paint("change them in CONSOLE_COLORS, config/settings.py", "gray")))
    for name in DEFAULT_COLORS:
        shown = role(name, "gray")
        text = f"{name.ljust(12)} {COLORS.get(name, DEFAULT_COLORS[name])}"
        auto = "  (green / yellow / gray by the number)" if str(COLORS.get(name)) == "auto" else ""
        print(INDENT + paint("████", shown) + "  " + text + paint(auto, "gray"))
    print()


def colors(everything: bool = False) -> None:
    """python -m core.console --colors   Lists the color names (add 'all' for the numbers 0-255 too)."""
    print()
    print(section("COLOR NAMES", paint("use them in CONSOLE_COLORS and CONSOLE_TAG_COLORS (config/settings.py)", "gray")))
    for name in _CODES:
        print(INDENT + paint("████", name) + "  " + name)
    print()
    print(wrap('Or a number 0-255 (add "all" to list them), or "#rrggbb" for any color.', color="gray"))
    if everything:
        print()
        for start in range(0, 256, 12):
            print(INDENT + "".join(paint("██", n) + f" {n:<4}" for n in range(start, min(start + 12, 256))))
    print()


if __name__ == "__main__":
    if "--colors" in sys.argv:
        colors("all" in sys.argv)
    else:
        demo()

route_library_logs()