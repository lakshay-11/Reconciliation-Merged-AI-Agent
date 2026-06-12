"""
Exceptions API (FR-07) — manage the exception queue.

GET  /api/exceptions                      list open exceptions (filterable)
GET  /api/exceptions/{id}                 get exception details
POST /api/exceptions/{id}/resolve         resolve an exception (human action)
POST /api/exceptions/{id}/analyse         ask the AI agent to analyse an exception
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import ReconciliationAgent
from app.audit.audit import AuditWriter
from app.db import (
    ActionType, ExceptionQueue, ExceptionStatus,
    PriorityLevel, Transaction, get_db,
)
from app.exceptions.resolution import resolve_exception

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExceptionOut(BaseModel):
    id: int
    run_id: int
    transaction_id: int
    exception_type: str
    priority_score: float
    priority_level: str
    amount: float
    currency: str
    status: str
    ai_suggested_action: str | None
    model_config = {"from_attributes": True}


class ResolveRequest(BaseModel):
    action_type: str            # manual_match / reject / writeoff / escalate
    resolved_by: int            # user_id (auth will inject this later)
    notes: str | None = None
    matched_transaction_id: int | None = None


class AnalyseResponse(BaseModel):
    exception_id: int
    response: str
    suggested_action: str | None
    tool_calls_made: int
    human_approval_required: bool = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ExceptionOut])
async def list_exceptions(
    db: DbDep,
    run_id: int | None = None,
    priority_level: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    """List exceptions, optionally filtered by run, priority, and status."""
    query = select(ExceptionQueue)
    if run_id:
        query = query.where(ExceptionQueue.run_id == run_id)
    if priority_level:
        query = query.where(ExceptionQueue.priority_level == PriorityLevel(priority_level))
    if status:
        query = query.where(ExceptionQueue.status == ExceptionStatus(status))
    else:
        query = query.where(ExceptionQueue.status == ExceptionStatus.open)
    query = query.order_by(ExceptionQueue.priority_score.desc()).limit(limit)
    r = await db.execute(query)
    return r.scalars().all()


@router.get("/{exception_id}", response_model=ExceptionOut)
async def get_exception(exception_id: int, db: DbDep):
    r = await db.execute(select(ExceptionQueue).where(ExceptionQueue.id == exception_id))
    exc = r.scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")
    return exc


@router.post("/{exception_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve(exception_id: int, body: ResolveRequest, db: DbDep):
    """
    Record a human resolution for an exception (FR-07 human-in-the-loop).
    Human approval is mandatory — this endpoint IS the approval gate.
    """
    try:
        action = ActionType(body.action_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {body.action_type}")

    try:
        resolution = await resolve_exception(
            db=db,
            exception_id=exception_id,
            action_type=action,
            resolved_by=body.resolved_by,
            notes=body.notes,
            matched_transaction_id=body.matched_transaction_id,
            ai_suggested=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Immutable audit entry
    await AuditWriter.log(
        db=db,
        event_type="exception_resolution",
        entity_type="exception_queue",
        entity_id=exception_id,
        user_id=body.resolved_by,
        action=body.action_type,
        new_value={"notes": body.notes, "resolution_id": resolution.id},
    )
    await db.commit()
    return {"message": "resolved", "resolution_id": resolution.id}


@router.post("/{exception_id}/analyse", response_model=AnalyseResponse)
async def analyse_exception(exception_id: int, db: DbDep):
    """
    Use the AI agent to analyse an exception and suggest a resolution.
    Returns a recommendation — human must approve before any action is taken.
    """
    r = await db.execute(select(ExceptionQueue).where(ExceptionQueue.id == exception_id))
    exc = r.scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")

    agent = ReconciliationAgent(db)
    result = await agent.chat(
        user_message=f"Analyse exception {exception_id} and suggest a resolution action.",
        context=f"run_id={exc.run_id}, priority={exc.priority_level.value}, amount={exc.amount} {exc.currency}",
    )

    # Extract suggested action from tool call log if present
    suggested_action: str | None = None
    for call in result.get("tool_calls", []):
        if call.get("tool") == "suggest_resolution":
            suggested_action = call.get("result", {}).get("suggested_action")

    return AnalyseResponse(
        exception_id=exception_id,
        response=result["response"],
        suggested_action=suggested_action,
        tool_calls_made=len(result.get("tool_calls", [])),
        human_approval_required=True,
    )
