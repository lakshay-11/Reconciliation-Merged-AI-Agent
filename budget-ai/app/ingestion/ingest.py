"""
IngestionPipeline — orchestrates the full FR-05 ingestion flow:

  file(s)
    -> reader (BankStatementReader | LedgerReader)
    -> normalizer
    -> validator
    -> bulk-insert into transactions table
    -> return IngestionReport
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Transaction, TransactionSource
from app.ingestion.bank_reader import BankStatementReader
from app.ingestion.ledger_reader import LedgerReader
from app.ingestion.normalizer import TransactionNormalizer
from app.ingestion.validator import TransactionValidator, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class IngestionReport:
    source_id: int
    source_name: str
    started_at: datetime
    completed_at: datetime | None = None
    total_rows: int = 0
    inserted: int = 0
    skipped_duplicates: int = 0
    validation_errors: list[ValidationError] = field(default_factory=list)
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.error_message is None

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class IngestionPipeline:
    """
    Stateless pipeline — instantiate once, call `run()` per file.

    Parameters
    ----------
    db : AsyncSession
        Active SQLAlchemy async session (injected by FastAPI dependency).
    batch_size : int
        Number of rows per bulk-insert batch (default 500).
    """

    def __init__(self, db: AsyncSession, batch_size: int = 500):
        self._db = db
        self._batch_size = batch_size
        self._normalizer = TransactionNormalizer()
        self._validator = TransactionValidator()

    async def run(
        self,
        source: TransactionSource,
        file: str | Path | bytes,
        filename: str = "",
        sheet: str | int | None = None,
    ) -> IngestionReport:
        """
        Ingest one file for `source`. Returns an IngestionReport.
        Does NOT commit — caller commits after reviewing the report.
        """
        report = IngestionReport(
            source_id=source.id,
            source_name=source.name,
            started_at=datetime.now(UTC),
        )

        try:
            raw_rows = self._read(source, file, filename, sheet)
            report.total_rows = len(raw_rows)
            logger.info("Source %s: read %d rows from %s", source.name, report.total_rows, filename or file)

            normalized = self._normalizer.normalize(raw_rows)
            validation = self._validator.validate(normalized)
            report.validation_errors = validation.errors

            if validation.errors:
                logger.warning(
                    "Source %s: %d validation errors (of %d rows)",
                    source.name, validation.error_count, report.total_rows,
                )

            inserted, skipped = await self._bulk_insert(source.id, validation.valid)
            report.inserted = inserted
            report.skipped_duplicates = skipped

        except Exception as exc:
            logger.exception("Ingestion failed for source %s: %s", source.name, exc)
            report.error_message = str(exc)
        finally:
            report.completed_at = datetime.now(UTC)

        logger.info(
            "Source %s: ingestion complete — inserted=%d skipped=%d errors=%d duration=%.2fs",
            source.name, report.inserted, report.skipped_duplicates,
            len(report.validation_errors), report.duration_seconds or 0,
        )
        return report

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _read(
        self,
        source: TransactionSource,
        file: str | Path | bytes,
        filename: str,
        sheet: str | int | None,
    ) -> list[dict[str, Any]]:
        source_type = source.source_type.value if hasattr(source.source_type, "value") else source.source_type
        if source_type in ("bank", "manual"):
            return BankStatementReader().read(file, filename)
        if source_type in ("ledger", "erp"):
            return LedgerReader().read(file, filename, sheet=sheet)
        raise ValueError(f"No reader configured for source_type={source_type!r}")

    async def _bulk_insert(self, source_id: int, rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Insert rows, skipping any whose external_id already exists for this source.
        Returns (inserted_count, skipped_count).
        """
        if not rows:
            return 0, 0

        # Fetch existing external_ids for this source so we can skip duplicates.
        # This makes ingestion idempotent — uploading the same file twice is safe.
        existing_result = await self._db.execute(
            select(Transaction.external_id).where(
                Transaction.source_id == source_id,
                Transaction.external_id.is_not(None),
            )
        )
        existing_external_ids = {row[0] for row in existing_result}

        records = []
        skipped = 0
        for r in rows:
            ext_id = r.get("external_id")
            if ext_id and ext_id in existing_external_ids:
                logger.debug("Skipping duplicate external_id=%s for source %d", ext_id, source_id)
                skipped += 1
                continue
            records.append({
                "source_id": source_id,
                "external_id": ext_id,
                "amount": r["amount"],
                "currency": r.get("currency", "AED"),
                "transaction_date": self._to_date(r["transaction_date"]),
                "value_date": self._to_date(r.get("value_date")),
                "description": r.get("description"),
                "reference_no": r.get("reference_no"),
                "counterparty": r.get("counterparty"),
                "raw_data": self._sanitise_json(r.get("raw_data", {})),
            })

        if not records:
            return 0, skipped

        for i in range(0, len(records), self._batch_size):
            batch = records[i : i + self._batch_size]
            await self._db.execute(insert(Transaction), batch)

        return len(records), skipped

    @staticmethod
    def _to_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _sanitise_json(obj: Any) -> Any:
        """Replace NaN/Inf with None so the dict is safe to store as JSONB."""
        if isinstance(obj, dict):
            return {k: IngestionPipeline._sanitise_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [IngestionPipeline._sanitise_json(v) for v in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
