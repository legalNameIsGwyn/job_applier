"""Engine setup, sessions and the active profile.

SQLite ignores foreign keys unless they are switched on for every connection.
The active profile is chosen once at startup (select_profile) and every db function reads it.
"""

import os

from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from config.settings import DB_PATH, DEFAULT_PROFILE
from db.models import Base, Profile

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
    return _active_name or os.environ.get("JOB_PROFILE") or DEFAULT_PROFILE


def set_active_profile(name: str) -> None:
    global _active_name
    _active_name = name
    os.environ["JOB_PROFILE"] = name   


def current_profile_id(session) -> int:
    pid = session.scalar(select(Profile.id).where(Profile.name == active_profile_name()))
    if pid is None:
        raise LookupError(f"profile '{active_profile_name()}' is not in the database "
                          "(select it first with db.session.select_profile)")
    return pid


def select_profile(name: str | None = None, db_path=DB_PATH, create: bool = False) -> str:
    """Make `name` (or DEFAULT_PROFILE) the active profile. A name that doesn't exist yet is only
    created with create=True, so a typo in --profile can't quietly make a new profile."""
    name = name or DEFAULT_PROFILE
    create_tables(get_engine(db_path))
    with session_scope(db_path) as s:
        if s.scalar(select(Profile).where(Profile.name == name)) is None:
            if not (create or name == DEFAULT_PROFILE):
                known = ", ".join(s.scalars(select(Profile.name).order_by(Profile.name))) or "none"
                raise SystemExit(f"[PROFILE] No profile named '{name}'. Existing profiles: {known}. "
                                 "Add --create-profile to make a new one.")
            s.add(Profile(name=name))
            print(f"[PROFILE] Created profile '{name}'.")
    set_active_profile(name)
    return name


def add_profile_arguments(parser) -> None:
    """Adds --profile and --create-profile to a script's argparse parser."""
    parser.add_argument("--profile", help=f"which profile to use (default: {DEFAULT_PROFILE}, set in config/settings.py)")
    parser.add_argument("--create-profile", action="store_true", help="allow --profile to name a profile that doesn't exist yet")


def apply_profile_arguments(args, db_path=DB_PATH) -> str:
    return select_profile(args.profile, db_path, create=args.create_profile)