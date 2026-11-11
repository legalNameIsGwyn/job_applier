"""Check that the project is in place and working. Run it from the project root.

    python check_setup.py                 # everything
    python check_setup.py --quick         # files, imports and settings only (no Ollama / browser / network)
    python check_setup.py --no-ollama     # skip the model check
    python check_setup.py --no-browser    # skip the Firefox check

It never changes anything. Each line is [ OK ], [WARN] (worth a look) or [FAIL] (something is broken).

  1. Python version and installed packages
  2. Folders, __init__.py files, config files, data\\resume.json
  3. Every import between your own files points at a file and a name that exist (catches files moved to the
     wrong place, and settings the code reads that config\\ doesn't define)
  4. Every module actually imports
  5. Small offline self-tests of the logic (link detection, link matching, dates, filters)
  6. Ollama is running and has your model; Firefox is installed for Playwright
  7. The database opens and has the tables the code expects
  8. Git: private files (data, database, browser profile, answers) aren't tracked
"""

import argparse
import ast
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {"archive", "data", "reports", "__pycache__", "venv", ".venv", "env", ".git", "node_modules",
             "backups", "archived_applications", "applications"}
THIRD_PARTY = {"jobspy": "python-jobspy", "ollama": "ollama", "pandas": "pandas", "numpy": "numpy",
               "docx": "python-docx", "requests": "requests", "bs4": "beautifulsoup4", "playwright": "playwright"}
CONFIG_FILES = ["settings", "apply_settings", "answers", "filter_rules", "keywords", "job_notes", "prompts",
                "writing_style"]
PRIVATE = ["data/", "applications/", "browser_profile", "learned_answers.json", "jobs.csv", ".sqlite", "reports/"]
EXPECTED_TABLES = {"jobs", "ratings", "applications"}

counts = {"ok": 0, "warn": 0, "fail": 0}


def say(kind: str, text: str, detail: str = "") -> None:
    counts[kind] += 1
    tag = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}[kind]
    print(f"{tag} {text}")
    for line in filter(None, detail.split("\n")):
        print(f"       {line}")


def section(title: str) -> None:
    print(f"\n== {title}")


def code_files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        parts = p.relative_to(ROOT).parts[:-1]
        if any(x in SKIP_DIRS or x.startswith((".", "browser_profile")) for x in parts):
            continue
        out.append(p)
    return out


def dotted(p: Path) -> str:
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


# ------------------------------------------------------------------------------------------ 1
def check_python_and_packages() -> None:
    section("Python and packages")
    v = sys.version_info
    say("ok" if v >= (3, 10) else "fail", f"Python {v.major}.{v.minor}.{v.micro}",
        "" if v >= (3, 10) else "needs 3.10 or newer")
    missing = []
    for module, package in THIRD_PARTY.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        say("fail", "Missing packages: " + ", ".join(missing), "run: pip install -r requirements.txt")
    else:
        say("ok", "All required packages are installed")


# ------------------------------------------------------------------------------------------ 2
def check_layout() -> list[Path]:
    section("Files and folders")
    files = code_files()
    folders = sorted({p.parent for p in files if p.parent != ROOT})
    for folder in folders:
        if (folder / "__init__.py").exists():
            say("ok", f"{folder.relative_to(ROOT)}\\ has __init__.py")
        else:
            say("fail", f"{folder.relative_to(ROOT)}\\ has no __init__.py", "run: python fix_imports.py")
    cfg = ROOT / "config"
    if not cfg.is_dir():
        say("fail", "config\\ folder is missing")
    else:
        absent = [n for n in CONFIG_FILES if not (cfg / f"{n}.py").exists()]
        say("fail" if absent else "ok", "config\\ files: " + (f"missing {', '.join(a + '.py' for a in absent)}"
                                                              if absent else "all present"))
    for name in ("main.py", "apply_jobs.py", "requirements.txt", ".gitignore"):
        say("ok" if (ROOT / name).exists() else "warn", f"{name} " + ("found" if (ROOT / name).exists() else "not found"))

    resume = ROOT / "data" / "resume.json"
    if not resume.exists():
        say("fail", "data\\resume.json not found")
    else:
        try:
            data = json.loads(resume.read_text(encoding="utf-8"))
            need = [k for k in ("name", "contact", "skills", "experience", "education") if not data.get(k)]
            email = (data.get("contact") or {}).get("email")
            problems = [f"empty or missing: {', '.join(need)}"] if need else []
            if not email:
                problems.append("contact.email is missing")
            say("warn" if problems else "ok", "data\\resume.json is valid JSON", "\n".join(problems))
        except Exception as e:
            say("fail", "data\\resume.json can't be read", str(e))
    return files


# ------------------------------------------------------------------------------------------ 3
def top_level_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):   # names defined inside if / try at the top level
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for a in sub.names:
                        names.add((a.asname or a.name).split(".")[0])
    return names


def module_file(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def where_is(simple: str, files: list[Path]) -> list[str]:
    return [dotted(p) for p in files if p.stem == simple and p.parent != ROOT]


def guarded_lines(tree: ast.Module) -> set[int]:
    """Lines of imports that sit in a try block which catches ImportError / Exception (optional imports)."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            catches = {getattr(h.type, "id", None) for h in node.handlers} | ({None} if any(h.type is None for h in node.handlers) else set())
            if catches & {"ImportError", "ModuleNotFoundError", "Exception", None}:
                for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        lines.add(sub.lineno)
    return lines


def check_imports(files: list[Path]) -> None:
    section("Imports between your own files")
    cache: dict[Path, tuple[ast.Module, set[str]]] = {}

    def parse(p: Path):
        if p not in cache:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            cache[p] = (tree, top_level_names(tree))
        return cache[p]

    project_tops = {p.relative_to(ROOT).parts[0].removesuffix(".py") for p in files}
    problems, warnings = [], []
    for path in files:
        rel = path.relative_to(ROOT)
        try:
            tree, _ = parse(path)
        except SyntaxError as e:
            problems.append(f"{rel}: syntax error on line {e.lineno}: {e.msg}")
            continue
        optional = guarded_lines(tree)
        aliases: dict[str, str] = {}   # alias -> config module (for settings attribute checks)
        for node in ast.walk(tree):
            targets: list[tuple[str, list[str]]] = []   # (module, names wanted)
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                targets.append((node.module, [a.name for a in node.names]))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    targets.append((a.name, []))
                    if a.name.startswith("config."):
                        aliases[a.asname or a.name] = a.name
            else:
                continue
            for mod, wanted in targets:
                top = mod.split(".")[0]
                sink = warnings if node.lineno in optional else problems
                where = f"{rel} line {node.lineno}"
                f = module_file(mod)
                if f is None:
                    if top in project_tops or (ROOT / top).is_dir():
                        sink.append(f"{where}: '{mod}' doesn't exist")
                    elif top not in THIRD_PARTY and where_is(top, files):
                        sink.append(f"{where}: 'import {mod}' but that file is now {where_is(top, files)[0]}. "
                                    "Run: python fix_imports.py")
                    continue
                if f.name == "__init__.py" and not wanted:
                    continue
                try:
                    _, names = parse(f)
                except SyntaxError:
                    continue
                for w in wanted:
                    if w == "*":
                        continue
                    if w not in names and module_file(f"{mod}.{w}") is None:
                        sink.append(f"{where}: '{w}' isn't defined in {mod}")
        # attribute use of config modules: `_settings.SOMETHING`
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                f = module_file(aliases[node.value.id])
                if f:
                    _, names = parse(f)
                    if node.attr not in names:
                        problems.append(f"{rel} line {node.lineno}: {aliases[node.value.id]} has no setting {node.attr}")
    if problems:
        say("fail", f"{len(problems)} broken import(s)", "\n".join(sorted(set(problems))))
    else:
        say("ok", f"All imports between your files resolve ({len(files)} files checked)")
    if warnings:
        say("warn", f"{len(warnings)} optional import(s) won't load (guarded, so nothing breaks)",
            "\n".join(sorted(set(warnings))))


# ------------------------------------------------------------------------------------------ 4
def check_runtime_imports(files: list[Path]) -> None:
    section("Modules import cleanly")
    sys.path.insert(0, str(ROOT))
    failures = []
    for p in files:
        if p.name in ("__init__.py", Path(__file__).name, "fix_imports.py", "check_linkedin_page.py"):
            continue
        name = dotted(p)
        try:
            importlib.import_module(name)
        except SystemExit:
            continue
        except ModuleNotFoundError as e:
            failures.append(f"{name}: missing module '{e.name}'")
        except Exception as e:
            failures.append(f"{name}: {type(e).__name__}: {e}")
    if failures:
        say("fail", f"{len(failures)} module(s) fail to import", "\n".join(failures))
    else:
        say("ok", "Every module imports")


# ------------------------------------------------------------------------------------------ 5
def _find(name: str):
    """Import a module wherever it lives now (root or a package folder)."""
    for candidate in [name] + [f"{pkg}.{name}" for pkg in ("core", "applying", "documents")]:
        if module_file(candidate):
            return importlib.import_module(candidate)
    raise ImportError(name)


def check_logic() -> None:
    section("Offline self-tests")
    tests = []

    def test(label):
        def wrap(fn):
            tests.append((label, fn))
            return fn
        return wrap

    @test("ats: recognizes Greenhouse, Lever, Workday and unknown employer pages")
    def _():
        ats = _find("ats")
        got = [ats.detect_ats(u) for u in (
            "https://boards.greenhouse.io/acme/jobs/123", "https://jobs.lever.co/acme/abc",
            "https://acme.wd5.myworkdayjobs.com/en-US/x/job/y", "https://careers.example.com/apply/1")]
        assert got[:3] == ["greenhouse", "lever", "workday"], got
        assert got[3] not in ("greenhouse", "lever", "workday", None), got

    @test("ats_lookup: finds the matching posting and refuses ambiguous ones")
    def _():
        lk = _find("ats_lookup")
        posts = [{"title": "Junior Software Engineer", "url": "u1", "location": "Norfolk, VA"},
                 {"title": "Senior Engineer", "url": "u2", "location": "Remote"}]
        assert lk.match_posting("Junior Software Engineer", "Norfolk, VA", posts) == "u1"
        twin = posts[:1] + [{"title": "Junior Software Engineer", "url": "u3", "location": "Norfolk, VA"}]
        assert lk.match_posting("Junior Software Engineer", "Norfolk, VA", twin) is None
        assert lk.slug_candidates("Smithfield Foods, Inc.")[0] == "smithfieldfoods"

    @test("generic: Next / Continue are pressed, Submit / Review never")
    def _():
        g = _find("generic")
        assert g.NEXT_RE.match("Save and Continue") and g.NEXT_RE.match("Next")
        assert not g.NEXT_RE.match("Submit application") and g.FINAL_RE.search("Review and submit")

    @test("tracking: dates and stage rules")
    def _():
        t = _find("tracking")
        assert t.parse_date("2026-11-09") == "2026-11-09" and t.parse_date("+0") == t.today()
        assert "interview" in t.STAGES and "ghosted" in t.ENDINGS

    @test("filters: senior titles are rejected, junior ones pass")
    def _():
        f = _find("filters")
        assert f.filter_reason("Senior Staff Engineer", "Acme"), "senior title was not rejected"
        assert not f.filter_reason("Junior Python Developer", "Acme"), "junior title was rejected"

    for label, fn in tests:
        try:
            fn()
            say("ok", label)
        except ImportError as e:
            say("warn", label, f"skipped: couldn't import {e}")
        except AssertionError as e:
            say("fail", label, f"unexpected result: {e}")
        except Exception as e:
            say("fail", label, f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------------------------------ 6
def check_ollama() -> None:
    section("Ollama")
    try:
        import ollama
    except ImportError:
        say("fail", "ollama package missing")
        return
    model = os.environ.get("OLLAMA_MODEL")
    source = "the OLLAMA_MODEL environment variable"
    if not model:
        try:
            model = importlib.import_module("config.settings").OLLAMA_MODEL
            source = "config/settings.py"
        except Exception:
            model = None
    try:
        listed = ollama.list()
        names = [getattr(m, "model", None) or m.get("model") or m.get("name") for m in
                 (getattr(listed, "models", None) or listed.get("models", []))]
    except Exception as e:
        say("fail", "Can't reach Ollama", f"{type(e).__name__}: {e}\nIs the Ollama app running? Try: ollama list")
        return
    say("ok", f"Ollama is running ({len(names)} model(s) installed)")
    if not model:
        say("warn", "No OLLAMA_MODEL setting found")
    elif model in names or any(n.split(":")[0] == model and ":" not in model for n in names):
        say("ok", f"Model '{model}' is installed (from {source})")
    else:
        say("fail", f"Model '{model}' (from {source}) isn't installed",
            "installed: " + (", ".join(names) or "none") + f"\nfix: ollama pull {model}  (or change OLLAMA_MODEL)")


def check_browser() -> None:
    section("Browser")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say("fail", "playwright package missing")
        return
    browser = "firefox"
    try:
        browser = getattr(importlib.import_module("config.apply_settings"), "BROWSER", "firefox")
    except Exception:
        pass
    try:
        with sync_playwright() as p:
            exe = Path(getattr(p, browser).executable_path)
        if exe.exists():
            say("ok", f"{browser} is installed for Playwright")
        else:
            say("fail", f"{browser} is not installed for Playwright", f"run: python -m playwright install {browser}")
    except Exception as e:
        say("fail", f"Couldn't check {browser}", f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------------------------------ 7
def check_database() -> None:
    section("Database")
    try:
        path = Path(importlib.import_module("config.settings").DB_PATH)
    except Exception:
        say("warn", "DB_PATH isn't readable from config/settings.py")
        return
    path = path if path.is_absolute() else ROOT / path
    if not path.exists():
        say("warn", f"{path.name} doesn't exist yet", "it is created by the first python main.py run")
        return
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = EXPECTED_TABLES - tables
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] if "jobs" in tables else 0
        conn.close()
        say("warn" if missing else "ok", f"{path.name} opens ({jobs} jobs)",
            f"missing tables (created on the next run): {', '.join(sorted(missing))}" if missing else "")
    except Exception as e:
        say("fail", f"Can't open {path.name}", f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------------------------------ 8
def check_git() -> None:
    section("Git (private files)")
    if not (ROOT / ".git").exists():
        say("ok", "Not a git repository (nothing to leak)")
        return
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=20,
                                 check=True).stdout.splitlines()
    except Exception as e:
        say("warn", "Couldn't run git", str(e))
        return
    leaks = [t for t in tracked if any(p in t.lower().replace("\\", "/") for p in PRIVATE)]
    if leaks:
        shown = leaks[:15] + ([f"... and {len(leaks) - 15} more"] if len(leaks) > 15 else [])
        say("fail", f"{len(leaks)} private file(s) are tracked by git",
            "\n".join(shown) + "\nstop tracking them (keeps your copy):\n  git rm -r --cached <path>\nthen commit and push; "
            "and keep the repository private.")
    else:
        say("ok", "No private files are tracked by git")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".gitignore").exists() else ""
    absent = [p for p in ("data/", "browser_profile", "learned_answers.json", "*.sqlite", "__pycache__")
              if p not in ignore]
    say("warn" if absent else "ok", ".gitignore " + ("is missing: " + ", ".join(absent) if absent else "covers the private files"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the project setup.", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--quick", action="store_true", help="skip Ollama, the browser and the database")
    ap.add_argument("--no-ollama", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)
    print(f"Checking {ROOT}")
    check_python_and_packages()
    files = check_layout()
    check_imports(files)
    check_runtime_imports(files)
    check_logic()
    if not args.quick:
        if not args.no_ollama:
            check_ollama()
        if not args.no_browser:
            check_browser()
        check_database()
    check_git()
    print(f"\n{counts['ok']} ok, {counts['warn']} warning(s), {counts['fail']} failure(s)")
    if counts["fail"]:
        print("Fix the [FAIL] lines first; the others are usually consequences of them.")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
