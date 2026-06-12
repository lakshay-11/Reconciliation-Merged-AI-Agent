"""
End-to-end integration test for the full reconciliation pipeline.

Each test gets a fresh DB session to avoid state contamination.

Run with:
    cd budget-ai
    python -m pytest tests/integration/test_reconciliation_pipeline.py -v -s
"""

from __future__ import annotations

import asyncio
import math
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

BANK_CSV = (
    "Transaction ID,Date,Value Date,Description,Reference No,Counterparty,Debit,Credit,Currency\n"
    "T-001,15/01/2025,15/01/2025,Vendor Payment ABC,REF-001,ABC Corporation,10000.00,,AED\n"
    "T-002,16/01/2025,16/01/2025,Customer Receipt,REF-002,XYZ Ltd,,5000.00,AED\n"
    "T-003,17/01/2025,17/01/2025,Utility Bill DEWA,REF-003,DEWA,750.00,,AED\n"
)

LEDGER_CSV = (
    "Doc No,Posting Date,GL Account,Cost Center,Narration,Vendor / Customer,Amount,Currency\n"
    "GL-001,15/01/2025,21000100,CC-FIN,ABC Corp Invoice REF-001,ABC Corporation,-10000.00,AED\n"
    "GL-002,16/01/2025,11000500,CC-FIN,Customer Receipt XYZ Ltd,XYZ Ltd,5000.00,AED\n"
    "GL-003,17/01/2025,52000100,CC-ADM,DEWA Utility Jan 2025,DEWA,-750.00,AED\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fresh_db():
    from app.db import get_db
    gen = get_db()
    return await gen.__anext__()


async def _create_sources(db):
    from app.db import SourceType, TransactionSource
    src_a = TransactionSource(name="IntTest Bank", name_ar="بنك", source_type=SourceType.bank)
    src_b = TransactionSource(name="IntTest Ledger", name_ar="دفتر", source_type=SourceType.ledger)
    db.add(src_a)
    db.add(src_b)
    await db.commit()
    await db.refresh(src_a)
    await db.refresh(src_b)
    return src_a, src_b


async def _ingest(db, source, csv_text, filename):
    from app.ingestion.ingest import IngestionPipeline
    pipeline = IngestionPipeline(db)
    report = await pipeline.run(
        source=source,
        file=csv_text.encode(),
        filename=filename,
    )
    if report.success:
        await db.commit()
    return report


# ---------------------------------------------------------------------------
# Tests (each creates its own isolated sources + session)
# ---------------------------------------------------------------------------

def test_normalizer_no_nan_amounts():
    """FR-05: Normalizer never stores NaN amounts from empty debit/credit cells."""
    from app.ingestion.normalizer import TransactionNormalizer

    rows = [
        {"Transaction ID": "T-1", "Date": "15/01/2025", "Debit": 125000.0, "Credit": float("nan"), "Currency": "AED"},
        {"Transaction ID": "T-2", "Date": "15/01/2025", "Debit": float("nan"), "Credit": 500000.0, "Currency": "AED"},
    ]
    norm = TransactionNormalizer()
    result = norm.normalize(rows)

    assert not math.isnan(result[0]["amount"]), "Debit row has NaN amount"
    assert result[0]["amount"] == -125000.0
    assert not math.isnan(result[1]["amount"]), "Credit row has NaN amount"
    assert result[1]["amount"] == 500000.0


def test_normalizer_vendor_customer_mapping():
    """FR-05: 'Vendor / Customer' column maps to 'counterparty'."""
    from app.ingestion.normalizer import TransactionNormalizer

    rows = [
        {
            "Doc No": "GL-001",
            "Posting Date": "15/01/2025",
            "Narration": "Test",
            "Vendor / Customer": "ABC Corporation",
            "Amount": -10000.0,
            "Currency": "AED",
        }
    ]
    norm = TransactionNormalizer()
    result = norm.normalize(rows)
    assert result[0]["counterparty"] == "ABC Corporation", "Vendor/Customer not mapped to counterparty"


def test_confidence_scoring():
    """FR-06: Confidence scorer produces correct weighted scores."""
    from app.matching.confidence import MatchCandidate, score, classify

    c = MatchCandidate(
        txn_a_id=1, txn_b_id=2,
        signals={
            "amount_match": 1.0,
            "date_proximity": 1.0,
            "reference_match": 0.0,
            "description_sim": 0.0,
            "counterparty_sim": 1.0,
        },
    )
    c = score(c)
    # Expected: 0.40 + 0.25 + 0 + 0 + 0.05 = 0.70
    assert abs(c.confidence - 0.70) < 0.01
    assert classify(c.confidence, 0.90, 0.70) == "pending_review"
    assert c.explanation  # non-empty


def test_explainability():
    """RFP mandate: SHAP-style explanation is bilingual."""
    from app.analytics.explainability import explain_match

    result = explain_match(
        signals={"amount_match": 1.0, "date_proximity": 1.0, "reference_match": 0.0,
                 "description_sim": 0.0, "counterparty_sim": 1.0},
        confidence=0.70,
    )
    assert result.narrative_en
    assert result.narrative_ar
    assert "70%" in result.narrative_en
    assert "amount_match" in result.top_factors


def test_prioritizer():
    """FR-07: Priority computation for exceptions."""
    from app.exceptions.prioritizer import compute_priority
    from datetime import date, timedelta

    score, level = compute_priority(
        amount=5_000_000.0,
        exception_type="unmatched",
        transaction_date=date.today() - timedelta(days=20),
    )
    assert level == "critical"
    assert score >= 0.80


@pytest.mark.asyncio
async def test_full_pipeline():
    """
    Full end-to-end: ingest → match → exception queue.
    Uses isolated sources to avoid interference with other data.
    """
    db = await _fresh_db()
    try:
        src_a, src_b = await _create_sources(db)

        # 1. Ingest
        r_bank = await _ingest(db, src_a, BANK_CSV, "bank.csv")
        assert r_bank.success, f"Bank ingestion failed: {r_bank.validation_errors}"
        assert r_bank.inserted == 3

        r_ledger = await _ingest(db, src_b, LEDGER_CSV, "ledger.csv")
        assert r_ledger.success, f"Ledger ingestion failed: {r_ledger.validation_errors}"
        assert r_ledger.inserted == 3

        # 2. Verify counterparty populated
        from app.db import Transaction
        from sqlalchemy import select
        r = await db.execute(select(Transaction).where(Transaction.source_id == src_b.id))
        ledger_txns = r.scalars().all()
        cp_set = {t.counterparty for t in ledger_txns if t.counterparty}
        assert "ABC Corporation" in cp_set, f"Counterparty not stored; got {cp_set}"

        # 3. Match
        from app.db import MatchResult, ReconciliationRun, RunStatus
        from app.matching.match_engine import MatchEngine

        run = ReconciliationRun(
            run_date=date.today(),
            source_a_id=src_a.id,
            source_b_id=src_b.id,
            status=RunStatus.running,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        engine = MatchEngine(db, use_ai=False)
        summary = await engine.run(run)

        assert summary.total_a == 3
        assert summary.total_b == 3
        # Expect at least 2 matches (all 3 have matching counterparty + amount + date)
        assert summary.auto_matched + summary.pending_review >= 2, (
            f"Too few matches: auto={summary.auto_matched} review={summary.pending_review}"
        )

        # 4. Match results persisted with explanations
        r2 = await db.execute(select(MatchResult).where(MatchResult.run_id == run.id))
        match_results = r2.scalars().all()
        assert len(match_results) >= 2
        for mr in match_results:
            assert mr.confidence_score > 0
            assert mr.explanation

        # 5. Exception queue
        from app.exceptions.exception_queue import ExceptionQueueBuilder
        from app.db import ExceptionQueue
        eq_builder = ExceptionQueueBuilder(db)
        n = await eq_builder.build(run.id, src_a.id, src_b.id)

        r3 = await db.execute(select(ExceptionQueue).where(ExceptionQueue.run_id == run.id))
        exceptions = r3.scalars().all()
        for exc in exceptions:
            assert exc.priority_score >= 0
            assert exc.priority_level is not None

        print(f"\nPipeline OK: matched={summary.auto_matched + summary.pending_review}/3 exceptions={n}")

    finally:
        # Best-effort cleanup using engine directly to avoid session state conflicts
        from app.db import ExceptionQueue, MatchResult, ReconciliationRun, Transaction, TransactionSource, engine
        from sqlalchemy import delete, text
        try:
            async with engine.begin() as conn:
                # Delete in FK dependency order
                src_ids = f"({src_a.id}, {src_b.id})"
                run_subq = f"(SELECT id FROM reconciliation_runs WHERE source_a_id = {src_a.id})"
                await conn.execute(text(f"DELETE FROM exception_queue WHERE run_id IN {run_subq}"))
                await conn.execute(text(f"DELETE FROM match_results WHERE run_id IN {run_subq}"))
                await conn.execute(text(f"DELETE FROM reconciliation_runs WHERE source_a_id = {src_a.id}"))
                await conn.execute(text(f"DELETE FROM transactions WHERE source_id IN {src_ids}"))
                await conn.execute(text(f"DELETE FROM transaction_sources WHERE id IN {src_ids}"))
        except Exception:
            pass
