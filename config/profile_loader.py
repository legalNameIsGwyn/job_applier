"""Profiles: one folder per kind of job search, with its own settings, resume and documents.

    profiles/<name>/profile.py      only the settings that differ from the shared defaults
    profiles/<name>/resume.json     this profile's resume data
    profiles/<name>/applications/   its generated resumes and cover letters

The active profile is chosen once, while the config files load, from (first match wins):
    --profile NAME on the command line   |   DEFAULT_PROFILE (config/settings.py)
Every config file ends with two lines that call apply_overrides(globals()), so by the time any other
code does `from config.settings import SEARCH_TERMS` the profile's value is already in place.

The profile name "_defaults" means "load no profile at all". tools/profile.py and tools/clear.py use
it so they can manage profiles that are missing or broken.
"""

import ast
import difflib
import os
import re
import runpy
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CONFIG_DIR.parent
PROFILES_DIR = PROJECT_DIR / "profiles"
DEFAULTS = "_defaults"

# Machine-wide settings: a profile can't change these (files, database, browser, scraping speed, timeouts).
LOCKED = {
    "PROJECT_DIR", "PROFILES_DIR", "PROFILE_DIR", "ACTIVE_PROFILE", "DEFAULT_PROFILE", "DB_PATH",
    "CALIBRATION_FILE", "BACKUP_DIR", "ARCHIVE_DIR", "SUMMARY_DIR", "LEARNED_ANSWERS_FILE",
    "BROWSER", "BROWSER_PROFILE_DIR", "PARALLEL_PROFILE_DIR", "PARALLEL_JOBS", "HEADLESS", "SLOW_MO_MS",
    "PAGE_TIMEOUT_MS", "USER_AGENT", "REQUEST_TIMEOUT_SECONDS", "DELAY_BETWEEN_SEARCH_TERMS",
    "DESCRIPTION_FETCH_DELAY", "DESCRIPTION_FETCH_TIMEOUT", "RATE_LIMIT_BACKOFF_SECONDS",
    "RATE_LIMIT_STOP_AFTER_JOBS", "COUNTRY_INDEED", "AVAILABLE_SITES", "DESCRIPTION_FETCH_ATTEMPTS", "PARK_BLOCKED"
}
_INJECTED = {"PROJECT_DIR", "PROFILE_DIR"}   # handed to profile.py so it can build paths; not overrides
_SKIP_FILES = {"__init__.py", "profile_loader.py"}


class ProfileError(Exception):
    """A profile is missing or broken. The message says what to do."""


@dataclass
class Resolved:
    name: str
    chain: list          # [this profile, its parent, ...]
    overrides: dict      # setting name -> value, parents merged in
    origins: dict        # setting name -> the profile whose file set it
    extends: str | None


# ------------------------------------------------------------------------------- finding profiles


def profile_dir(name: str) -> Path:
    return PROFILES_DIR / name


def profile_file(name: str) -> Path:
    return profile_dir(name) / "profile.py"


def list_profiles(include_templates: bool = False) -> list[str]:
    """Profiles that exist (a folder with a profile.py). Names starting with _ are templates."""
    if not PROFILES_DIR.is_dir():
        return []
    names = sorted(p.parent.name for p in PROFILES_DIR.glob("*/profile.py"))
    return names if include_templates else [n for n in names if not n.startswith("_")]


def default_name() -> str:
    """DEFAULT_PROFILE from config/settings.py, read without importing it."""
    try:
        tree = ast.parse((CONFIG_DIR / "settings.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_PROFILE"
                                                    for t in node.targets):
                return str(ast.literal_eval(node.value))
    except (OSError, SyntaxError, ValueError):
        pass
    return "software"


def requested_name() -> str | None:
    """The profile asked for with --profile on the command line (None = use DEFAULT_PROFILE).

    The one exception is internal: tools/profile.py sets JOB_PROFILE=_defaults to load no profile at all."""
    if os.environ.get("JOB_PROFILE") == DEFAULTS:
        return DEFAULTS
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--profile="):
            return arg.split("=", 1)[1]
    return None


@lru_cache(maxsize=1)
def known_names() -> dict:
    """{SETTING_NAME: config file it lives in}, found by reading the config files (nothing is imported)."""
    found = {}
    for path in sorted(CONFIG_DIR.glob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    found.setdefault(target.id, path.stem)
    return found


# ----------------------------------------------------------------------------- reading a profile


def _load_file(name: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
        raise ProfileError(f"'{name}' isn't a valid profile name (use letters, digits, - and _).")
    path = profile_file(name)
    if not path.is_file():
        existing = ", ".join(list_profiles()) or "none yet"
        raise ProfileError(f"No profile named '{name}' (looked for {path}). Existing profiles: {existing}. "
                           f"Create one with:  python -m tools.profile new {name}")
    try:
        return runpy.run_path(str(path), init_globals={"PROJECT_DIR": PROJECT_DIR, "PROFILE_DIR": profile_dir(name)})
    except Exception as e:   # a typo in the file: say which file
        raise ProfileError(f"{path} has an error: {type(e).__name__}: {e}") from None


def resolve(name: str, _seen: tuple = ()) -> Resolved:
    """A profile's settings with its parent's merged underneath (EXTENDS = "parent")."""
    if name in _seen:
        raise ProfileError("profiles extend each other in a loop: " + " -> ".join(_seen + (name,)))
    namespace = _load_file(name)
    own = {k: v for k, v in namespace.items()
           if k.isupper() and not k.startswith("_") and k not in _INJECTED}
    extends = own.pop("EXTENDS", None)
    if isinstance(extends, (list, tuple, set)):
        raise ProfileError(f"{name}: EXTENDS with several parents isn't supported yet. Use one parent: EXTENDS = \"name\"")
    if extends is not None and not isinstance(extends, str):
        raise ProfileError(f"{name}: EXTENDS must be a profile name in quotes, like EXTENDS = \"software\"")
    if extends:
        parent = resolve(extends, _seen + (name,))
        overrides, origins, chain = dict(parent.overrides), dict(parent.origins), [name] + parent.chain
    else:
        overrides, origins, chain = {}, {}, [name]
    for key, value in own.items():
        overrides[key], origins[key] = value, name
    return Resolved(name, chain, overrides, origins, extends)


def problems(res: Resolved) -> list[str]:
    """Settings in the profile that don't exist or can't be changed by a profile."""
    known, out = known_names(), []
    for key, owner in res.origins.items():
        if key in LOCKED:
            out.append(f"{owner}.py sets {key}, which is a machine-wide setting a profile can't change")
        elif key not in known:
            close = difflib.get_close_matches(key, list(known), n=1)
            out.append(f"{owner}.py sets {key}, which isn't a setting" + (f" (did you mean {close[0]}?)" if close else ""))
    return out


@lru_cache(maxsize=1)
def active() -> Resolved | None:
    """The profile for this run (None for "_defaults"). Exits with a clear message if it's missing or wrong."""
    name = requested_name() or default_name()
    if name == DEFAULTS:
        return None
    try:
        res = resolve(name)
        found = problems(res)
        if found:
            raise ProfileError("; ".join(found) + ". Run  python -m tools.profile check " + name)
    except ProfileError as e:
        raise SystemExit(f"[PROFILE] {e}") from None
    return res


# -------------------------------------------------------------------------- applying to a config


def apply_overrides(g: dict) -> None:
    """Called at the bottom of every config file with that file's globals()."""
    res = active()
    is_settings = g.get("__name__") == "config.settings"
    if is_settings:
        g["ACTIVE_PROFILE"] = res.name if res else DEFAULTS
        g["PROFILE_DIR"] = profile_dir(res.name) if res else None
    if res is None:
        return
    if is_settings:   # each profile's resume and documents live in its own folder
        g["RESUME_FILE"] = g["PROFILE_DIR"] / "resume.json"
        g["APPLICATIONS_DIR"] = g["PROFILE_DIR"] / "applications"
    for key, value in res.overrides.items():
        if key in g and key not in LOCKED:
            g[key] = value
    if is_settings:
        resume = Path(g["RESUME_FILE"])
        resume = resume if resume.is_absolute() else PROJECT_DIR / resume
        g["RESUME_FILE"] = resume
        if not resume.is_file():
            raise SystemExit(f"[PROFILE] Profile '{res.name}' has no resume at {resume}. "
                             f"Add one (copy profiles\\_generic\\resume.json and fill it in), "
                             f"then run  python -m tools.profile check {res.name}")
