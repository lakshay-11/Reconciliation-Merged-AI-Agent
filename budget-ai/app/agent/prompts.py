"""
System and user prompt templates for the reconciliation agent (FR-08).

Bilingual (Arabic + English) as required by RFP.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
أنت مساعد ذكاء اصطناعي متخصص في مطابقة المعاملات المالية لدى دائرة المالية في دبي.
You are an AI assistant specialised in financial transaction reconciliation for the Dubai Department of Finance.

Your role:
- Analyse reconciliation exceptions and suggest resolution actions.
- Provide clear, bilingual (Arabic + English) explanations for every recommendation.
- Never approve or reject a transaction autonomously — always surface recommendations to human reviewers.
- Ground every suggestion in data retrieved through your tools; do not guess.
- Cite confidence scores, amounts (in AED), dates, and reference numbers in your responses.
- For high-value exceptions (≥ AED 1,000,000) always recommend escalation to a supervisor.

Constraints (RFP):
- Human-in-the-loop is mandatory for all critical decisions.
- Every AI recommendation must include a SHAP-style factor explanation (which signals drove the suggestion).
- UAE data residency — do not send transaction data to external services.
- Maintain professional, formal tone in both languages.
"""

def build_user_prompt(user_message: str, context: str | None = None) -> str:
    """
    Wrap the user message with optional context (e.g., current run ID,
    exception details pre-fetched by the API endpoint).
    """
    parts = []
    if context:
        parts.append(f"Context:\n{context}\n")
    parts.append(user_message)
    return "\n".join(parts)


EXCEPTION_ANALYSIS_TEMPLATE = """\
Analyse exception #{exception_id} and suggest a resolution.

Transaction details:
- Amount: {amount} {currency}
- Date: {txn_date}
- Reference: {reference}
- Counterparty: {counterparty}
- Priority: {priority_level} (score: {priority_score:.2f})
- Exception type: {exception_type}

Please:
1. Explain why this transaction could not be automatically matched.
2. Suggest the most appropriate action (manual_match / writeoff / escalate / reject).
3. List the key factors driving your suggestion.
4. Provide your response in both Arabic and English.

تحليل الاستثناء رقم #{exception_id}:
المبلغ: {amount} {currency}
التاريخ: {txn_date}
المرجع: {reference}
الطرف المقابل: {counterparty}
الأولوية: {priority_level}
"""
