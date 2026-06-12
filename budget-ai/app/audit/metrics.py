"""
KPI snapshot writer (FR-09).

After each reconciliation run, write a KpiSnapshot row so that
the dashboard and reports can track performance over time.

RFP KPIs tracked:
  - auto_reconciled_pct    (≥90% target)
  - matching_accuracy      (≥98% target)
  - exception_count
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import KpiSnapshot, ReconciliationRun

logger = logging.getLogger(__name__)


class KpiSnapshotWriter:
    """Compute and persist a KPI snapshot for a completed run."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def write(self, run: ReconciliationRun) -> KpiSnapshot:
        """
        Derive KPIs from run counters and insert a KpiSnapshot row.
        Caller must commit after this call.
        """
        total = run.total_transactions or 0
        matched = run.matched_count or 0
        exceptions = run.exception_count or 0
        auto_pct = run.auto_reconciled_pct or 0.0

        # matching_accuracy: matched / total (excludes exceptions)
        matching_accuracy = (
            round(matched / max(total, 1) * 100, 2) if total else 0.0
        )

        snapshot = KpiSnapshot(
            run_id=run.id,
            snapshot_date=run.run_date or date.today(),
            auto_reconciled_pct=auto_pct,
            matching_accuracy=matching_accuracy,
            exception_count=exceptions,
            manual_effort_reduction_pct=None,
            time_to_close_days=None,
        )
        self._db.add(snapshot)
        logger.info(
            "KPI snapshot run=%d auto=%.1f%% accuracy=%.1f%% exceptions=%d",
            run.id, auto_pct, matching_accuracy, exceptions,
        )
        return snapshot
