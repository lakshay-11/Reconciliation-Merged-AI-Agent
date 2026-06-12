"""
Immutable audit trail writer (FR-09, TR-11).

Every user action, AI decision, and system event is recorded here.
The underlying audit_log table has a PostgreSQL trigger that blocks
UPDATE and DELETE, making the log append-only at the database level.

Usage:
    await AuditWriter.log(db,
        event_type="reconciliation_run",
        entity_type="reconciliation_runs",
        entity_id=run.id,
        action="run_completed",
        new_value={"auto_pct": 92.5},
    )
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuditLog

logger = logging.getLogger(__name__)


class AuditWriter:
    """Append-only audit log writer. Caller owns the session commit."""

    @staticmethod
    async def log(
        db: AsyncSession,
        event_type: str,
        entity_type: str,
        action: str,
        entity_id: int | None = None,
        user_id: int | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        ip_address: str | None = None,
        session_id: str | None = None,
    ) -> AuditLog:
        """
        Append one immutable audit event.

        Parameters
        ----------
        db          : active async session — caller must commit
        event_type  : high-level category (e.g. 'reconciliation_run', 'exception_resolved')
        entity_type : table name (e.g. 'match_results', 'exception_queue')
        action      : specific action label (e.g. 'auto_matched', 'manual_match')
        entity_id   : PK of the affected row
        user_id     : user performing the action (None for system events)
        old_value   : JSON snapshot before change (for audit diff)
        new_value   : JSON snapshot after change
        ip_address  : request IP (for user actions)
        session_id  : request/session identifier
        """
        entry = AuditLog(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            session_id=session_id,
        )
        db.add(entry)
        logger.debug(
            "AUDIT event=%s action=%s %s#%s user=%s",
            event_type, action, entity_type, entity_id, user_id,
        )
        return entry

    @staticmethod
    async def log_run_completed(
        db: AsyncSession,
        run_id: int,
        auto_pct: float,
        matched: int,
        exceptions: int,
        duration_s: float,
    ) -> AuditLog:
        return await AuditWriter.log(
            db=db,
            event_type="reconciliation_run",
            entity_type="reconciliation_runs",
            entity_id=run_id,
            action="run_completed",
            new_value={
                "auto_reconciled_pct": auto_pct,
                "matched_count": matched,
                "exception_count": exceptions,
                "duration_seconds": duration_s,
            },
        )

    @staticmethod
    async def log_exception_resolved(
        db: AsyncSession,
        exception_id: int,
        action_taken: str,
        user_id: int,
        notes: str | None = None,
    ) -> AuditLog:
        return await AuditWriter.log(
            db=db,
            event_type="exception_resolution",
            entity_type="exception_queue",
            entity_id=exception_id,
            user_id=user_id,
            action=action_taken,
            new_value={"notes": notes},
        )
