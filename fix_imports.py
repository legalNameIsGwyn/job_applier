r"""Repair imports after moving files into folders. Run it from the project root.

    python fix_imports.py --dry-run     # show what it would change
    python fix_imports.py               # do it (a zip backup of every .py file is made first)

It looks at where each .py file lives NOW, then
  - creates an empty __init__.py in every folder that holds code (so the folder is a package),
  - rewrites  `import db` -> `import core.db as db`  and  `from db import x` -> `from core.db import x`
    (for whatever folder db.py ended up in), including imports written inside functions.
Files at the root, config\ and archive\ are left alone. It is safe to run again: nothing changes the second time.

After a move, run scripts from the root as before (python main.py). Files inside a folder that are meant to be run
directly need -m:   python -m applying.check_linkedin_page <url>
"""

import argparse
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {"archive", "data", "reports", "__pycache__", "venv", ".venv", "env", "node_modules", ".git",
             "backups", "archived_applications", "applications"}
SKIP_PREFIXES = ("browser_profile",)
SELF = "fix_imports.py"


def _skipped(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts[:-1]
    return any(p in SKIP_DIRS or p.startswith(SKIP_PREFIXES) or p.startswith(".") for p in parts)


def find_modules(root: Path) -> tuple[dict[str, str], dict[str, list[str]], list[Path]]:
    """({simple name: dotted path} for modules inside folders, {name: [paths]} for duplicates, all code files)."""
    found: dict[str, list[str]] = {}
    files = []
    for path in sorted(root.rglob("*.py")):
        if _skipped(path, root) or path.name in ("__init__.py", SELF):
            continue
        files.append(path)
        dotted = ".".join(path.relative_to(root).with_suffix("").parts)
        found.setdefault(path.stem, []).append(dotted)
    moved = {n: d[0] for n, d in found.items()
             if len(d) == 1 and "." in d[0] and not d[0].startswith("config.")}   # config\ imports are already dotted
    dupes = {n: d for n, d in found.items() if len(d) > 1}
    return moved, dupes, files


def rewrite(text: str, moved: dict[str, str]) -> tuple[str, int, list[str]]:
    """Rewrite imports of moved modules. Returns (new text, how many lines changed, warnings)."""
    names = "|".join(sorted(map(re.escape, moved), key=len, reverse=True))
    if not names:
        return text, 0, []
    from_re = re.compile(rf"^(\s*)from (?:archive\.)?({names})(\s+import\b.*)$")
    import_re = re.compile(rf"^(\s*)import (?:archive\.)?({names})(?:\s+as\s+(\w+))?(\s*(?:#.*)?)$")
    multi_re = re.compile(rf"^\s*import\s+[\w.]+\s*,\s*[\w., ]+$")
    out, changed, warnings = [], 0, []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        body, nl = (line[:-1], "\n") if line.endswith("\n") else (line, "")
        body = body.rstrip("\r")
        nl = ("\r\n" if line.endswith("\r\n") else nl)
        m = from_re.match(body)
        if m:
            new = f"{m[1]}from {moved[m[2]]}{m[3]}"
        else:
            m = import_re.match(body)
            if m:
                alias = m[3] or m[2]
                new = f"{m[1]}import {moved[m[2]]} as {alias}{m[4]}"
            else:
                new = body
                if multi_re.match(body) and any(re.search(rf"\b{n}\b", body) for n in moved):
                    warnings.append(f"line {number}: several modules on one import line; fix by hand: {body.strip()}")
        if new != body:
            changed += 1
        out.append(new + nl)
    return "".join(out), changed, warnings


def ensure_packages(root: Path, files: list[Path], dry_run: bool) -> list[Path]:
    """Create __init__.py in every folder (below the root) that holds code, and in its parents."""
    need = set()
    for f in files:
        folder = f.parent
        while folder != root:
            need.add(folder)
            folder = folder.parent
    made = []
    for folder in sorted(need):
        init = folder / "__init__.py"
        if not init.exists():
            made.append(init)
            if not dry_run:
                init.write_text("", encoding="utf-8")
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fix imports after moving files into folders.")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; change nothing")
    ap.add_argument("--root", default=".", help="the project folder (default: here)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    moved, dupes, files = find_modules(root)
    if not files:
        print(f"No .py files found in {root}. Run this from the project root.")
        return 1
    print(f"Project: {root}\n")
    if moved:
        print("Modules inside folders:")
        for name, dotted in sorted(moved.items(), key=lambda kv: kv[1]):
            print(f"  {name:<22} -> {dotted}")
    else:
        print("No modules found inside folders (everything is still at the root).")
    for name, where in sorted(dupes.items()):
        print(f"\nWARNING: '{name}' exists more than once ({', '.join(where)}); its imports were left alone. "
              "Keep one copy.")
    in_archive = [p for p in (root / "archive").glob("*.py")] if (root / "archive").is_dir() else []
    for p in in_archive:
        if p.stem in {"linkedin_resolver", "ats_lookup"}:
            print(f"\nNOTE: {p.relative_to(root)} is still in archive\\. If you use it, move it next to the other "
                  "applying files and run this again.")

    made = ensure_packages(root, files, args.dry_run)
    print(f"\n__init__.py: {len(made)} to create" if args.dry_run else f"\n__init__.py: created {len(made)}")
    for p in made:
        print(f"  {p.relative_to(root)}")

    results = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        new, count, warns = rewrite(text, moved)
        results.append((f, text, new, count, warns))
    total = sum(r[3] for r in results)
    print(f"\nImports to rewrite: {total} line(s) in {sum(1 for r in results if r[3])} file(s)")
    for f, _, _, count, warns in results:
        if count:
            print(f"  {f.relative_to(root)}: {count}")
        for w in warns:
            print(f"  WARNING {f.relative_to(root)} {w}")
    for f, text, _, _, _ in results:
        if f.name in ("check_setup.py", SELF):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if "__file__" in line and not line.lstrip().startswith("#"):
                print(f"  CHECK {f.relative_to(root)} line {number}: uses __file__ (paths move with the file): {line.strip()}")

    if args.dry_run:
        print("\nDry run: nothing was changed.")
        return 0
    if total:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = root / f"backup_before_fix_imports_{stamp}.zip"
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
            for f, *_ in results:
                z.write(f, f.relative_to(root))
        print(f"\nBackup of every code file: {backup.name}")
        for f, _, new, count, _ in results:
            if count:
                f.write_text(new, encoding="utf-8", newline="")
    print("\nDone. Next: python check_setup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
