"""
Exception queue builder (FR-07).

After the matching engine runs, this module identifies all transactions
that ended up as 'exception' status and inserts them into the
exception_queue table with priority scores.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ExceptionQueue, ExceptionStatus, ExceptionType, PriorityLevel, Transaction, TransactionStatus
from app.exceptions.prioritizer import compute_priority

logger = logging.getLogger(__name__)


class ExceptionQueueBuilder:
    """
    Scans exception-status transactions for a run and enqueues them.
    Only enqueues transactions not already present in the exception_queue
    from a prior run — prevents re-queuing the same transaction on every run.
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def build(self, run_id: int, source_a_id: int, source_b_id: int) -> int:
        """
        Creates ExceptionQueue rows for unmatched transactions in this run.
        Returns count of exceptions enqueued.
        """
        # Find transaction IDs already in the exception_queue from any run.
        # This prevents the same physical transaction being re-enqueued every
        # time a new run is triggered against the same source.
        already_queued = await self._db.execute(
            select(ExceptionQueue.transaction_id)
        )
        already_queued_ids = {row[0] for row in already_queued}

        result = await self._db.execute(
            select(Transaction).where(
                Transaction.source_id.in_([source_a_id, source_b_id]),
                Transaction.status == TransactionStatus.exception,
                Transaction.id.not_in(already_queued_ids) if already_queued_ids else True,
            )
        )
        unmatched = result.scalars().all()

        if not unmatched:
            logger.info("Run %d: no new exceptions to enqueue", run_id)
            return 0

        today = date.today()
        enqueued = 0

        for txn in unmatched:
            exc_type = ExceptionType.unmatched
            priority_score, priority_level = compute_priority(
                amount=float(txn.amount),
                exception_type=exc_type.value,
                transaction_date=txn.transaction_date,
                run_date=today,
            )

            exc = ExceptionQueue(
                run_id=run_id,
                transaction_id=txn.id,
                exception_type=exc_type,
                priority_score=priority_score,
                priority_level=PriorityLevel(priority_level),
                amount=txn.amount,
                currency=txn.currency,
                status=ExceptionStatus.open,
            )
            self._db.add(exc)
            enqueued += 1

        await self._db.commit()
        logger.info("Run %d: enqueued %d exceptions", run_id, enqueued)
        return enqueued
