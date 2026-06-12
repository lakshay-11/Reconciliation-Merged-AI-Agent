"""
SHAP-style explainability for match confidence scores (RFP mandate).

Every AI matching decision must include a human-readable explanation
of which signals drove the confidence score (bilingual AR + EN).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.matching.confidence import SIGNAL_WEIGHTS


@dataclass
class ExplanationResult:
    confidence: float
    classification: str
    contributions: dict[str, float]
    top_factors: list[str]
    narrative_en: str
    narrative_ar: str


_LABELS_EN: dict[str, str] = {
    "amount_match":     "Amount match",
    "date_proximity":   "Date proximity",
    "reference_match":  "Reference number match",
    "description_sim":  "Description similarity",
    "counterparty_sim": "Counterparty match",
}

_LABELS_AR: dict[str, str] = {
    "amount_match":     "تطابق المبلغ",
    "date_proximity":   "قرب التاريخ",
    "reference_match":  "تطابق رقم المرجع",
    "description_sim":  "تشابه الوصف",
    "counterparty_sim": "تطابق الطرف المقابل",
}


def explain_match(
    signals: dict[str, float],
    confidence: float,
    auto_threshold: float = 0.90,
    review_threshold: float = 0.70,
) -> ExplanationResult:
    """
    SHAP-style explanation: weighted signal contributions for a match decision.

    Returns bilingual narrative + structured factor breakdown.
    """
    if confidence >= auto_threshold:
        classification = "auto_matched"
    elif confidence >= review_threshold:
        classification = "pending_review"
    else:
        classification = "exception"

    contributions: dict[str, float] = {
        sig: round(SIGNAL_WEIGHTS.get(sig, 0.0) * score, 4)
        for sig, score in signals.items()
    }

    top_factors = [
        k for k, v in sorted(contributions.items(), key=lambda x: x[1], reverse=True)
        if v > 0
    ][:3]

    factor_strs_en = [
        f"{_LABELS_EN.get(f, f)} ({contributions[f]*100:.0f}%)" for f in top_factors
    ]
    factor_strs_ar = [
        f"{_LABELS_AR.get(f, f)} ({contributions[f]*100:.0f}%)" for f in top_factors
    ]

    classification_ar = {
        "auto_matched":   "مطابقة تلقائية",
        "pending_review": "قيد المراجعة",
        "exception":      "استثناء",
    }.get(classification, classification)

    narrative_en = (
        f"Confidence {confidence*100:.0f}%: "
        + (", ".join(factor_strs_en) or "no strong signals")
        + f". Decision: {classification.replace('_', ' ')}."
    )
    narrative_ar = (
        f"درجة الثقة {confidence*100:.0f}%: "
        + (", ".join(factor_strs_ar) or "لم تُوجد إشارات قوية")
        + f". القرار: {classification_ar}."
    )

    return ExplanationResult(
        confidence=confidence,
        classification=classification,
        contributions=contributions,
        top_factors=top_factors,
        narrative_en=narrative_en,
        narrative_ar=narrative_ar,
    )


def explain_exception(
    exception_type: str,
    amount: float,
    priority_score: float,
    priority_level: str,
) -> dict[str, str]:
    """Bilingual plain-language explanation for an exception."""
    labels = {
        "unmatched":      ("No matching counterpart found", "لم يتم العثور على مقابل"),
        "low_confidence": ("Match found but confidence too low", "مطابقة بثقة منخفضة"),
        "ambiguous":      ("Multiple possible matches", "مطابقات متعددة محتملة"),
        "duplicate":      ("Possible duplicate transaction", "معاملة مكررة محتملة"),
    }
    label_en, label_ar = labels.get(exception_type, (exception_type, exception_type))
    return {
        "en": (
            f"{label_en}. Amount: AED {abs(amount):,.2f}. "
            f"Priority: {priority_level} (score {priority_score:.2f})."
        ),
        "ar": (
            f"{label_ar}. المبلغ: {abs(amount):,.2f} درهم. "
            f"الأولوية: {priority_level} (النتيجة {priority_score:.2f})."
        ),
    }
