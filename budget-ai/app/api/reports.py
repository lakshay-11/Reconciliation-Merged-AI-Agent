"""
Reports API (FR-09) — KPI dashboard data and audit log queries.

GET /api/reports/kpi/{run_id}        KPI snapshot for a run
GET /api/reports/runs                list recent runs
GET /api/reports/audit               query audit log
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuditLog, KpiSnapshot, ReconciliationRun, get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RunSummaryOut(BaseModel):
    id: int
    run_date: str
    status: str
    total_transactions: int
    matched_count: int
    exception_count: int
    auto_reconciled_pct: float | None
    duration_seconds: float | None
    model_config = {"from_attributes": True}


class KpiOut(BaseModel):
    id: int
    run_id: int | None
    snapshot_date: str
    auto_reconciled_pct: float | None
    matching_accuracy: float | None
    exception_count: int
    model_config = {"from_attributes": True}


class AuditOut(BaseModel):
    id: int
    event_type: str
    entity_type: str
    entity_id: int | None
    user_id: int | None
    action: str
    ip_address: str | None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=list[RunSummaryOut])
async def list_runs(db: DbDep, limit: int = 20):
    r = await db.execute(
        select(ReconciliationRun).order_by(desc(ReconciliationRun.id)).limit(limit)
    )
    runs = r.scalars().all()
    return [
        RunSummaryOut(
            id=run.id,
            run_date=str(run.run_date),
            status=run.status.value,
            total_transactions=run.total_transactions or 0,
            matched_count=run.matched_count or 0,
            exception_count=run.exception_count or 0,
            auto_reconciled_pct=run.auto_reconciled_pct,
            duration_seconds=run.duration_seconds,
        )
        for run in runs
    ]


@router.get("/kpi/{run_id}", response_model=KpiOut)
async def get_kpi(run_id: int, db: DbDep):
    r = await db.execute(
        select(KpiSnapshot).where(KpiSnapshot.run_id == run_id)
    )
    kpi = r.scalar_one_or_none()
    if not kpi:
        # Derive from run record if no snapshot exists yet
        rr = await db.execute(
            select(ReconciliationRun).where(ReconciliationRun.id == run_id)
        )
        run = rr.scalar_one_or_none()
        if not run:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return KpiOut(
            id=0,
            run_id=run.id,
            snapshot_date=str(run.run_date),
            auto_reconciled_pct=run.auto_reconciled_pct,
            matching_accuracy=None,
            exception_count=run.exception_count or 0,
        )
    return KpiOut(
        id=kpi.id,
        run_id=kpi.run_id,
        snapshot_date=str(kpi.snapshot_date),
        auto_reconciled_pct=kpi.auto_reconciled_pct,
        matching_accuracy=kpi.matching_accuracy,
        exception_count=kpi.exception_count,
    )


@router.get("/audit", response_model=list[AuditOut])
async def query_audit(
    db: DbDep,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 100,
):
    query = select(AuditLog).order_by(desc(AuditLog.id)).limit(limit)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    r = await db.execute(query)
    return r.scalars().all()
