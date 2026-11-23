"""Engine setup, sessions and the active profile.

SQLite ignores foreign keys unless they are switched on for every connection.
The active profile is the one the config files loaded (--profile, JOB_PROFILE or DEFAULT_PROFILE);
select_profile checks it against the database and makes sure the database has a row for it.
A profile exists when profiles/<name>/profile.py exists; its database row is added on first use.
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from config.settings import ACTIVE_PROFILE, DB_PATH, DEFAULT_PROFILE
from db.models import Base, Profile
from core.console import tag

_engines: dict = {}
_active_name: str | None = None


def get_engine(db_path=DB_PATH):
    key = str(db_path)
    if key not in _engines:
        engine = create_engine(URL.create("sqlite", database=key))

        @event.listens_for(engine, "connect")
        def _foreign_keys_on(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _engines[key] = engine
    return _engines[key]


make_engine = get_engine   # the name db/migrate.py uses


def create_tables(engine) -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jobs)")}
    if cols and "is_duplicate" not in cols:
        raise SystemExit(
            "[DB] This database still has the OLD schema, so it was left alone. Point at the migrated file: "
            '$env:JOBS_DB = "$PWD\\data\\jobs_db_new.sqlite"   (or finish the switch-over).'
        )
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


# Columns added after a table was first created. create_all() never alters an existing table, so they are added here.
_NEW_COLUMNS = {
    "jobs": {
        "last_checked": "DATETIME",
    },
    "job_scores": {
        "compat_detail_pct": "FLOAT",
        "compat_missing": "TEXT DEFAULT '[]'",
        "compat_capped": "INTEGER DEFAULT 0",
    },
}


def _add_missing_columns(engine) -> None:
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            have = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in columns.items():
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


@contextmanager
def session_scope(db_path=DB_PATH):
    """A session that commits when the block ends and rolls back if it raises."""
    with Session(get_engine(db_path)) as session:
        with session.begin():
            yield session


def get_or_create_profile(session, name: str) -> Profile:
    profile = session.scalar(select(Profile).where(Profile.name == name))
    if profile is None:
        profile = Profile(name=name)
        session.add(profile)
        session.flush()
    return profile


# ----------------------------------------------------------------- the active profile


def active_profile_name() -> str:
    return _active_name or ACTIVE_PROFILE


def set_active_profile(name: str) -> None:
    global _active_name
    _active_name = name
    os.environ["JOB_PROFILE"] = name   # parallel apply windows inherit this


def current_profile_id(session) -> int:
    pid = session.scalar(select(Profile.id).where(Profile.name == active_profile_name()))
    if pid is None:
        raise LookupError(f"profile '{active_profile_name()}' is not in the database "
                          "(call db.session.select_profile first)")
    return pid


def select_profile(name: str | None = None, db_path=DB_PATH) -> str:
    """Confirm the profile for this run and make sure the database knows it.

    The settings were loaded for ACTIVE_PROFILE before any script started, so asking for a different
    one here would score jobs with one profile's prompts and save them under another's name. That is
    refused rather than guessed at.
    """
    name = name or ACTIVE_PROFILE
    if ACTIVE_PROFILE == "_defaults":
        raise SystemExit("[PROFILE] This command needs a real profile, but none was loaded. "
                         "Run it without JOB_PROFILE=_defaults, or pass --profile NAME.")
    if name != ACTIVE_PROFILE:
        raise SystemExit(f"[PROFILE] The settings were loaded for '{ACTIVE_PROFILE}', not '{name}'. "
                         "Type the full option --profile NAME (argparse abbreviations like --prof aren't seen by the config loader).")
    create_tables(get_engine(db_path))
    with session_scope(db_path) as s:
        if s.scalar(select(Profile.id).where(Profile.name == name)) is None:
            s.add(Profile(name=name))
            tag("PROFILE", f"First use of '{name}': added it to the database.")
    set_active_profile(name)
    return name


def add_profile_arguments(parser) -> None:
    """Adds --profile to a script's argparse parser. (The config loader reads it from the command line first.)"""
    parser.add_argument("--profile", metavar="NAME",
                        help=f"which profile to use (default: {DEFAULT_PROFILE}, set in config/settings.py)")


def apply_profile_arguments(args, db_path=DB_PATH) -> str:
    return select_profile(args.profile, db_path)
