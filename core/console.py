"""Console output shared by main.py, the scraper and the document maker: colors, symbols and layout.

Everything lines up with the title bar at the top of a run (up to the date), and anything longer
wraps onto the next line, indented under its own text.

Colors switch off by themselves when the output goes to a file or pipe, or when NO_COLOR is set.
CONSOLE_COLOR in config/settings.py overrides that: True = always on, False = always off.
Symbols fall back to plain ASCII when the terminal can't show them; CONSOLE_UNICODE = False forces that.

See what it looks like in your terminal:   python -m core.console
"""

import os
import re
import shutil
import sys

import config.settings as _settings

if os.name == "nt":
    os.system("")   # switches ANSI colors on in older Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# "detail" is the color for secondary text (dates, labels, reasons). Pick it with CONSOLE_DETAIL_COLOR in
# config/settings.py: a name from PALETTE, or any number 0-255. Grey is only for paragraphs that explain a section.
PALETTE = {"lavender": "38;5;183", "orange": "38;5;208", "peach": "38;5;216", "gold": "38;5;179",
           "sky": "38;5;117", "teal": "38;5;80", "mint": "38;5;114", "pink": "95", "white": "97"}
_CODES = {"green": "32", "red": "31", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "grey": "90"}
_ANSI = re.compile(r"\033\[[0-9;]*m")
_layout = None   # width of the title bar; set by banner()


def color_on() -> bool:
    setting = getattr(_settings, "CONSOLE_COLOR", None)
    if setting is not None:
        return bool(setting)
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def unicode_on() -> bool:
    """CONSOLE_UNICODE in config/settings.py (True/False) overrides the automatic check."""
    setting = getattr(_settings, "CONSOLE_UNICODE", None)
    if setting is not None:
        return bool(setting)
    return (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf16", "utf32")


_FANCY = {"ok": "✔", "bad": "✗", "skip": "≡", "warn": "⚠", "arrow": "→", "dot": "·", "bar": "━"}
_PLAIN = {"ok": "+", "bad": "x", "skip": "=", "warn": "!", "arrow": "->", "dot": "-", "bar": "="}


def _code(color: str) -> str:
    if color != "detail":
        return _CODES[color]
    choice = getattr(_settings, "CONSOLE_DETAIL_COLOR", "lavender")
    if isinstance(choice, int) and 0 <= choice <= 255:
        return f"38;5;{choice}"
    return PALETTE.get(str(choice), PALETTE["lavender"])


def sym(name: str) -> str:
    return (_FANCY if unicode_on() else _PLAIN)[name]


def paint(text, color: str | None = None, bold: bool = False) -> str:
    """Wrap text in color and/or bold (plain text when colors are off)."""
    text = str(text)
    if not color_on() or not (color or bold):
        return text
    codes = (["1"] if bold else []) + ([_code(color)] if color else [])
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def visible_len(text: str) -> int:
    return len(_ANSI.sub("", text))


def width() -> int:
    """Line width: the title bar's width, or the terminal's if that is narrower."""
    terminal = shutil.get_terminal_size((100, 20)).columns - 1
    return max(40, min(_layout or 74, terminal))


def shorten(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    return text[: max(n - 1, 1)].rstrip() + "…" if unicode_on() else text[: n - 3] + "..."


# --------------------------------------------------------------------------------- wrapping
# A "segment" is (text, color, bold). Text is split into words, colors stay with their words, and
# lines break only between words (a word longer than a whole line, such as a URL, is cut).


def _words(segments) -> list:
    words, cur = [], []
    for text, color, bold in segments:
        buf = ""
        for ch in str(text):
            if ch.isspace():
                if buf:
                    cur.append((buf, color, bold))
                    buf = ""
                if cur:
                    words.append(cur)
                    cur = []
            else:
                buf += ch
        if buf:
            cur.append((buf, color, bold))
    if cur:
        words.append(cur)
    return words


def _wlen(word) -> int:
    return sum(len(t) for t, _, _ in word)


def _split(word, n: int) -> list:
    chars = [(ch, c, b) for t, c, b in word for ch in t]
    chunks = []
    for i in range(0, len(chars), n):
        part = []
        for ch, c, b in chars[i:i + n]:
            if part and part[-1][1:] == (c, b):
                part[-1] = (part[-1][0] + ch, c, b)
            else:
                part.append((ch, c, b))
        chunks.append(part)
    return chunks


def emit(segments, indent: str = "", prefix=None) -> None:
    """Print text wrapped to width(). prefix (segments) is printed once; wrapped lines hang under the text."""
    prefix = prefix or []
    plen = sum(len(t) for t, _, _ in prefix)
    cont = indent + " " * plen
    room = max(width() - len(cont), 10)
    first = max(width() - len(indent) - plen, 10)
    lines, cur, cur_len, cap = [], [], 0, first

    def flush():
        nonlocal cur, cur_len, cap
        lines.append(cur)
        cur, cur_len, cap = [], 0, room

    for word in _words(segments):
        if cur and cur_len + 1 + _wlen(word) > cap:
            flush()
        if _wlen(word) > cap:
            chunks = _split(word, min(cap, room))
            for chunk in chunks[:-1]:
                cur = [chunk]
                flush()
            word = chunks[-1]
        cur_len += _wlen(word) + (1 if cur else 0)
        cur.append(word)
    if cur or not lines:
        flush()

    for i, words in enumerate(lines):
        head = indent + "".join(paint(t, c, b) for t, c, b in prefix) if i == 0 else cont
        print(head + " ".join("".join(paint(t, c, b) for t, c, b in w) for w in words))


# ------------------------------------------------------------------------------------- layout


def banner(profile: str, mode: str, model: str, resume_name: str, min_score: float, when: str) -> None:
    """The title bar. Every bar and line below is as wide as this first line, up to the date."""
    global _layout
    plain = f" JOB SCRAPER   profile: {profile}   mode: {mode}   {when}"
    _layout = max(len(plain), 60)
    print()
    print(f" {paint('JOB SCRAPER', None, True)}   profile: {paint(profile, 'cyan')}   mode: "
          f"{paint(mode, 'cyan', True)}   {paint(when, 'detail')}")
    dot = sym("dot")
    emit([(f"model {model} {dot} resume {resume_name} {dot} min score {min_score:g}", "detail", False)], " ")
    print()


def _bar(title: str) -> str:
    left = f"{sym('bar') * 2} {title} "
    return " " + paint(left + sym("bar") * max(width() - 1 - len(left), 3), "cyan", True)


def step(number: int, title: str, note: str = "") -> None:
    """A step header: ━━ 1  SCRAPE ━━━━━━━━. The note (a paragraph explaining the step) is grey."""
    print("\n" + _bar(f"{number}  {title}"))
    print()
    if note:
        emit([(note, "grey", False)], "   ")
        print()


def section(title: str) -> None:
    """A group header, for example STRONG FIT."""
    print("\n" + _bar(title))
    print()


def job_head(title: str, company: str, link: str = "") -> str:
    """Print 'Title · Company' and the link under it. Returns the indent for the detail lines."""
    emit([(title, None, True), (f" {sym('dot')} ", None, False), (company, None, False)], "   ")
    if link:
        emit([(link, "cyan", False)], "   ")
    return "   "


_KINDS = {"ok": "green", "bad": "red", "skip": "yellow", "warn": "yellow"}


def decision(kind: str, text: str, indent: str = "   ") -> None:
    """One result line under a job: ok / bad / skip / warn. 'rejected: reason' shows the reason in the detail color."""
    color = _KINDS[kind]
    head, sep, reason = text.partition(": ")
    segments = [(head, color, False)] + ([(": ", "detail", False), (reason, "detail", False)] if sep else [])
    emit(segments, indent, prefix=[(sym(kind) + " ", color, False)])


def line(label: str, value: str, indent: str = "   ", label_width: int = 9, color: str | None = None) -> None:
    """label   value  (for links, folders, missing requirements...). A long value wraps under itself."""
    emit([(value, color, False)], indent, prefix=[(label.ljust(label_width), "detail", False)])


def say(tag: str, text: str, color: str | None = None) -> None:
    """A status line: a bold colored tag, then the text."""
    emit([(text, None, False)], "   ", prefix=[(tag.ljust(9), color or "cyan", True)])


def note(text: str, indent: str = "   ") -> None:
    """A paragraph explaining something (grey)."""
    emit([(text, "grey", False)], indent)


def detail(text: str, indent: str = "   ") -> None:
    """Secondary information (detail color)."""
    emit([(text, "detail", False)], indent)


# ------------------------------------------------------------------------------------- demo


def demo() -> None:
    banner("software", "SEMI-AUTO", "qwen2.5:7b", "Gwyn L.", 5, "Tue 2026-11-17 20:05")

    step(1, "SCRAPE")
    say("linkedin", '"junior software engineer" · Norfolk, VA · 24 found')
    say("indeed", '"junior software engineer" · Norfolk, VA · 3 found')
    emit([("27 jobs from 4 searches ", None, False), (sym("arrow"), None, False),
          (" 19 unique ", None, False), (sym("arrow"), None, False), (" 11 new ", None, False),
          ("(8 seen before)", "detail", False)], "   ")

    step(2, "PRE-FILTER", "Title and company rules, checked before any description is downloaded.")
    pad = job_head("Senior Software Engineer", "Foo Inc", "https://www.linkedin.com/jobs/view/111")
    decision("bad", "rejected: senior title", pad)
    pad = job_head("Developer", "Robert Half", "https://www.linkedin.com/jobs/view/112")
    decision("bad", "rejected: staffing agency", pad)

    step(3, "DESCRIPTIONS", "Fetching the full posting for each job that is still in.")
    say("linkedin", "9 to fetch: 8 fetched, 1 failed (it is retried next run)")

    step(4, "SCORING", "Suitability is how well you fit this kind of job for your profile, out of 10. Compatibility is the share of the posting's listed requirements your resume meets.")
    pad = job_head("Junior Developer", "Acme Corp", "https://www.linkedin.com/jobs/view/123?refId=ByteString&trackingId=Zk3dQ2pXm1W8vY")
    decision("ok", "scored: suitability 7.2/10 · compatibility 64% · standard documents", pad)
    pad = job_head("Systems Analyst", "DoD Contractor", "https://www.linkedin.com/jobs/view/124")
    decision("bad", "rejected: requires security clearance", pad)
    pad = job_head("Backend Engineer", "Globex", "https://www.linkedin.com/jobs/view/127")
    decision("bad", "rejected: 5+ years of professional experience required (you have about 1 year)", pad)
    pad = job_head("Web Developer", "Bar LLC", "https://www.linkedin.com/jobs/view/125")
    decision("skip", "skipped: duplicate of Baz Inc", pad)
    pad = job_head("QA Analyst", "Initech", "https://www.linkedin.com/jobs/view/126")
    decision("warn", "scored: suitability 4.1/10 · below 5, so no documents", pad)

    step(5, "DOCUMENTS")
    pad = job_head("Junior Developer", "Acme Corp")
    line("mode", "standard", pad)
    line("folder", "Acme_Junior_Developer_a1b2c3", pad)
    print()
    pad = job_head("Web Analyst", "Initech")
    line("mode", "bridge", pad)
    line("bridge", "Supported end users daily as a full stack developer.", pad)
    decision("warn", "check the letter: invented number \"40%\"", pad)

    step(6, "SUMMARY")
    line("new", "11 jobs: 5 scored, 2 filtered, 1 duplicate, 1 failed", "   ")
    line("docs", "2 application folders created, 2 rows added to the CSV", "   ")
    line("csv", "profiles\\software\\applications.csv", "   ")
    print()
    note("Needs you:")
    detail("- 1 job failed scoring: python -m tools.rescore --failed-only")
    detail("- only 4 hand ratings: python -m tools.rating")

    for title, jobs in (("STRONG FIT", [("Junior Developer", "Acme Corp", "7.2", "64%", "standard",
                                         "https://boards.greenhouse.io/acme/jobs/123", "Acme_Junior_Developer_a1b2c3",
                                         "AWS certification", "")]),
                        ("STRETCH", [("Web Analyst", "Initech", "6.4", "41%", "bridge",
                                      "https://www.linkedin.com/jobs/view/456", "Initech_Web_Analyst_d4e5f6",
                                      "3+ years Java, SQL Server", "read the bridge line; letter warning: invented number")])):
        section(title)
        for i, (t, c, score, compat, mode, link, folder, missing, check) in enumerate(jobs):
            if i:
                print()
            pad = job_head(t, c)
            line("fit", f"suitability {score}/10 · compatibility {compat} · {mode}", pad)
            line("link", link, pad, color="cyan")
            line("folder", folder, pad)
            line("missing", missing, pad, color="yellow")
            if check:
                line("check", check, pad, color="yellow")
    section("NEXT STEPS")
    for n, text in enumerate(("Open profiles\\software\\applications.csv.",
                              "Read each cover letter (the model can be wrong) and any check lines.",
                              "Apply with the link, then write a status in the CSV (applied, rejected, skip...).",
                              "python -m tools.summary shows what's new at any time."), 1):
        emit([(text, None, False)], "   ", prefix=[(f"{n}  ", "detail", True)])


def colors(everything: bool = False) -> None:
    """Show the detail color options, so you can pick one for CONSOLE_DETAIL_COLOR."""
    def swatch(code, text):
        return f"\033[{code}m{text}\033[0m" if color_on() else text
    print('\n Pick one and set it in config/settings.py, for example:  CONSOLE_DETAIL_COLOR = "orange"\n')
    for name, code in PALETTE.items():
        print(f"   {name:<9} {swatch(code, 'rejected: requires security clearance')}   "
              f"{swatch(code, 'folder')}  Acme_Junior_Developer_a1b2c3")
    if everything:
        print("\n Or use any number from 16 to 255, for example:  CONSOLE_DETAIL_COLOR = 141\n")
        for row in range(16, 256, 12):
            print("  " + "".join(swatch(f"38;5;{n}", f"{n:>5}") for n in range(row, min(row + 12, 256))))
    print()


if __name__ == "__main__":
    if "--colors" in sys.argv:
        colors(everything="all" in sys.argv)
    else:
        demo()