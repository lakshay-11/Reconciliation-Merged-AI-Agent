"""
Rule-based matcher (FR-06, first pass).

Applies deterministic rules in priority order against pairs of transactions
from Source A (bank) and Source B (ledger).  Returns MatchCandidates with
signal scores filled in; final confidence is computed by confidence.py.

Rules applied (in order):
  R1 — Exact reference number match + exact amount  → high signals
  R2 — Exact amount + date within tolerance         → medium signals
  R3 — Reference partial match + amount within tol  → lower signals
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.matching.confidence import MatchCandidate


# Tolerances
AMOUNT_EXACT_TOLERANCE = 0.01       # ≤1 fils difference counts as exact
AMOUNT_NEAR_TOLERANCE  = 0.005      # ≤0.5% relative difference
DATE_EXACT_DAYS        = 0
DATE_NEAR_DAYS         = 3          # within 3 calendar days (value date lag)


class RuleMatcher:
    """
    Stateless rule engine — call match(txns_a, txns_b) to get candidates.

    Parameters
    ----------
    amount_tol : absolute amount tolerance (AED)
    date_tol   : date tolerance in calendar days
    """

    def __init__(
        self,
        amount_tol: float = AMOUNT_EXACT_TOLERANCE,
        date_tol: int = DATE_NEAR_DAYS,
    ):
        self._amount_tol = amount_tol
        self._date_tol = date_tol

    def match(
        self,
        txns_a: list[dict[str, Any]],
        txns_b: list[dict[str, Any]],
    ) -> list[MatchCandidate]:
        """
        Compare every transaction in txns_a against every transaction in txns_b.
        Returns only candidates with at least one non-zero signal.
        """
        candidates: list[MatchCandidate] = []

        for a in txns_a:
            for b in txns_b:
                signals = self._score_pair(a, b)
                if any(v > 0 for v in signals.values()):
                    rule = self._best_rule(signals)
                    candidates.append(
                        MatchCandidate(
                            txn_a_id=a["id"],
                            txn_b_id=b["id"],
                            signals=signals,
                            rule_matched=rule,
                        )
                    )

        return candidates

    # ------------------------------------------------------------------

    def _score_pair(self, a: dict, b: dict) -> dict[str, float]:
        signals: dict[str, float] = {}

        signals["amount_match"]     = self._amount_score(a, b)
        signals["date_proximity"]   = self._date_score(a, b)
        signals["reference_match"]  = self._reference_score(a, b)
        signals["counterparty_sim"] = self._counterparty_score(a, b)
        signals["description_sim"]  = 0.0   # filled by AI matcher

        # If bank reference appears in ledger description or vice-versa,
        # boost reference_match (handles "PO-30041 in description" case)
        if signals["reference_match"] < 0.75:
            signals["reference_match"] = max(
                signals["reference_match"],
                self._cross_ref_score(a, b),
            )

        return signals

    def _amount_score(self, a: dict, b: dict) -> float:
        amt_a = abs(float(a.get("amount", 0) or 0))
        amt_b = abs(float(b.get("amount", 0) or 0))
        if amt_a == 0 and amt_b == 0:
            return 0.0
        diff = abs(amt_a - amt_b)
        # Exact
        if diff <= self._amount_tol:
            return 1.0
        # Near (relative)
        base = max(amt_a, amt_b)
        if base > 0 and (diff / base) <= AMOUNT_NEAR_TOLERANCE:
            return 0.85
        # Within 1%
        if base > 0 and (diff / base) <= 0.01:
            return 0.60
        return 0.0

    def _date_score(self, a: dict, b: dict) -> float:
        d_a = self._to_date(a.get("transaction_date"))
        d_b = self._to_date(b.get("transaction_date"))
        if d_a is None or d_b is None:
            return 0.0
        gap = abs((d_a - d_b).days)
        if gap == 0:
            return 1.0
        if gap <= 1:
            return 0.90
        if gap <= self._date_tol:
            return 0.70
        return 0.0

    def _reference_score(self, a: dict, b: dict) -> float:
        ref_a = self._clean_ref(a.get("reference_no") or a.get("external_id") or "")
        ref_b = self._clean_ref(b.get("reference_no") or b.get("external_id") or "")
        if not ref_a or not ref_b:
            return 0.0
        if ref_a == ref_b:
            return 1.0
        # One contains the other
        if ref_a in ref_b or ref_b in ref_a:
            return 0.75
        return 0.0

    @staticmethod
    def _clean_ref(ref: str) -> str:
        return re.sub(r"[\s\-_/]", "", ref).upper()

    @staticmethod
    def _to_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if value is None:
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _counterparty_score(a: dict, b: dict) -> float:
        cp_a = (a.get("counterparty") or "").strip().upper()
        cp_b = (b.get("counterparty") or "").strip().upper()
        if not cp_a or not cp_b:
            return 0.0
        if cp_a == cp_b:
            return 1.0
        # Partial containment (e.g. "DEWA" in "DUBAI ELECTRICITY & WATER AUTHORITY")
        if cp_a in cp_b or cp_b in cp_a:
            return 0.70
        return 0.0

    @staticmethod
    def _cross_ref_score(a: dict, b: dict) -> float:
        """Check if bank reference appears in ledger description or vice-versa."""
        ref_a = (a.get("reference_no") or "").strip()
        ref_b = (b.get("reference_no") or "").strip()
        desc_a = (a.get("description") or "").upper()
        desc_b = (b.get("description") or "").upper()
        if ref_a and len(ref_a) >= 4 and ref_a.upper() in desc_b:
            return 0.80
        if ref_b and len(ref_b) >= 4 and ref_b.upper() in desc_a:
            return 0.80
        return 0.0

    @staticmethod
    def _best_rule(signals: dict[str, float]) -> str:
        ref   = signals.get("reference_match", 0)
        amt   = signals.get("amount_match", 0)
        dated = signals.get("date_proximity", 0)
        if ref >= 1.0 and amt >= 1.0:
            return "R1:exact_ref_amount"
        if amt >= 1.0 and dated >= 0.70:
            return "R2:exact_amount_date"
        if ref >= 0.75 and amt >= 0.60:
            return "R3:partial_ref_amount"
        return "R_weak"
