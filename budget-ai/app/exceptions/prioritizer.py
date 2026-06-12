"""
Exception prioritizer (FR-07).

Computes a priority_score [0–1] and priority_level for each unmatched
or low-confidence transaction.  Score is based on:
  - Amount (higher AED value → higher priority)
  - Age (older unmatched → escalates priority)
  - Exception type (unmatched > low_confidence > ambiguous)

RFP requirement: exceptions must be prioritized by value and risk.
"""

from __future__ import annotations

from datetime import date
from typing import Any


# Weights
_W_AMOUNT = 0.55
_W_AGE    = 0.25
_W_TYPE   = 0.20

# Type scores
_TYPE_SCORES: dict[str, float] = {
    "unmatched":       1.0,
    "low_confidence":  0.65,
    "ambiguous":       0.45,
    "duplicate":       0.30,
}

# Amount bands (AED) → score
_AMOUNT_BANDS: list[tuple[float, float]] = [
    (10_000_000, 1.00),
    (1_000_000,  0.85),
    (500_000,    0.70),
    (100_000,    0.55),
    (50_000,     0.40),
    (10_000,     0.25),
    (0,          0.10),
]


def compute_priority(
    amount: float,
    exception_type: str,
    transaction_date: date | None,
    run_date: date | None = None,
) -> tuple[float, str]:
    """
    Returns (priority_score, priority_level).
    priority_level: 'critical' | 'high' | 'medium' | 'low'
    """
    today = run_date or date.today()

    amount_score = _amount_score(abs(amount))
    age_score    = _age_score(transaction_date, today)
    type_score   = _TYPE_SCORES.get(exception_type, 0.30)

    score = round(
        _W_AMOUNT * amount_score
        + _W_AGE   * age_score
        + _W_TYPE  * type_score,
        4,
    )

    level = _level(score)
    return score, level


def _amount_score(amount: float) -> float:
    for threshold, score in _AMOUNT_BANDS:
        if amount >= threshold:
            return score
    return 0.05


def _age_score(txn_date: date | None, today: date) -> float:
    if txn_date is None:
        return 0.5
    age_days = (today - txn_date).days
    if age_days <= 1:
        return 0.10
    if age_days <= 3:
        return 0.35
    if age_days <= 7:
        return 0.60
    if age_days <= 14:
        return 0.80
    return 1.00


def _level(score: float) -> str:
    if score >= 0.80:
        return "critical"
    if score >= 0.55:
        return "high"
    if score >= 0.30:
        return "medium"
    return "low"
