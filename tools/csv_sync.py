"""Write what the database knows into your applications CSV.

For each CSV row with a blank status whose job the bot applied to (or found closed), fill in
"auto-applied" or "closed". A status you typed yourself is never changed.

Run:  python -m tools.csv_sync --profile NAME            (add --dry-run to only look)
"""

import argparse

from core.csv_log import csv_path, sync_statuses
from db.queries import application_statuses
from db.session import add_profile_arguments, apply_profile_arguments

LABELS = {"applied": "auto-applied", "closed": "closed"}


def main() -> None:
    p = argparse.ArgumentParser(description="Fill blank CSV statuses from the database.")
    p.add_argument("--dry-run", action="store_true", help="show what would change and write nothing")
    add_profile_arguments(p)
    args = p.parse_args()
    apply_profile_arguments(args)

    path = csv_path()
    if not path.exists():
        raise SystemExit(f"No CSV yet at {path}. Run main.py first.")

    labels = {url: LABELS[status] for url, status in application_statuses().items() if status in LABELS}
    changed = sync_statuses(labels, dry_run=args.dry_run)
    verb = "would fill" if args.dry_run else "filled"
    print(f"[CSV] {path}")
    print(f"[CSV] {len(labels)} job(s) in the database are applied or closed; {verb} {len(changed)} blank status cell(s)")
    for url, text in changed:
        print(f"  {text:<13} {url}")


if __name__ == "__main__":
    main()