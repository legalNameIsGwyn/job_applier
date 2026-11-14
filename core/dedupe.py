"""Duplicate job detection: the same posting listed twice (two sites, two companies of one group, two scrapes).

Two jobs are duplicates when their titles match and EITHER
  - they have the same company and the same location, or
  - their descriptions are nearly identical (90%+ of the same words) and the location agrees.

    python -m core.dedupe --dry-run       # show what would be marked, change nothing
    python -m core.dedupe                 # mark duplicates already in your database

main.py also checks every new job as it goes. A duplicate is saved with status "duplicate" and score 0
(its model and keyword scores are kept), so it never shows up in ratings, rankings or applications.
"""

import argparse
import re

from config.settings import DB_PATH
from db.queries import dedupe_candidates, load_known as _load_known, mark_duplicates as _mark_duplicates
from db.repo import init_db
from db.session import add_profile_arguments, apply_profile_arguments

DESCRIPTION_SIMILARITY = 0.9
SHORTER_OVERLAP = 0.75       # same title + same city: duplicate if 75% of the SHORTER posting's words are in the other
MIN_WORDS_FOR_OVERLAP = 40   # ...but only when the shorter posting has at least this many distinct words
COMPANY_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "the"}
VAGUE_LOCATIONS = {"", "united states", "us", "usa", "remote", "anywhere"}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()


def title_key(title: str) -> str:
    return " ".join(_words(title))


def company_key(company: str) -> str:
    return " ".join(w for w in _words(company) if w not in COMPANY_SUFFIXES)


def location_key(location: str) -> str:
    """The city part of a location ('Norfolk, VA, United States' -> 'norfolk'), or '' if vague."""
    city = " ".join(_words((location or "").split(",")[0]))
    return "" if city in VAGUE_LOCATIONS else city


def description_words(description: str) -> frozenset:
    return frozenset(w for w in _words((description or "")[:4000]) if len(w) > 2)


def similarity(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: frozenset, b: frozenset) -> float:
    """Share of the shorter description's words that also appear in the other (catches a posting wrapped in page junk)."""
    if not a or not b or min(len(a), len(b)) < MIN_WORDS_FOR_OVERLAP:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_duplicate(a: dict, b: dict) -> bool:
    """True if two jobs ({title, company, location, description}) are the same posting."""
    if title_key(a["title"]) != title_key(b["title"]):
        return False
    loc_a, loc_b = location_key(a.get("location")), location_key(b.get("location"))
    same_location = loc_a == loc_b
    if company_key(a["company"]) == company_key(b["company"]) and same_location:
        return True
    sim = similarity(description_words(a.get("description")), description_words(b.get("description")))
    if sim >= DESCRIPTION_SIMILARITY and (same_location or not loc_a or not loc_b):
        return True
    if loc_a and same_location:  # same city, different company name: compare against the shorter text
        return containment(description_words(a.get("description")), description_words(b.get("description"))) >= SHORTER_OVERLAP
    return False


class KnownJobs:
    """A growing list of jobs to compare new ones against (indexed by title for speed)."""

    def __init__(self, jobs=()):
        self.by_title: dict[str, list[dict]] = {}
        for job in jobs:
            self.add(job)

    def add(self, job: dict) -> None:
        self.by_title.setdefault(title_key(job["title"]), []).append(job)

    def duplicate_of(self, job: dict) -> dict | None:
        return next((k for k in self.by_title.get(title_key(job["title"]), []) if is_duplicate(job, k)), None)


def load_known(db_path: str = DB_PATH) -> KnownJobs:
    """Every job already scored (by any profile) that isn't itself a duplicate."""
    return KnownJobs(_load_known(db_path))


def duplicate_gap(original: dict) -> list[str]:
    return [f"Duplicate of: {original['title']} - {original['company']}"]

def mark_duplicates(db_path: str = DB_PATH, dry_run: bool = False) -> list[tuple[dict, dict]]:
    """Mark duplicates among the jobs already scored. Returns [(duplicate, kept)].

    Of each set of duplicates the best is kept: one you've started applying to, then one with an
    employer link, then the highest score, then the oldest. Scores are not changed.
    """
    init_db(db_path)
    jobs = dedupe_candidates(db_path)
    jobs.sort(key=lambda j: (j["application"] is None,
                             not (j["apply_url"] and not j["apply_url"].startswith("none")),
                             -(j["match_score"] or 0), j["id"]))
    known, found = KnownJobs(), []
    for job in jobs:
        original = known.duplicate_of(job)
        if original:
            found.append((job, original))
        else:
            known.add(job)
    if found and not dry_run:
        _mark_duplicates([(job["id"], original["id"]) for job, original in found], db_path)
    return found

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find and mark duplicate jobs already in the database.")
    parser.add_argument("--dry-run", action="store_true", help="show the duplicates without changing anything")
    add_profile_arguments(parser)
    args = parser.parse_args()
    apply_profile_arguments(args)
    dupes = mark_duplicates(dry_run=args.dry_run)
    for dup, kept in dupes:
        print(f"duplicate: {dup['title'][:45]} - {dup['company'][:25]}  ({dup['location']})\n"
              f"   of:     {kept['title'][:45]} - {kept['company'][:25]}  ({kept['location']})")
    verb = "Would mark" if args.dry_run else "Marked"
    print(f"\n{verb} {len(dupes)} duplicate job(s).")
