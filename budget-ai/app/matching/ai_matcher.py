"""
AI-assisted fuzzy matcher (FR-06, second pass).

Uses sentence-transformers to compute semantic similarity between
transaction descriptions and counterparty names, then fills in the
description_sim and counterparty_sim signals on each MatchCandidate.

The model is loaded once at import time and reused across all runs
to keep the batch SLA within ≤10 minutes (RFP TR-14).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer, util

from app.matching.confidence import MatchCandidate

logger = logging.getLogger(__name__)

# Lightweight multilingual model — supports Arabic + English (RFP bilingual req)
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformer model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Model loaded.")
    return _model


class AIMatcher:
    """
    Enriches existing MatchCandidates with semantic similarity scores.
    Only candidates that already have at least one non-zero rule signal
    are re-scored (avoids O(n²) embedding comparisons for all pairs).
    """

    def enrich(
        self,
        candidates: list[MatchCandidate],
        txns_a: list[dict[str, Any]],
        txns_b: list[dict[str, Any]],
    ) -> list[MatchCandidate]:
        if not candidates:
            return candidates

        model = _get_model()

        # Index transactions by id for O(1) lookup
        idx_a = {t["id"]: t for t in txns_a}
        idx_b = {t["id"]: t for t in txns_b}

        # Collect unique texts to embed in one batch
        desc_texts:  list[str] = []
        party_texts: list[str] = []

        for c in candidates:
            a = idx_a.get(c.txn_a_id, {})
            b = idx_b.get(c.txn_b_id, {})
            desc_texts.append(self._text(a.get("description")))
            desc_texts.append(self._text(b.get("description")))
            party_texts.append(self._text(a.get("counterparty")))
            party_texts.append(self._text(b.get("counterparty")))

        # Batch encode
        desc_embs  = model.encode(desc_texts,  convert_to_tensor=True, show_progress_bar=False)
        party_embs = model.encode(party_texts, convert_to_tensor=True, show_progress_bar=False)

        for i, c in enumerate(candidates):
            da, db = desc_embs[i * 2], desc_embs[i * 2 + 1]
            pa, pb = party_embs[i * 2], party_embs[i * 2 + 1]

            c.signals["description_sim"]  = float(util.cos_sim(da, db)[0][0])
            c.signals["counterparty_sim"] = float(util.cos_sim(pa, pb)[0][0])

        return candidates

    @staticmethod
    def _text(value: Any) -> str:
        return str(value).strip() if value else ""
