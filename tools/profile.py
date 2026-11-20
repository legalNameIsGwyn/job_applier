"""Create, inspect and check profiles.

    python -m tools.profile list                 # every profile, with its resume and data status
    python -m tools.profile new NAME             # guided setup: asks a few questions and writes the profile
    python -m tools.profile show NAME            # what the profile changes, and where each value comes from
    python -m tools.profile check NAME           # validate it without running anything
    python -m tools.profile rename OLD NEW       # move the folder and keep its scores, ratings and history

A profile is a folder, profiles/NAME/, holding profile.py (only the settings that differ from the shared
defaults), resume.json and applications/. It exists as soon as profile.py does. Use it with
python main.py --profile NAME (every other command takes --profile too).
"""

import os

os.environ["JOB_PROFILE"] = "_defaults"   # manage profiles without loading any of them (must come first)

import argparse
import importlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import config.settings as S
from config import profile_loader as PL

DB_PATH = S.DB_PATH
GENERIC = "_generic"

# ------------------------------------------------------------------------------------ appearance

if os.name == "nt":
    os.system("")   # switches ANSI colors on in older Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_COLOR = sys.stdout.isatty()
_CODES = {"blue": "94", "magenta": "95", "green": "92", "yellow": "93", "red": "91", "cyan": "96",
          "gray": "90", "white": "97"}


def paint(text, color: str, bold: bool = False) -> str:
    return f"\033[{'1;' if bold else ''}{_CODES[color]}m{text}\033[0m" if _COLOR else str(text)


def banner(title: str, subtitle: str = "") -> None:
    inner = max(len(title), len(subtitle)) + 4
    print(paint("┏" + "━" * inner + "┓", "blue"))
    print(paint("┃", "blue") + "  " + paint(title.ljust(inner - 2), "white", True) + paint("┃", "blue"))
    if subtitle:
        print(paint("┃", "blue") + "  " + paint(subtitle.ljust(inner - 2), "gray") + paint("┃", "blue"))
    print(paint("┗" + "━" * inner + "┛", "blue"))


def step(n: int, total: int, title: str) -> None:
    print()
    print(paint(f"Step {n} of {total}", "cyan", True) + "  " + paint("●" * n + "○" * (total - n), "blue"))
    print(paint(title, "white", True))


def good(text: str) -> str:
    return paint("✔ ", "green", True) + text


def bad(text: str) -> str:
    return paint("✖ ", "red", True) + text


def warn(text: str) -> str:
    return paint("! ", "yellow", True) + text


def note(text: str) -> None:
    print(paint("  " + text, "gray"))


def fail(message: str) -> None:
    raise SystemExit(bad(message))


def ask(prompt: str, default=None, required: bool = False, validate=None) -> str:
    shown = "" if default is None or default == "" else f" [{default}]"
    while True:
        try:
            raw = input(f"{paint('›', 'magenta', True)} {prompt}{paint(shown, 'gray')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\nCancelled. Nothing was written.")
        if not raw and shown:
            raw = str(default)
        if not raw and required:
            print(paint("  Please enter a value.", "red"))
            continue
        error = validate(raw) if validate and raw else None
        if error:
            print(paint(f"  {error}", "red"))
            continue
        return raw


def choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> int:
    for i, (label, hint) in enumerate(options, start=1):
        print(f"  {paint(i, 'cyan', True)}) {label}" + (paint(f"   {hint}", "gray") if hint else ""))
    check = lambda r: None if r.isdigit() and 1 <= int(r) <= len(options) else f"Enter a number from 1 to {len(options)}."
    return int(ask(prompt, default, validate=check))


def confirm(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt + (" (Y/n)" if default else " (y/N)"),
              validate=lambda r: None if r.lower() in ("y", "yes", "n", "no") else "Type y or n.")
    return default if not raw else raw.lower().startswith("y")


def as_list(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]", text) if p.strip()]


def short(value, width: int = 52) -> str:
    text = " ".join(str(value).split()) if not isinstance(value, str) else " ".join(value.split())
    if isinstance(value, str) and len(value) > 60:
        text = text[:width] + f"…  ({len(value)} characters)"
    elif len(text) > width + 20:
        text = text[:width + 20] + "…"
    return text


# ------------------------------------------------------------------------------------ settings

def default_value(key: str):
    """The shared default of a setting (None if it doesn't exist)."""
    stem = PL.known_names().get(key)
    if stem is None:
        return None
    return getattr(importlib.import_module(f"config.{stem}"), key, None)


def effective(res, key: str):
    return res.overrides[key] if res is not None and key in res.overrides else default_value(key)


def resume_path(name: str, res=None) -> Path:
    path = Path(res.overrides["RESUME_FILE"]) if res is not None and "RESUME_FILE" in res.overrides \
        else PL.profile_dir(name) / "resume.json"
    return path if path.is_absolute() else PL.PROJECT_DIR / path


def application_count(name: str) -> int:
    folder = PL.profile_dir(name) / "applications"
    return sum(1 for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else 0


def db_counts() -> dict:
    """{profile name: jobs it has scored}, read without changing the database."""
    try:
        con = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return dict(con.execute("SELECT p.name, COUNT(js.id) FROM profiles p "
                                    "LEFT JOIN job_scores js ON js.profile_id = p.id GROUP BY p.id").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        return {}


# ------------------------------------------------------------------------------------ prompts

_SCORING = """You are a hiring manager reviewing applications for [[LEVEL]] [[FIELD]] positions.
I have my resume and a job posting.

Resume summary (extracted facts ONLY - do NOT invent experience):
- Name: {name}
- Location: {location}
- Skills from resume: {skills}
- Experience ({n_roles} roles):
{experience_lines}

[[IMPORTANT]] Rate it 0 if it requires any clearance level or does not accept green card holders.

Job title: {job_title}
Company: {company}
Location: {job_location}
Description: {description}

Rate your match on a scale of 1-10. Provide:
- A numeric score (1-10)[[SCORE_NOTE]]
- Which skills from my resume match this job (list them)
- Any significant gaps I have compared to the job requirements

Respond with JSON only, using exactly these keys:
{{"match_score": <number 0-10>, "matched_skills": ["..."], "gaps": ["..."]}}"""

_TAILOR = """You are helping tailor an [[LEVEL]] [[FIELD]] resume to one job.

RESUME DATA:
{resume_facts}

JOB: {job_title} at {company}
{description}

{truth_rules}
{years_rule}
Return JSON with:
- "summary": 2 plain sentences, under 60 words, rewriting the resume summary to fit this job. Keep the degree and the real roles; do not add new claims. Where it is true, use the posting's own wording for my skills. No em dashes and no buzzwords (leverage, passionate, dynamic, robust).
- "relevant_skills": up to {max_skills} skills copied EXACTLY from the resume skills list, most relevant to this job first.
- "project_names": up to {max_projects} project names copied EXACTLY from the resume, most relevant first."""


def make_prompts(field: str, level: str) -> dict:
    """The scoring and tailoring prompts for a field. [[MARKERS]] are used instead of {} so the prompts'
    own {placeholders} survive."""
    entry = level == "entry-level"
    important = (f"IMPORTANT: This is an ENTRY-LEVEL {field} job search. Your match score should reflect whether my "
                 "skills and ANY actual experience make me suitable for junior/entry-level roles, not senior positions. "
                 "My Associate/Junior level roles count as entry-level experience. Do NOT heavily penalize gaps if I "
                 f"have relevant foundational skills for {field} work." if entry else
                 f"IMPORTANT: This is a MID-LEVEL {field} job search. Your match score should reflect whether my "
                 "skills and actual experience make me suitable for mid-level roles, not senior or lead positions.")
    note_text = ": Associate/Junior roles qualify you even at score 5" if entry else ""
    scoring = (_SCORING.replace("[[IMPORTANT]]", important).replace("[[SCORE_NOTE]]", note_text)
               .replace("[[LEVEL]]", level).replace("[[FIELD]]", field))
    tailor = _TAILOR.replace("[[LEVEL]]", level).replace("[[FIELD]]", field)
    return {"SCORING_PROMPT": scoring, "TAILOR_PROMPT": tailor}


# ------------------------------------------------------------------------------------ writing

_ORDER = ["SEARCH_TERMS", "LOCATION", "MAX_MIN_YEARS", "MIN_SCORE", "DEFAULT_MODEL_WEIGHT", "COMMON_TERMS",
          "SCORING_PROMPT", "TAILOR_PROMPT"]
_COMMENTS = {
    "SEARCH_TERMS": "what to search for (every term runs on every site)",
    "LOCATION": "where to search",
    "MAX_MIN_YEARS": "skip a posting only if EVERY experience requirement asks for more years than this",
    "MIN_SCORE": "one cutoff: documents are made, jobs are listed and applications offered at this score",
    "DEFAULT_MODEL_WEIGHT": "share of the score that comes from the model (the rest is keyword matching)",
    "COMMON_TERMS": "terms postings in this field often ask for (used for the keyword score and the gaps list)",
    "SCORING_PROMPT": "how the model scores a job against your resume (keep the {placeholders})",
    "TAILOR_PROMPT": "how the model tailors your resume summary and skills (keep the {placeholders})",
}


def py_value(value) -> str:
    if isinstance(value, Path):
        try:
            rel = value.resolve().relative_to(PL.PROJECT_DIR)
            return "PROJECT_DIR / " + " / ".join(repr(p) for p in rel.parts)
        except ValueError:
            return repr(str(value))
    if isinstance(value, str):
        if "\n" in value and '"""' not in value and "\\" not in value and not value.endswith('"'):
            return '"""' + value + '"""'
        return repr(value)
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, str) for v in value):
        return "[\n" + "".join(f"    {v!r},\n" for v in value) + "]"
    return repr(value)


def render_profile(name: str, summary: str, extends: str | None, values: dict) -> str:
    lines = [f'"""Profile {name}: {summary}.', "",
             "Only settings that differ from the shared defaults are listed. Edit freely, then run:",
             f"  python -m tools.profile check {name}",
             f"  python -m tools.profile show {name}",
             'To change something not listed here, copy its line from profiles/_generic/profile.py.', '"""', ""]
    if extends:
        lines += [f"EXTENDS = {extends!r}   # settings not listed below come from this profile", ""]
    keys = [k for k in _ORDER if k in values] + [k for k in values if k not in _ORDER]
    for key in keys:
        lines.append(f"# {_COMMENTS.get(key, key.lower().replace('_', ' '))}")
        lines.append(f"{key} = {py_value(values[key])}")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------ new


def cmd_new(name: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        fail("Profile names use lowercase letters, digits, - and _, and can't start with _ (that's for templates).")
    folder = PL.profile_dir(name)
    if PL.profile_file(name).exists():
        fail(f"Profile '{name}' already exists ({PL.profile_file(name)}). Edit that file, or pick another name.")
    existing = PL.list_profiles()
    keep_resume = (folder / "resume.json").is_file()
    total = 10

    banner(f"New profile: {name}", "a few questions, then it writes profiles\\" + name + "\\")
    note("Press Ctrl-C at any point to cancel; nothing is written until the end.")

    # 1 ---------------------------------------------------------------------------------------
    step(1, total, "Where should it start from?")
    options = [("Fresh", "the shared defaults and a blank resume template")]
    if existing:
        options += [("Copy an existing profile", "its settings and resume become yours to change"),
                    ("Extend an existing profile", "only the differences are stored; the rest follows the parent")]
    mode = ["fresh", "copy", "extend"][choose("Choose", options) - 1]
    source = source_res = None
    if mode != "fresh":
        print()
        source = existing[choose("Which one?", [(p, "") for p in existing]) - 1]
        try:
            source_res = PL.resolve(source)
        except PL.ProfileError as e:
            fail(str(e))
    base_res = source_res if mode == "extend" else None   # what "unchanged" means for each setting

    # 2 ---------------------------------------------------------------------------------------
    step(2, total, "What kind of jobs is this profile for?")
    note('A few words, like "IT support", "accounting" or "cloud engineering". Used in the generated prompts.')
    field = re.sub(r'[\\"{}]', "", ask("Field", required=True)).strip()

    # 3 ---------------------------------------------------------------------------------------
    step(3, total, "What level?")
    level = ["entry-level", "mid-level"][choose("Level", [("Entry-level", "junior, associate, first jobs"),
                                                         ("Mid-level", "a few years of experience expected")]) - 1]
    regenerate = True
    if mode != "fresh":
        print()
        regenerate = confirm(f"Write new scoring and tailoring prompts for {field}?")

    # 4 ---------------------------------------------------------------------------------------
    step(4, total, "What should it search for?")
    if source_res is not None:
        note(f"{source} searches for: " + ", ".join(effective(source_res, "SEARCH_TERMS") or []))
    note("Job titles, separated by commas. Each one is searched on every site.")
    terms = as_list(ask("Search terms", required=True))

    # 5 ---------------------------------------------------------------------------------------
    step(5, total, "Where?")
    location = ask("Location", effective(base_res or source_res, "LOCATION"))

    # 6 ---------------------------------------------------------------------------------------
    step(6, total, "How many years of experience is too many?")
    note("Postings asking for more than this are skipped without costing any model time.")
    years_default = effective(source_res, "MAX_MIN_YEARS") if source_res else (2 if level == "entry-level" else 6)
    years = int(ask("Years", years_default,
                    validate=lambda r: None if r.isdigit() and int(r) <= 30 else "Enter a whole number from 0 to 30."))

    # 7 ---------------------------------------------------------------------------------------
    step(7, total, "What score is good enough?")
    note("One cutoff for everything: documents are made, jobs are listed and applications are offered at this score or above.")

    def check_score(raw):
        try:
            return None if 0 <= float(raw) <= 10 else "Enter a number from 0 to 10."
        except ValueError:
            return "Enter a number from 0 to 10."
    min_score = float(ask("Minimum score (0-10)", effective(source_res, "MIN_SCORE") or S.MIN_SCORE, validate=check_score))

    # 8 ---------------------------------------------------------------------------------------
    step(8, total, "How much should keyword matching count?")
    note("The keyword score is how many of your resume's skills the posting mentions. It helps most when your")
    note("resume uses the same words as the postings. Percent of the final score (the rest comes from the model).")
    weight_default = round((1 - float(effective(source_res, "DEFAULT_MODEL_WEIGHT") or S.DEFAULT_MODEL_WEIGHT)) * 100)
    keyword_pct = int(ask("Keyword weight %", weight_default,
                          validate=lambda r: None if r.isdigit() and int(r) <= 100 else "Enter a whole number from 0 to 100."))

    # 9 ---------------------------------------------------------------------------------------
    step(9, total, "Words postings in this field often ask for (optional)")
    note('For example "Active Directory, ServiceNow, VPN". They feed the keyword score and the "gaps" list.')
    note("Press Enter to keep the current list.")
    common = as_list(ask("Common terms"))

    # 10 --------------------------------------------------------------------------------------
    step(10, total, "Resume")
    resume_from = None
    if keep_resume:
        print(good(f"Found a resume.json already in profiles\\{name}\\ and I'll keep it."))
    else:
        options = [("Copy the generic template", "then fill it in with your real details")]
        if source:
            options.append((f"Copy {source}'s resume", "then adjust it for this field"))
        options += [("Copy a resume.json from a path", ""), ("Skip for now", "commands stop until a resume is added")]
        pick = choose("Choose", options, default=2 if source else 1)
        labels = [o[0] for o in options]
        picked = labels[pick - 1]
        if picked.startswith("Copy the generic"):
            resume_from = PL.profile_dir(GENERIC) / "resume.json"
        elif picked.startswith("Copy ") and source and picked == f"Copy {source}'s resume":
            resume_from = resume_path(source, source_res)
        elif picked.startswith("Copy a resume"):
            def check_path(raw):
                p = Path(raw.strip('"'))
                if not p.is_file():
                    return "No file there."
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    return "That file isn't valid JSON."
            resume_from = Path(ask("Path to resume.json", required=True, validate=check_path).strip('"'))
        if resume_from is not None and not resume_from.is_file():
            fail(f"Can't find {resume_from} to copy.")

    # what to write: only differences from the base -------------------------------------------
    values: dict = {}
    if mode == "copy":
        values.update({k: v for k, v in source_res.overrides.items() if k not in ("RESUME_FILE", "APPLICATIONS_DIR")})

    def put(key, value, force=False):
        base = effective(base_res, key) if base_res else default_value(key)
        if force or value != base:
            values[key] = value
        else:
            values.pop(key, None)

    put("SEARCH_TERMS", terms, force=True)
    put("LOCATION", location)
    put("MAX_MIN_YEARS", years)
    put("MIN_SCORE", min_score if min_score != int(min_score) else int(min_score))
    put("DEFAULT_MODEL_WEIGHT", round(1 - keyword_pct / 100, 2))
    if common:
        put("COMMON_TERMS", common, force=True)
    if regenerate:
        for key, text in make_prompts(field, level).items():
            put(key, text, force=True)

    # review ----------------------------------------------------------------------------------
    print()
    banner("Review", f"profiles\\{name}\\profile.py")
    rows = [("Field", f"{field} ({level})"), ("Starts from", {"fresh": "defaults", "copy": f"a copy of {source}",
                                                           "extend": f"extends {source}"}[mode]),
            ("Search terms", ", ".join(terms)), ("Location", location), ("Max years asked", years),
            ("Minimum score", f"{min_score:g}"), ("Keyword weight", f"{keyword_pct}%"),
            ("Common terms", ", ".join(common) or "(unchanged)"),
            ("Prompts", "generated for this field" if regenerate else "unchanged"),
            ("Resume", "kept" if keep_resume else f"copied from {resume_from}" if resume_from else "NOT SET YET")]
    for label, value in rows:
        print(f"  {paint(label.ljust(16), 'cyan')} {value}")
    print()
    if not confirm("Create this profile?"):
        raise SystemExit("Cancelled. Nothing was written.")

    # write -----------------------------------------------------------------------------------
    (folder / "applications").mkdir(parents=True, exist_ok=True)
    PL.profile_file(name).write_text(
        render_profile(name, f"{field}, {level}", source if mode == "extend" else None, values), encoding="utf-8")
    if resume_from is not None:
        shutil.copyfile(resume_from, folder / "resume.json")

    print()
    print(good(f"Created profiles\\{name}\\  (profile.py" + (", resume.json" if (folder / "resume.json").is_file() else "")
               + ", applications\\)"))
    print()
    print(paint("Next", "white", True))
    if not (folder / "resume.json").is_file():
        print(f"  1. Add profiles\\{name}\\resume.json (copy profiles\\{GENERIC}\\resume.json and fill it in)")
    elif resume_from is not None and resume_from.parent.name == GENERIC:
        print(f"  1. Fill in profiles\\{name}\\resume.json with your real details (it's a template now)")
    else:
        print(f"  1. Adjust profiles\\{name}\\resume.json for {field} if needed")
    print(f"  2. python -m tools.profile check {name}")
    print(f"  3. python main.py --profile {name}")
    print(f"  4. python -m tools.rating --profile {name}      (rate ~10 jobs so the scores can be tuned)")


# ------------------------------------------------------------------------------------ show / list


def cmd_show(name: str) -> None:
    try:
        res = PL.resolve(name)
    except PL.ProfileError as e:
        fail(str(e))
    resume = resume_path(name, res)
    banner(f"Profile: {name}", " -> ".join(res.chain) + ("  (child -> parent)" if len(res.chain) > 1 else ""))
    print(f"  {paint('Folder', 'cyan')}        profiles\\{name}")
    print(f"  {paint('Resume', 'cyan')}        {resume}  " + (good("found").strip() if resume.is_file() else bad("MISSING").strip()))
    print(f"  {paint('Documents', 'cyan')}     {application_count(name)} application folder(s)")
    print(f"  {paint('Scored jobs', 'cyan')}   {db_counts().get(name, 0)}")
    problems = PL.problems(res)
    for p in problems:
        print("  " + bad(p))
    print()
    if not res.overrides:
        print(paint("  This profile changes nothing: every setting is the shared default.", "gray"))
        return
    print(paint(f"  {len(res.overrides)} setting(s) differ from the defaults", "white", True))
    for key in sorted(res.overrides):
        owner = res.origins[key]
        origin = paint(("this profile" if owner == name else f"from {owner}").ljust(16), "magenta")
        print(f"  {paint(key.ljust(24), 'cyan')} {origin} {short(res.overrides[key])}")
        print(f"  {' ' * 24} {' ' * 16} {paint('default: ' + short(default_value(key), 40), 'gray')}")


def cmd_list() -> None:
    names = PL.list_profiles(include_templates=True)
    counts = db_counts()
    banner("Profiles", f"{len(PL.list_profiles())} profile(s) in profiles\\")
    print(f"  default profile: {paint(S.DEFAULT_PROFILE, 'magenta', True)}  (config\\settings.py)")
    print()
    print(paint(f"  {'name':<18}{'resume':<9}{'terms':>6}{'min':>6}  {'extends':<14}{'docs':>5}{'jobs':>6}", "gray"))
    for name in names:
        try:
            res = PL.resolve(name)
        except PL.ProfileError:
            print(f"  {name:<18}" + bad("profile.py has an error: python -m tools.profile check " + name))
            continue
        terms = effective(res, "SEARCH_TERMS") or []
        mark = good("").strip() if resume_path(name, res).is_file() else bad("").strip()
        tag = paint("  template", "gray") if name.startswith("_") else ""
        print(f"  {name:<18}{mark:<9}{len(terms):>6}{effective(res, 'MIN_SCORE'):>6g}  {(res.extends or '-'):<14}"
              f"{application_count(name):>5}{counts.get(name, 0):>6}{tag}")
    leftovers = [n for n in counts if n not in names]
    if leftovers:
        print()
        for n in leftovers:
            print(warn(f"'{n}' has {counts[n]} scored job(s) in the database but no profile folder "
                       f"(restore profiles\\{n}\\ or clear it: python -m tools.clear db --profile {n})"))
    if not PL.list_profiles():
        print()
        print(paint("  No profiles yet. Create one with:  python -m tools.profile new NAME", "yellow"))


# ------------------------------------------------------------------------------------ check

_PROMPT_VALUES = {
    "SCORING_PROMPT": dict(name="x", location="x", skills="x", n_roles=1, experience_lines="x", job_title="x",
                           company="x", job_location="x", description="x"),
    "TAILOR_PROMPT": dict(resume_facts="x", job_title="x", company="x", description="x", truth_rules="x",
                          years_rule="", max_skills=1, max_projects=1),
    "LETTER_PROMPT": dict(name="x", resume_facts="x", job_title="x", company="x", job_location="x", description="x",
                          truth_rules="x", letter_structure="x", keyword_rule="", years_rule="",
                          authorization_rule="", style_rules="x"),
    "LETTER_KEYWORD_RULE": dict(keywords="x"),
    "LETTER_YEARS_RULE": dict(asked=1, have="1"),
    "LETTER_AUTHORIZATION_RULE": dict(work_authorization="x", availability_clause=""),
    "LETTER_AVAILABILITY_CLAUSE": dict(availability="x"),
    "SUMMARY_YEARS_RULE": {},
}


def run_checks(name: str) -> list[tuple[str, str, str]]:
    """[(ok | warn | fail, what was checked, detail)]"""
    out = []
    add = lambda level, what, detail="": out.append((level, what, detail))
    try:
        res = PL.resolve(name)
    except PL.ProfileError as e:
        return [("fail", "profile.py", str(e))]
    add("ok", "profile.py loads", "extends " + " -> ".join(res.chain[1:]) if len(res.chain) > 1 else "")

    found = PL.problems(res)
    for p in found:
        add("fail", "setting names", p)
    if not found:
        add("ok", "every setting name is real and changeable")
    if not res.overrides:
        add("warn", "overrides", "the profile changes nothing, so it searches and scores exactly like the defaults")

    # resume
    path = resume_path(name, res)
    if not path.is_file():
        add("fail", "resume", f"{path} doesn't exist (copy profiles\\{GENERIC}\\resume.json there and fill it in)")
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not str(data.get("name", "")).strip():
                add("fail", "resume", "resume.json has no \"name\"")
            elif data.get("name") == "Your Name" or "TEMPLATE" in str(data.get("_readme", "")):
                add("warn", "resume", "still the template: replace every value with your real details")
            else:
                add("ok", "resume.json is valid", f"{len(data.get('skills', []))} skills, "
                                                  f"{len(data.get('experience', []))} role(s), {len(data.get('projects', []))} project(s)")
            if data.get("name") and not data.get("skills"):
                add("warn", "resume", "no skills listed, so the keyword score will be 0 for every job")

            licenses = data.get("licenses")

            if licenses is None:
                add("warn", "licenses", "resume.json has no \"licenses\" list (for example a driver's license), so jobs that "
                                        "require one are flagged as missing. Use [] if you hold none")
                
            elif not isinstance(licenses, list) or not all(
                    (str(x.get("name", "")).strip() if isinstance(x, dict) else str(x).strip()) for x in licenses):
                add("warn", "licenses", "\"licenses\" must be a list and every license needs a \"name\"")
        except ValueError as e:
            add("fail", "resume", f"{path.name} isn't valid JSON: {e}")

    # search
    terms = effective(res, "SEARCH_TERMS")
    if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
        add("fail", "SEARCH_TERMS", "must be a non-empty list of strings")
    else:
        add("ok", "search terms", f"{len(terms)} term(s)")

    # numbers
    def number(key, low, high, integer=False):
        value = effective(res, key)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high \
            and (not integer or float(value).is_integer())
        add("ok" if ok else "fail", key, f"{value}" if ok else f"{value!r} should be a number from {low} to {high}")
    number("MIN_SCORE", 0, 10)
    number("MAX_MIN_YEARS", 0, 30, integer=True)
    number("DEFAULT_MODEL_WEIGHT", 0, 1)
    if effective(res, "MIN_RATINGS") and effective(res, "FULL_TRUST_RATINGS") and \
            effective(res, "MIN_RATINGS") > effective(res, "FULL_TRUST_RATINGS"):
        add("fail", "ratings", "MIN_RATINGS is larger than FULL_TRUST_RATINGS")

    # prompts
    for key, values in _PROMPT_VALUES.items():
        if key not in res.overrides:
            continue
        try:
            res.overrides[key].format(**values)
            add("ok", key, "fills in with every placeholder")
        except (KeyError, IndexError, ValueError, AttributeError) as e:
            add("fail", key, f"can't be filled in ({e!r}). Allowed: " + ", ".join("{" + k + "}" for k in values)
                + ". Write a literal brace as {{ or }}.")

    # patterns
    def regexes(key, patterns):
        bad_ones = []
        for p in patterns:
            try:
                re.compile(p)
            except re.error as e:
                bad_ones.append(f"{p!r}: {e}")
        add("fail" if bad_ones else "ok", key, "; ".join(bad_ones) if bad_ones else f"{len(patterns)} pattern(s) compile")
    try:
        if "SENIOR_TITLE_WORDS" in res.overrides:
            regexes("SENIOR_TITLE_WORDS", list(res.overrides["SENIOR_TITLE_WORDS"]))
        if "LEVEL_SUFFIX_PATTERN" in res.overrides:
            regexes("LEVEL_SUFFIX_PATTERN", [res.overrides["LEVEL_SUFFIX_PATTERN"]])
        if "BLOCKER_PATTERNS" in res.overrides:
            regexes("BLOCKER_PATTERNS", list(res.overrides["BLOCKER_PATTERNS"]))
        if "NOTE_PATTERNS" in res.overrides:
            regexes("NOTE_PATTERNS", [p for _, p in res.overrides["NOTE_PATTERNS"]])
        if "SLOP_PATTERNS" in res.overrides:
            regexes("SLOP_PATTERNS", list(res.overrides["SLOP_PATTERNS"].values()))
        if "ANSWER_RULES" in res.overrides:
            regexes("ANSWER_RULES", [rule[0] for rule in res.overrides["ANSWER_RULES"]])
    except (TypeError, ValueError, IndexError) as e:
        add("fail", "patterns", f"a pattern list has the wrong shape ({e})")

    for key in ("BLOCKED_COMPANIES", "COMMON_TERMS", "CASE_SENSITIVE_TERMS"):
        if key in res.overrides and not (isinstance(res.overrides[key], list) and all(isinstance(v, str) for v in res.overrides[key])):
            add("fail", key, "must be a list of strings")
    if "SKILL_ALIASES" in res.overrides:
        aliases = res.overrides["SKILL_ALIASES"]
        if not (isinstance(aliases, dict) and all(isinstance(v, list) for v in aliases.values())):
            add("fail", "SKILL_ALIASES", "must look like {\"Skill\": [\"other wording\", ...]}")

    # same field name used for documents by another profile?
    folder = PL.profile_dir(name) / "applications"
    add("ok" if folder.is_dir() else "warn", "applications folder",
        "exists" if folder.is_dir() else "will be created the first time documents are made")
    return out


def cmd_check(name: str) -> None:
    banner(f"Checking profile: {name}")
    results = run_checks(name)
    for level, what, detail in results:
        mark = {"ok": good, "warn": warn, "fail": bad}[level]
        print("  " + mark(paint(what, "white", True) + (paint("  " + detail, "gray") if level == "ok" else "  " + detail)))
    fails = sum(r[0] == "fail" for r in results)
    warns = sum(r[0] == "warn" for r in results)
    print()
    if fails:
        tint = {"ok": "cyan", "warn": "yellow", "fail": "red"}[level]
        print("  " + mark(paint(what, "white", True) + (paint("  " + detail, tint, True) if detail else "")))
    print(good(f"Ready to use: python main.py --profile {name}" + (f"   ({warns} warning(s) above)" if warns else "")))


# ------------------------------------------------------------------------------------ rename


def cmd_rename(old: str, new: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", new):
        fail("Profile names use lowercase letters, digits, - and _, and can't start with _.")
    if old.startswith("_"):
        fail("Templates (names starting with _) can't be renamed.")
    if not PL.profile_dir(old).is_dir():
        fail(f"No folder profiles\\{old}\\.")
    if PL.profile_dir(new).exists():
        fail(f"profiles\\{new}\\ already exists.")
    counts = db_counts()
    if new in counts:
        fail(f"The database already has data for a profile called '{new}'.")
    print(f"Rename {paint(old, 'magenta', True)} to {paint(new, 'magenta', True)}: moves profiles\\{old}\\ "
          f"({application_count(old)} application folder(s)) and re-labels {counts.get(old, 0)} scored job(s), "
          "its ratings and its calibration history. Nothing is deleted.")
    if not confirm("Continue?"):
        raise SystemExit("Cancelled. Nothing was changed.")
    shutil.move(str(PL.profile_dir(old)), str(PL.profile_dir(new)))
    try:
        con = sqlite3.connect(DB_PATH)
        try:
            has_table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'").fetchone()
            if has_table:   # a fresh database has nothing to relabel
                with con:
                    con.execute("UPDATE profiles SET name = ? WHERE name = ?", (new, old))
        finally:
            con.close()
    except sqlite3.Error as e:   # put the folder back so the two stay in step
        shutil.move(str(PL.profile_dir(new)), str(PL.profile_dir(old)))
        fail(f"The database couldn't be updated ({e}); the folder was moved back. Nothing changed.")
    print(good(f"Renamed to '{new}'."))
    for other in PL.list_profiles(include_templates=True):
        text = PL.profile_file(other).read_text(encoding="utf-8")
        if re.search(rf"""EXTENDS\s*=\s*['"]{re.escape(old)}['"]""", text):
            print(warn(f"profiles\\{other}\\profile.py still says EXTENDS = \"{old}\"; change it to \"{new}\"."))
    if S.DEFAULT_PROFILE == old:
        print(warn(f"DEFAULT_PROFILE in config\\settings.py is still \"{old}\"; change it to \"{new}\"."))


# ------------------------------------------------------------------------------------ CLI


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, inspect and check profiles.", epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every profile")
    for cmd, text in (("new", "guided setup for a new profile"), ("show", "what a profile changes"),
                      ("check", "validate a profile")):
        sub.add_parser(cmd, help=text).add_argument("name")
    rename = sub.add_parser("rename", help="rename a profile and keep its data")
    rename.add_argument("old")
    rename.add_argument("new")
    args = parser.parse_args()
    try:
        {"list": lambda: cmd_list(), "new": lambda: cmd_new(args.name) if args.cmd == "new" else None,
         "show": lambda: cmd_show(args.name) if args.cmd == "show" else None,
         "check": lambda: cmd_check(args.name) if args.cmd == "check" else None,
         "rename": lambda: cmd_rename(args.old, args.new) if args.cmd == "rename" else None}[args.cmd]()
    except PL.ProfileError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
