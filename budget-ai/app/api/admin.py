"""
Admin API — RBAC, user management, source management.

GET  /api/admin/users              list users
POST /api/admin/users              create user
GET  /api/admin/roles              list roles
GET  /api/admin/notifications/{id} get notifications for a user
POST /api/admin/workflow/{id}/decide  approve or reject a workflow step
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    ApprovalWorkflow, Notification, Role, User, get_db,
)
from app.workflow.approval import process_decision

router = APIRouter(prefix="/api/admin", tags=["admin"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RoleOut(BaseModel):
    id: int
    name: str
    name_ar: str
    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str | None
    full_name_ar: str | None
    role_id: int | None
    is_active: bool
    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    email: str
    password_hash: str
    full_name: str = ""
    full_name_ar: str = ""
    role_id: int | None = None


class NotificationOut(BaseModel):
    id: int
    notification_type: str
    title: str
    title_ar: str
    message: str
    is_read: bool
    related_entity_type: str | None
    related_entity_id: int | None
    model_config = {"from_attributes": True}


class WorkflowDecisionRequest(BaseModel):
    decision: str    # "approved" or "rejected"
    notes: str | None = None


class WorkflowOut(BaseModel):
    id: int
    exception_id: int
    step_no: int
    approver_id: int
    status: str
    decision_notes: str | None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: DbDep):
    r = await db.execute(select(Role))
    return r.scalars().all()


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbDep):
    r = await db.execute(select(User).where(User.is_active.is_(True)))
    return r.scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DbDep):
    user = User(
        username=body.username,
        email=body.email,
        password_hash=body.password_hash,
        full_name=body.full_name,
        full_name_ar=body.full_name_ar,
        role_id=body.role_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/notifications/{user_id}", response_model=list[NotificationOut])
async def get_notifications(user_id: int, db: DbDep, unread_only: bool = False):
    query = select(Notification).where(Notification.recipient_id == user_id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    query = query.order_by(desc(Notification.id)).limit(50)
    r = await db.execute(query)
    return r.scalars().all()


@router.post("/workflow/{workflow_id}/decide", response_model=WorkflowOut)
async def decide_workflow(
    workflow_id: int,
    body: WorkflowDecisionRequest,
    db: DbDep,
):
    """Approve or reject a workflow approval step (human-in-the-loop gate)."""
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approved' or 'rejected'",
        )
    try:
        workflow = await process_decision(
            db=db,
            workflow_id=workflow_id,
            decision=body.decision,
            notes=body.notes,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return WorkflowOut(
        id=workflow.id,
        exception_id=workflow.exception_id,
        step_no=workflow.step_no,
        approver_id=workflow.approver_id,
        status=workflow.status.value,
        decision_notes=workflow.decision_notes,
    )
