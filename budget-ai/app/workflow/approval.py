"""
Approval workflow (FR-07 human-in-the-loop, RFP TR-12).

Every critical exception resolution must go through an approval step.
This module creates ApprovalWorkflow records and processes approve/reject decisions.

Levels:
  - Step 1: finance_ops reviewer
  - Step 2 (critical/high): supervisor approval
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    ApprovalStatus, ApprovalWorkflow, ExceptionQueue,
    ExceptionStatus, PriorityLevel,
)

logger = logging.getLogger(__name__)

# Exceptions at this level or above require two-step approval
_TWO_STEP_LEVELS = {PriorityLevel.critical, PriorityLevel.high}


async def create_approval_request(
    db: AsyncSession,
    exception_id: int,
    approver_id: int,
    step_no: int = 1,
) -> ApprovalWorkflow:
    """
    Create an ApprovalWorkflow row for a given exception.
    Call this after the exception queue entry is created.
    """
    workflow = ApprovalWorkflow(
        exception_id=exception_id,
        step_no=step_no,
        approver_id=approver_id,
        status=ApprovalStatus.pending,
    )
    db.add(workflow)
    logger.info(
        "Approval request created: exception=%d step=%d approver=%d",
        exception_id, step_no, approver_id,
    )
    return workflow


async def process_decision(
    db: AsyncSession,
    workflow_id: int,
    decision: str,          # "approved" or "rejected"
    notes: str | None = None,
) -> ApprovalWorkflow:
    """
    Record an approve/reject decision on a workflow step.

    If approved and no further steps required, marks the exception as resolved.
    If rejected, marks the exception as escalated for manual review.
    """
    r = await db.execute(
        select(ApprovalWorkflow).where(ApprovalWorkflow.id == workflow_id)
    )
    workflow = r.scalar_one_or_none()
    if not workflow:
        raise ValueError(f"ApprovalWorkflow {workflow_id} not found")
    if workflow.status != ApprovalStatus.pending:
        raise ValueError(
            f"Workflow {workflow_id} is already {workflow.status.value}"
        )

    decision_status = (
        ApprovalStatus.approved if decision == "approved" else ApprovalStatus.rejected
    )
    now = datetime.now(UTC)

    await db.execute(
        update(ApprovalWorkflow)
        .where(ApprovalWorkflow.id == workflow_id)
        .values(
            status=decision_status,
            decision_notes=notes,
            decided_at=now,
        )
    )

    # Update exception status based on decision
    if decision == "approved":
        await db.execute(
            update(ExceptionQueue)
            .where(ExceptionQueue.id == workflow.exception_id)
            .values(status=ExceptionStatus.resolved, resolved_at=now)
        )
        logger.info("Exception %d approved via workflow %d", workflow.exception_id, workflow_id)
    else:
        await db.execute(
            update(ExceptionQueue)
            .where(ExceptionQueue.id == workflow.exception_id)
            .values(status=ExceptionStatus.escalated)
        )
        logger.info("Exception %d rejected, escalated via workflow %d", workflow.exception_id, workflow_id)

    workflow.status = decision_status
    workflow.decision_notes = notes
    workflow.decided_at = now
    return workflow


async def needs_two_step(db: AsyncSession, exception_id: int) -> bool:
    """Return True if this exception's priority requires supervisor approval."""
    r = await db.execute(
        select(ExceptionQueue.priority_level).where(ExceptionQueue.id == exception_id)
    )
    row = r.scalar_one_or_none()
    return row in _TWO_STEP_LEVELS if row else False
