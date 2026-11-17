"""Database tables (SQLAlchemy 2.0).

One database file. Facts about a posting live in `jobs`; everything that depends on a profile
(scores, ratings, calibrations) points at `profiles.id`.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """UTC without tzinfo, matching SQLite's CURRENT_TIMESTAMP so old and new rows compare correctly."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    """The scraped posting itself, stored once however many profiles score it."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String, default="unknown")
    job_url: Mapped[str | None] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    apply_url: Mapped[str | None] = mapped_column(String)
    salary: Mapped[str | None] = mapped_column(String)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    found_by_profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))


class JobScore(Base):
    """One profile's verdict on one job. status: scored | scoring_failed | filtered."""
    __tablename__ = "job_scores"
    __table_args__ = (
        UniqueConstraint("job_id", "profile_id"),
        Index("ix_job_scores_profile_status", "profile_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="scored")
    match_score: Mapped[float] = mapped_column(Float, default=0.0)   # final score; -1 = scoring failed, 0 = rejected
    model_score: Mapped[float | None] = mapped_column(Float)
    keyword_score: Mapped[float | None] = mapped_column(Float)
    compat_pct: Mapped[float | None] = mapped_column(Float)         # rough: matched / (matched + gaps), 0-100
    compat_detail_pct: Mapped[float | None] = mapped_column(Float)  # detailed: requirement by requirement, 0-100
    compat_missing: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of {"text", "hard", "required"}
    compat_capped: Mapped[int] = mapped_column(Integer, default=0)   # 1 = the detailed % was capped by a hard requirement
    matched_skills: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    gaps: Mapped[str] = mapped_column(Text, default="[]")            # JSON list
    is_retry: Mapped[int] = mapped_column(Integer, default=0)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Rating(Base):
    """Your hand rating (rating is NULL when you skipped). Keyed by URL so it survives clearing jobs."""
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("job_url", "profile_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_url: Mapped[str] = mapped_column(String)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    rating: Mapped[float | None] = mapped_column(Float)
    batch: Mapped[int] = mapped_column(Integer)
    rated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    previous_rating: Mapped[float | None] = mapped_column(Float)     # set when you re-rate
    rerated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Calibration(Base):
    """Every fit of w / a / b for a profile. Exactly one per profile has is_active = True."""
    __tablename__ = "calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    fitted_at: Mapped[str] = mapped_column(String, default="")
    n: Mapped[int] = mapped_column(Integer, default=0)
    latest_batch_only: Mapped[bool] = mapped_column(Boolean, default=False)
    w_model: Mapped[float | None] = mapped_column(Float)
    a: Mapped[float | None] = mapped_column(Float)
    b: Mapped[float | None] = mapped_column(Float)
    trust: Mapped[float | None] = mapped_column(Float)
    w_fit: Mapped[float | None] = mapped_column(Float)
    a_fit: Mapped[float | None] = mapped_column(Float)
    b_fit: Mapped[float | None] = mapped_column(Float)
    spearman_model: Mapped[float | None] = mapped_column(Float)
    spearman_keyword: Mapped[float | None] = mapped_column(Float)
    spearman_final: Mapped[float | None] = mapped_column(Float)
    mae_model: Mapped[float | None] = mapped_column(Float)
    mae_final: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class Application(Base):
    """What happened when you opened a job to apply. status: applied | skipped | opened | closed."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    apply_url: Mapped[str | None] = mapped_column(String)
    ats: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Tracking(Base):
    """Where an application stands. Keyed by URL so it survives clearing jobs and works for jobs applied to by hand."""
    __tablename__ = "tracking"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_url: Mapped[str] = mapped_column(String, unique=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"))
    stage: Mapped[str] = mapped_column(String)
    applied_on: Mapped[str | None] = mapped_column(String)    # YYYY-MM-DD text, as before
    updated_on: Mapped[str | None] = mapped_column(String)
    site: Mapped[str | None] = mapped_column(String)
    ats: Mapped[str | None] = mapped_column(String)
    folder: Mapped[str | None] = mapped_column(String)
    score_at_apply: Mapped[float | None] = mapped_column(Float)
    contact_name: Mapped[str | None] = mapped_column(String)
    contact_email: Mapped[str | None] = mapped_column(String)
    interview_on: Mapped[str | None] = mapped_column(String)
    follow_up_on: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)


class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[int] = mapped_column(ForeignKey("tracking.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String)
    on_date: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text)