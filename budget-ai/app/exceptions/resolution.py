"""
Exception resolution handler (FR-07).

Records a human resolution action for an open exception
and updates its status to 'resolved'.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    ActionType, ApprovalStatus, ApprovalWorkflow,
    ExceptionQueue, ExceptionStatus, ResolutionAction,
)


async def resolve_exception(
    db: AsyncSession,
    exception_id: int,
    action_type: ActionType,
    resolved_by: int,
    notes: str | None = None,
    matched_transaction_id: int | None = None,
    ai_suggested: bool = False,
) -> ResolutionAction:
    """
    Record a resolution action for an exception and close it.

    Parameters
    ----------
    db                    : async session — caller must commit
    exception_id          : exception_queue.id to resolve
    action_type           : ActionType enum (manual_match / reject / writeoff / escalate)
    resolved_by           : user_id of the resolver
    notes                 : free-text resolution notes
    matched_transaction_id: for manual_match — the counterpart transaction
    ai_suggested          : True if this action was suggested by the LLM agent
    """
    # Verify exception exists and is open
    r = await db.execute(
        select(ExceptionQueue).where(ExceptionQueue.id == exception_id)
    )
    exc = r.scalar_one_or_none()
    if exc is None:
        raise ValueError(f"Exception {exception_id} not found")
    if exc.status != ExceptionStatus.open:
        raise ValueError(f"Exception {exception_id} is not open (status: {exc.status.value})")

    # Create resolution record
    resolution = ResolutionAction(
        exception_id=exception_id,
        action_type=action_type,
        resolved_by=resolved_by,
        resolution_notes=notes,
        matched_transaction_id=matched_transaction_id,
        ai_suggested=ai_suggested,
    )
    db.add(resolution)

    # Mark exception as resolved
    now = datetime.now(UTC)
    await db.execute(
        update(ExceptionQueue)
        .where(ExceptionQueue.id == exception_id)
        .values(
            status=ExceptionStatus.resolved,
            resolved_at=now,
        )
    )

    return resolution
