"""
Match Engine orchestrator (FR-06).

Pipeline per reconciliation run:
  1. Load all pending transactions for source_a and source_b
  2. Run RuleMatcher  → raw candidates with deterministic signals
  3. Run AIMatcher    → enrich candidates with semantic signals
  4. Score each candidate via confidence.py
  5. Deduplicate: keep highest-confidence candidate per transaction pair
  6. Classify: auto_matched / pending_review / exception
  7. Persist MatchResult rows and update transaction statuses
  8. Return MatchSummary

Target: ≥90% auto-reconciliation rate, ≥98% matching accuracy (RFP KPIs)
Batch SLA: ≤10 minutes total (RFP TR-14)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, UTC
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import (
    MatchResult, MatchStatus, MatchType, ReconciliationRun,
    RunStatus, Transaction, TransactionStatus,
)
from app.matching.ai_matcher import AIMatcher
from app.matching.confidence import MatchCandidate, classify, score
from app.matching.rule_matcher import RuleMatcher

logger = logging.getLogger(__name__)


@dataclass
class MatchSummary:
    run_id: int
    total_a: int
    total_b: int
    auto_matched: int = 0
    pending_review: int = 0
    exceptions: int = 0
    duration_seconds: float = 0.0
    auto_reconciled_pct: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class MatchEngine:
    """
    Orchestrates the full matching pipeline for one reconciliation run.

    Parameters
    ----------
    db          : active async SQLAlchemy session
    use_ai      : if False, skips AI enrichment (faster for testing)
    """

    def __init__(self, db: AsyncSession, use_ai: bool = True):
        self._db = db
        self._rule_matcher = RuleMatcher()
        self._ai_matcher = AIMatcher() if use_ai else None

    async def run(self, recon_run: ReconciliationRun) -> MatchSummary:
        summary = MatchSummary(run_id=recon_run.id, total_a=0, total_b=0)
        t0 = datetime.now(UTC)

        try:
            # 1. Load pending transactions for each source
            txns_a = await self._load_transactions(recon_run.source_a_id)
            txns_b = await self._load_transactions(recon_run.source_b_id)
            summary.total_a = len(txns_a)
            summary.total_b = len(txns_b)
            logger.info("Run %d: source_a=%d txns, source_b=%d txns", recon_run.id, summary.total_a, summary.total_b)

            if not txns_a or not txns_b:
                logger.warning("Run %d: one or both sources are empty — nothing to match.", recon_run.id)
                return summary

            # 2. Rule-based matching
            candidates = self._rule_matcher.match(txns_a, txns_b)
            logger.info("Run %d: rule matcher produced %d candidates", recon_run.id, len(candidates))

            # 3. AI enrichment
            if self._ai_matcher and candidates:
                candidates = self._ai_matcher.enrich(candidates, txns_a, txns_b)

            # 4. Score all candidates
            candidates = [score(c) for c in candidates]

            # 5. Deduplicate — keep best candidate per (txn_a, txn_b) pair,
            #    then pick the best match per transaction (greedy 1:1)
            candidates = self._deduplicate(candidates)

            # 6. Classify and persist
            auto_threshold   = settings.auto_match_confidence_threshold
            review_threshold = settings.review_confidence_threshold

            matched_a_ids: set[int] = set()
            matched_b_ids: set[int] = set()

            for c in candidates:
                status_label = classify(c.confidence, auto_threshold, review_threshold)
                match_status = {
                    "auto_matched":   MatchStatus.auto_matched,
                    "pending_review": MatchStatus.pending_review,
                    "exception":      MatchStatus.pending_review,   # low-conf → still saved, flagged as exception later
                }.get(status_label, MatchStatus.pending_review)

                result = MatchResult(
                    run_id=recon_run.id,
                    transaction_a_id=c.txn_a_id,
                    transaction_b_id=c.txn_b_id,
                    match_type=MatchType.one_to_one,
                    rule_matched=c.rule_matched,
                    confidence_score=c.confidence,
                    match_status=match_status,
                    explanation=c.explanation,
                )
                self._db.add(result)

                if status_label == "auto_matched":
                    summary.auto_matched += 1
                    matched_a_ids.add(c.txn_a_id)
                    matched_b_ids.add(c.txn_b_id)
                elif status_label == "pending_review":
                    summary.pending_review += 1
                    matched_a_ids.add(c.txn_a_id)
                    matched_b_ids.add(c.txn_b_id)
                else:
                    summary.exceptions += 1

            # 7. Update transaction statuses
            all_a_ids = {t["id"] for t in txns_a}
            all_b_ids = {t["id"] for t in txns_b}
            unmatched_a = all_a_ids - matched_a_ids
            unmatched_b = all_b_ids - matched_b_ids

            if matched_a_ids | matched_b_ids:
                await self._db.execute(
                    update(Transaction)
                    .where(Transaction.id.in_(matched_a_ids | matched_b_ids))
                    .values(status=TransactionStatus.matched)
                )
            if unmatched_a | unmatched_b:
                await self._db.execute(
                    update(Transaction)
                    .where(Transaction.id.in_(unmatched_a | unmatched_b))
                    .values(status=TransactionStatus.exception)
                )
                summary.exceptions += len(unmatched_a) + len(unmatched_b)

            # 8. Update run record
            total_processed = summary.total_a + summary.total_b
            summary.auto_reconciled_pct = (
                round(summary.auto_matched / max(summary.total_a, 1) * 100, 2)
            )
            summary.duration_seconds = (datetime.now(UTC) - t0).total_seconds()
            summary.completed_at = datetime.now(UTC)

            await self._db.execute(
                update(ReconciliationRun)
                .where(ReconciliationRun.id == recon_run.id)
                .values(
                    matched_count=summary.auto_matched + summary.pending_review,
                    exception_count=summary.exceptions,
                    auto_reconciled_pct=summary.auto_reconciled_pct,
                    total_transactions=total_processed,
                    status=RunStatus.completed,
                    completed_at=summary.completed_at,
                    duration_seconds=summary.duration_seconds,
                )
            )
            await self._db.commit()
            logger.info(
                "Run %d complete — auto=%d review=%d exception=%d pct=%.1f%% in %.1fs",
                recon_run.id, summary.auto_matched, summary.pending_review,
                summary.exceptions, summary.auto_reconciled_pct, summary.duration_seconds,
            )

        except Exception as exc:
            await self._db.rollback()
            await self._db.execute(
                update(ReconciliationRun)
                .where(ReconciliationRun.id == recon_run.id)
                .values(status=RunStatus.failed, error_message=str(exc))
            )
            await self._db.commit()
            logger.exception("Run %d failed: %s", recon_run.id, exc)
            raise

        return summary

    # ------------------------------------------------------------------

    async def _load_transactions(self, source_id: int) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(
                Transaction.id,
                Transaction.amount,
                Transaction.currency,
                Transaction.transaction_date,
                Transaction.value_date,
                Transaction.description,
                Transaction.reference_no,
                Transaction.external_id,
                Transaction.counterparty,
            ).where(
                Transaction.source_id == source_id,
                Transaction.status == TransactionStatus.pending,
            )
        )
        return [row._asdict() for row in result.fetchall()]

    @staticmethod
    def _deduplicate(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
        # Keep highest-confidence candidate per unique pair
        pair_best: dict[tuple[int, int], MatchCandidate] = {}
        for c in candidates:
            key = (c.txn_a_id, c.txn_b_id)
            if key not in pair_best or c.confidence > pair_best[key].confidence:
                pair_best[key] = c

        # Greedy assignment: each transaction can appear in at most one match
        used_a: set[int] = set()
        used_b: set[int] = set()
        chosen: list[MatchCandidate] = []
        for c in sorted(pair_best.values(), key=lambda x: x.confidence, reverse=True):
            if c.txn_a_id not in used_a and c.txn_b_id not in used_b:
                chosen.append(c)
                used_a.add(c.txn_a_id)
                used_b.add(c.txn_b_id)
        return chosen
