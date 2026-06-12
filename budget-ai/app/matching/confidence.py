"""
Confidence scoring for match candidates (FR-06).

Each candidate carries a dict of signal scores; this module
combines them into a single [0.0 – 1.0] confidence score and
produces a human-readable explanation for every decision (RFP TR-10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Weight of each matching signal — must sum to 1.0
SIGNAL_WEIGHTS: dict[str, float] = {
    "amount_match":     0.40,   # exact or near-exact amount
    "date_proximity":   0.25,   # transaction date closeness
    "reference_match":  0.20,   # reference/doc number match
    "description_sim":  0.10,   # text similarity (from AI matcher)
    "counterparty_sim": 0.05,   # counterparty name similarity
}


@dataclass
class MatchCandidate:
    txn_a_id: int
    txn_b_id: int
    signals: dict[str, float] = field(default_factory=dict)   # signal → score [0,1]
    confidence: float = 0.0
    explanation: str = ""
    rule_matched: str | None = None
    match_type: str = "1:1"


def score(candidate: MatchCandidate) -> MatchCandidate:
    """
    Compute weighted confidence and build a plain-English explanation.
    Mutates and returns the candidate.
    """
    total = 0.0
    parts: list[str] = []

    for signal, weight in SIGNAL_WEIGHTS.items():
        value = candidate.signals.get(signal, 0.0)
        contribution = value * weight
        total += contribution
        if value > 0:
            parts.append(f"{_label(signal)} {value:.0%} (×{weight:.0%})")

    candidate.confidence = round(min(total, 1.0), 4)
    candidate.explanation = (
        f"Confidence {candidate.confidence:.0%}: " + "; ".join(parts)
        if parts else "No matching signals found."
    )
    return candidate


def _label(signal: str) -> str:
    return {
        "amount_match":     "Amount matched",
        "date_proximity":   "Date proximity",
        "reference_match":  "Reference matched",
        "description_sim":  "Description similarity",
        "counterparty_sim": "Counterparty similarity",
    }.get(signal, signal)


def classify(confidence: float, auto_threshold: float, review_threshold: float) -> str:
    """
    Return 'auto_matched', 'pending_review', or 'exception' based on thresholds
    configured in settings (RFP FR-06 confidence tiers).
    """
    if confidence >= auto_threshold:
        return "auto_matched"
    if confidence >= review_threshold:
        return "pending_review"
    return "exception"
