import enum
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, Float,
    ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

# DateTime(timezone=True) maps to TIMESTAMPTZ in PostgreSQL
TIMESTAMPTZ = DateTime(timezone=True)

from app.config import settings


# ---------------------------------------------------------------------------
# Engine & session
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(AsyncAttrs, DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, enum.Enum):
    bank = "bank"
    ledger = "ledger"
    erp = "erp"
    manual = "manual"


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    matched = "matched"
    exception = "exception"
    excluded = "excluded"


class MatchType(str, enum.Enum):
    one_to_one = "1:1"
    one_to_many = "1:many"
    many_to_many = "many:many"


class MatchStatus(str, enum.Enum):
    auto_matched = "auto_matched"
    pending_review = "pending_review"
    confirmed = "confirmed"
    rejected = "rejected"


class ExceptionType(str, enum.Enum):
    unmatched = "unmatched"
    low_confidence = "low_confidence"
    ambiguous = "ambiguous"
    duplicate = "duplicate"


class PriorityLevel(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ExceptionStatus(str, enum.Enum):
    open = "open"
    in_review = "in_review"
    resolved = "resolved"
    escalated = "escalated"
    closed = "closed"


class ActionType(str, enum.Enum):
    manual_match = "manual_match"
    reject = "reject"
    split = "split"
    escalate = "escalate"
    writeoff = "writeoff"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class RunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# SQLAlchemy Enum types — bound to the PostgreSQL types created by the migration.
# create_type=False prevents SQLAlchemy from trying to CREATE TYPE at startup.
# ---------------------------------------------------------------------------

pg_source_type      = Enum(SourceType,        name="source_type",      create_type=False)
pg_txn_status       = Enum(TransactionStatus,  name="txn_status",       create_type=False)
pg_match_type       = Enum(MatchType,          name="match_type",       create_type=False, values_callable=lambda obj: [e.value for e in obj])
pg_match_status     = Enum(MatchStatus,        name="match_status",     create_type=False)
pg_exception_type   = Enum(ExceptionType,      name="exception_type",   create_type=False)
pg_priority_level   = Enum(PriorityLevel,      name="priority_level",   create_type=False)
pg_exception_status = Enum(ExceptionStatus,    name="exception_status", create_type=False)
pg_action_type      = Enum(ActionType,         name="action_type",      create_type=False)
pg_approval_status  = Enum(ApprovalStatus,     name="approval_status",  create_type=False)
pg_run_status       = Enum(RunStatus,          name="run_status",       create_type=False)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(128), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name_ar: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    language_pref: Mapped[str] = mapped_column(String(4), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    last_login: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    role: Mapped["Role"] = relationship(back_populates="users")
    exceptions_assigned: Mapped[list["ExceptionQueue"]] = relationship(back_populates="assigned_to_user")
    resolutions: Mapped[list["ResolutionAction"]] = relationship(back_populates="resolved_by_user")
    approvals: Mapped[list["ApprovalWorkflow"]] = relationship(back_populates="approver")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="recipient")
    audit_entries: Mapped[list["AuditLog"]] = relationship(back_populates="user")


# ---------------------------------------------------------------------------
# Ingestion  (FR-05)
# ---------------------------------------------------------------------------

class TransactionSource(Base):
    __tablename__ = "transaction_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_type: Mapped[SourceType] = mapped_column(pg_source_type, nullable=False)
    connection_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="source")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("transaction_sources.id"), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="AED")
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_ar: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_no: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        pg_txn_status, nullable=False, default=TransactionStatus.pending
    )
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["TransactionSource"] = relationship(back_populates="transactions")


# ---------------------------------------------------------------------------
# Reconciliation run
# ---------------------------------------------------------------------------

class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_a_id: Mapped[int] = mapped_column(ForeignKey("transaction_sources.id"), nullable=False)
    source_b_id: Mapped[int] = mapped_column(ForeignKey("transaction_sources.id"), nullable=False)
    total_transactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_reconciled_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[RunStatus] = mapped_column(pg_run_status, nullable=False, default=RunStatus.running)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    match_results: Mapped[list["MatchResult"]] = relationship(back_populates="run")
    exceptions: Mapped[list["ExceptionQueue"]] = relationship(back_populates="run")
    kpi_snapshots: Mapped[list["KpiSnapshot"]] = relationship(back_populates="run")


# ---------------------------------------------------------------------------
# Matching engine  (FR-06)
# ---------------------------------------------------------------------------

class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False)
    transaction_a_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    transaction_b_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    match_type: Mapped[MatchType] = mapped_column(pg_match_type, nullable=False)
    rule_matched: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_status: Mapped[MatchStatus] = mapped_column(
        pg_match_status, nullable=False, default=MatchStatus.pending_review
    )
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # SHAP explanation
    shap_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    matched_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    run: Mapped["ReconciliationRun"] = relationship(back_populates="match_results")


# ---------------------------------------------------------------------------
# Exception queue  (FR-07)
# ---------------------------------------------------------------------------

class ExceptionQueue(Base):
    __tablename__ = "exception_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    exception_type: Mapped[ExceptionType] = mapped_column(pg_exception_type, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    priority_level: Mapped[PriorityLevel] = mapped_column(
        pg_priority_level, nullable=False, default=PriorityLevel.medium
    )
    amount: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="AED")
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[ExceptionStatus] = mapped_column(
        pg_exception_status, nullable=False, default=ExceptionStatus.open
    )
    ai_suggested_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    run: Mapped["ReconciliationRun"] = relationship(back_populates="exceptions")
    assigned_to_user: Mapped[Optional["User"]] = relationship(back_populates="exceptions_assigned")
    resolutions: Mapped[list["ResolutionAction"]] = relationship(back_populates="exception")
    approvals: Mapped[list["ApprovalWorkflow"]] = relationship(back_populates="exception")


class ResolutionAction(Base):
    __tablename__ = "resolution_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey("exception_queue.id"), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(pg_action_type, nullable=False)
    resolved_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_transaction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    exception: Mapped["ExceptionQueue"] = relationship(back_populates="resolutions")
    resolved_by_user: Mapped["User"] = relationship(back_populates="resolutions")


# ---------------------------------------------------------------------------
# Workflow  (human-in-the-loop, FR-08)
# ---------------------------------------------------------------------------

class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey("exception_queue.id"), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        pg_approval_status, nullable=False, default=ApprovalStatus.pending
    )
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    exception: Mapped["ExceptionQueue"] = relationship(back_populates="approvals")
    approver: Mapped["User"] = relationship(back_populates="approvals")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    title_ar: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    message_ar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    related_entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    read_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    recipient: Mapped["User"] = relationship(back_populates="notifications")


# ---------------------------------------------------------------------------
# Audit  (FR-09 — immutable, append-only enforced by DB trigger in migration)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(256), nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), nullable=False)

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_entries")


# ---------------------------------------------------------------------------
# KPI snapshots  (FR-09)
# ---------------------------------------------------------------------------

class KpiSnapshot(Base):
    __tablename__ = "kpi_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=True)
    auto_reconciled_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    matching_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    manual_effort_reduction_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_to_close_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    run: Mapped[Optional["ReconciliationRun"]] = relationship(back_populates="kpi_snapshots")
