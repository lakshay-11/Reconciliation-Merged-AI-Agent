"""
Anomaly detection for reconciliation transactions (RFP FR-06, FR-07).

Uses scikit-learn Isolation Forest to flag statistical outliers.
Anomalous transactions are surfaced in the exception queue with higher priority.

Features: log_amount, amount_zscore, day_of_week
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from sklearn.ensemble import IsolationForest
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed — anomaly detection disabled")


@dataclass
class AnomalyResult:
    transaction_id: int
    is_anomaly: bool
    anomaly_score: float      # raw sklearn score (lower = more anomalous)
    normalized_score: float   # 0=normal, 1=most anomalous


class TransactionAnomalyDetector:
    """Isolation Forest anomaly detector for a batch of transactions."""

    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 100,
        random_state: int = 42,
    ):
        self._contamination = contamination
        self._n_estimators = n_estimators
        self._random_state = random_state

    def detect(self, transactions: list[dict[str, Any]]) -> list[AnomalyResult]:
        if not transactions:
            return []

        if not _SKLEARN_AVAILABLE or len(transactions) < 5:
            return [
                AnomalyResult(transaction_id=t["id"], is_anomaly=False,
                              anomaly_score=1.0, normalized_score=0.0)
                for t in transactions
            ]

        features = self._extract_features(transactions)
        model = IsolationForest(
            n_estimators=self._n_estimators,
            contamination=self._contamination,
            random_state=self._random_state,
        )
        raw_scores  = model.fit(features).score_samples(features)
        predictions = model.predict(features)  # -1=anomaly, 1=normal

        min_s, max_s = raw_scores.min(), raw_scores.max()
        rng = max_s - min_s if max_s != min_s else 1.0
        normalized = (max_s - raw_scores) / rng

        return [
            AnomalyResult(
                transaction_id=t["id"],
                is_anomaly=bool(predictions[i] == -1),
                anomaly_score=float(raw_scores[i]),
                normalized_score=round(float(normalized[i]), 4),
            )
            for i, t in enumerate(transactions)
        ]

    @staticmethod
    def _extract_features(transactions: list[dict[str, Any]]) -> np.ndarray:
        amounts = [abs(float(t.get("amount") or 0)) for t in transactions]
        mean_amt = float(np.mean(amounts)) if amounts else 1.0
        std_amt  = float(np.std(amounts))  if amounts else 1.0

        rows = []
        for t in transactions:
            amt = abs(float(t.get("amount") or 0))
            amt_z = (amt - mean_amt) / (std_amt + 1e-9)
            log_amt = float(np.log1p(amt))

            day_of_week = 0
            txn_date = t.get("transaction_date")
            if txn_date is not None:
                try:
                    from datetime import date
                    if isinstance(txn_date, str):
                        txn_date = date.fromisoformat(str(txn_date))
                    day_of_week = txn_date.weekday()
                except Exception:
                    pass

            rows.append([log_amt, amt_z, float(day_of_week)])

        return np.array(rows, dtype=float)
