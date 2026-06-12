"""
Reconciliation API — FR-05 (ingestion) + FR-06 (matching run)

POST /api/reconciliation/sources                  create a source
GET  /api/reconciliation/sources                  list sources
POST /api/reconciliation/ingest/{source_id}       upload & ingest file
POST /api/reconciliation/run                      start a reconciliation run
GET  /api/reconciliation/run/{run_id}             fetch run status & summary
GET  /api/reconciliation/run/{run_id}/results     fetch match results
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    MatchResult, ReconciliationRun, RunStatus,
    SourceType, TransactionSource, get_db,
)
from app.audit.audit import AuditWriter
from app.audit.metrics import KpiSnapshotWriter
from app.exceptions.exception_queue import ExceptionQueueBuilder
from app.ingestion.ingest import IngestionPipeline, IngestionReport
from app.matching.match_engine import MatchEngine, MatchSummary

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str
    name_ar: str = ""
    source_type: SourceType


class SourceRead(BaseModel):
    id: int
    name: str
    name_ar: str
    source_type: str
    is_active: bool
    model_config = {"from_attributes": True}


class IngestResponse(BaseModel):
    source_id: int
    source_name: str
    total_rows: int
    inserted: int
    skipped_duplicates: int
    error_count: int
    errors: list[dict]
    duration_seconds: float | None
    success: bool


class RunRequest(BaseModel):
    source_a_id: int    # bank / primary source
    source_b_id: int    # ledger / secondary source
    run_date: date | None = None
    use_ai: bool = True


class RunResponse(BaseModel):
    run_id: int
    status: str
    total_a: int
    total_b: int
    auto_matched: int
    pending_review: int
    exceptions: int
    auto_reconciled_pct: float
    duration_seconds: float
    message: str


class MatchResultOut(BaseModel):
    id: int
    transaction_a_id: int
    transaction_b_id: int
    match_type: str
    rule_matched: str | None
    confidence_score: float
    match_status: str
    explanation: str | None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Routes — Sources
# ---------------------------------------------------------------------------

@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceCreate, db: DbDep):
    source = TransactionSource(
        name=body.name,
        name_ar=body.name_ar,
        source_type=body.source_type,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(db: DbDep):
    result = await db.execute(
        select(TransactionSource).where(TransactionSource.is_active.is_(True))
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Routes — Ingestion (FR-05)
# ---------------------------------------------------------------------------

@router.post("/ingest/{source_id}", response_model=IngestResponse)
async def ingest_file(
    source_id: int,
    db: DbDep,
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
):
    """Upload a bank statement or ledger file and run the ingestion pipeline."""
    result = await db.execute(
        select(TransactionSource).where(TransactionSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    if not source.is_active:
        raise HTTPException(status_code=400, detail=f"Source {source_id} is inactive")

    content = await file.read()
    pipeline = IngestionPipeline(db)
    report: IngestionReport = await pipeline.run(
        source=source,
        file=content,
        filename=file.filename or "",
        sheet=sheet,
    )

    if report.success:
        await db.commit()
    else:
        await db.rollback()

    return IngestResponse(
        source_id=report.source_id,
        source_name=report.source_name,
        total_rows=report.total_rows,
        inserted=report.inserted,
        skipped_duplicates=report.skipped_duplicates,
        error_count=len(report.validation_errors),
        errors=[
            {"row": e.row_index, "field": e.field, "message": e.message}
            for e in report.validation_errors
        ],
        duration_seconds=report.duration_seconds,
        success=report.success,
    )


# ---------------------------------------------------------------------------
# Routes — Reconciliation Run (FR-06 + FR-07)
# ---------------------------------------------------------------------------

@router.post("/run", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def start_run(body: RunRequest, db: DbDep):
    """
    Start a reconciliation run: match source_a against source_b,
    score confidence, classify matches, and queue exceptions.
    """
    # Validate sources exist
    for sid in (body.source_a_id, body.source_b_id):
        r = await db.execute(select(TransactionSource).where(TransactionSource.id == sid))
        if not r.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Source {sid} not found")

    # Create run record
    run = ReconciliationRun(
        run_date=body.run_date or date.today(),
        source_a_id=body.source_a_id,
        source_b_id=body.source_b_id,
        status=RunStatus.running,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Execute matching engine
    engine = MatchEngine(db, use_ai=body.use_ai)
    summary: MatchSummary = await engine.run(run)

    # Build exception queue for unmatched transactions (FR-07)
    eq_builder = ExceptionQueueBuilder(db)
    await eq_builder.build(run.id, body.source_a_id, body.source_b_id)

    # Write KPI snapshot (FR-09)
    await db.refresh(run)
    kpi_writer = KpiSnapshotWriter(db)
    await kpi_writer.write(run)
    await db.commit()

    # Write audit entry
    await AuditWriter.log_run_completed(
        db=db,
        run_id=run.id,
        auto_pct=summary.auto_reconciled_pct,
        matched=summary.auto_matched + summary.pending_review,
        exceptions=summary.exceptions,
        duration_s=summary.duration_seconds,
    )
    await db.commit()

    return RunResponse(
        run_id=run.id,
        status="completed",
        total_a=summary.total_a,
        total_b=summary.total_b,
        auto_matched=summary.auto_matched,
        pending_review=summary.pending_review,
        exceptions=summary.exceptions,
        auto_reconciled_pct=summary.auto_reconciled_pct,
        duration_seconds=summary.duration_seconds,
        message=(
            f"Auto-reconciled {summary.auto_reconciled_pct:.1f}% of source A transactions. "
            f"{summary.exceptions} exception(s) queued for review."
        ),
    )


@router.get("/run/{run_id}", response_model=RunResponse)
async def get_run(run_id: int, db: DbDep):
    r = await db.execute(select(ReconciliationRun).where(ReconciliationRun.id == run_id))
    run = r.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunResponse(
        run_id=run.id,
        status=run.status.value,
        total_a=run.total_transactions // 2 if run.total_transactions else 0,
        total_b=run.total_transactions // 2 if run.total_transactions else 0,
        auto_matched=run.matched_count or 0,
        pending_review=0,
        exceptions=run.exception_count or 0,
        auto_reconciled_pct=run.auto_reconciled_pct or 0.0,
        duration_seconds=run.duration_seconds or 0.0,
        message=run.error_message or "OK",
    )


@router.get("/run/{run_id}/results", response_model=list[MatchResultOut])
async def get_run_results(run_id: int, db: DbDep):
    r = await db.execute(
        select(MatchResult).where(MatchResult.run_id == run_id)
    )
    return r.scalars().all()
