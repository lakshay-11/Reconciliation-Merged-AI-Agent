"""
Reconciliation AI Agent orchestrator (FR-08).

Uses Anthropic Claude tool-calling to:
  - Analyse exceptions and suggest resolutions
  - Answer analyst questions about reconciliation runs
  - Route follow-up actions (never approves autonomously)

Human-in-the-loop: every suggestion is returned as a recommendation.
Approval/rejection is handled by the workflow module, not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agent.tools import TOOLS
from app.config import settings
from app.db import (
    ExceptionQueue, ExceptionStatus, MatchResult,
    PriorityLevel, ReconciliationRun, Transaction,
)

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


class ReconciliationAgent:
    """
    LLM-powered agent for exception analysis and resolution recommendations.

    Parameters
    ----------
    db : active async SQLAlchemy session for tool execution
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        self._client = _get_client()

    async def chat(
        self,
        user_message: str,
        context: str | None = None,
        max_tool_rounds: int = 5,
    ) -> dict[str, Any]:
        """
        Send a message to the agent and return its final text response
        along with any tool calls it made.

        Returns
        -------
        {
            "response": str,          # final assistant text
            "tool_calls": list[dict], # tools invoked during the conversation
        }
        """
        messages: list[dict] = [
            {"role": "user", "content": build_user_prompt(user_message, context)},
        ]
        tool_call_log: list[dict] = []

        for _round in range(max_tool_rounds):
            resp = await self._client.messages.create(
                model=settings.llm_model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Append assistant message
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "end_turn":
                # Extract final text
                text = next(
                    (b.text for b in resp.content if hasattr(b, "text")),
                    "",
                )
                return {"response": text, "tool_calls": tool_call_log}

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    result = await self._dispatch_tool(block.name, block.input)
                    tool_call_log.append({
                        "tool": block.name,
                        "input": block.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        # Fallback — return whatever text is in the last assistant message
        last_text = ""
        if messages and messages[-1]["role"] == "assistant":
            for block in messages[-1]["content"]:
                if hasattr(block, "text"):
                    last_text = block.text
                    break
        return {"response": last_text, "tool_calls": tool_call_log}

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        dispatch = {
            "get_exception_details": self._tool_get_exception_details,
            "list_exceptions":       self._tool_list_exceptions,
            "suggest_resolution":    self._tool_suggest_resolution,
            "get_match_result":      self._tool_get_match_result,
            "get_run_summary":       self._tool_get_run_summary,
            "search_transactions":   self._tool_search_transactions,
        }
        handler = dispatch.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        try:
            return await handler(**inputs)
        except Exception as exc:
            logger.exception("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _tool_get_exception_details(self, exception_id: int) -> dict:
        r = await self._db.execute(
            select(ExceptionQueue).where(ExceptionQueue.id == exception_id)
        )
        exc = r.scalar_one_or_none()
        if not exc:
            return {"error": f"Exception {exception_id} not found"}
        txn = None
        if exc.transaction_id:
            tr = await self._db.execute(
                select(Transaction).where(Transaction.id == exc.transaction_id)
            )
            txn = tr.scalar_one_or_none()
        return {
            "id": exc.id,
            "run_id": exc.run_id,
            "exception_type": exc.exception_type.value,
            "priority_score": float(exc.priority_score),
            "priority_level": exc.priority_level.value,
            "amount": float(exc.amount) if exc.amount is not None else None,
            "currency": exc.currency,
            "status": exc.status.value,
            "transaction": {
                "id": txn.id,
                "reference_no": txn.reference_no,
                "description": txn.description,
                "counterparty": txn.counterparty,
                "transaction_date": str(txn.transaction_date),
                "amount": float(txn.amount),
                "currency": txn.currency,
            } if txn else None,
        }

    async def _tool_list_exceptions(
        self,
        run_id: int,
        priority_level: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        query = select(ExceptionQueue).where(
            ExceptionQueue.run_id == run_id,
            ExceptionQueue.status == ExceptionStatus.open,
        )
        if priority_level:
            query = query.where(
                ExceptionQueue.priority_level == PriorityLevel(priority_level)
            )
        query = query.order_by(ExceptionQueue.priority_score.desc()).limit(limit)
        r = await self._db.execute(query)
        exceptions = r.scalars().all()
        return [
            {
                "id": e.id,
                "exception_type": e.exception_type.value,
                "priority_level": e.priority_level.value,
                "priority_score": float(e.priority_score),
                "amount": float(e.amount) if e.amount is not None else None,
                "currency": e.currency,
                "transaction_id": e.transaction_id,
            }
            for e in exceptions
        ]

    async def _tool_suggest_resolution(self, exception_id: int) -> dict:
        details = await self._tool_get_exception_details(exception_id)
        if "error" in details:
            return details
        amount = details.get("amount") or 0
        priority = details.get("priority_level", "low")
        # Rule-based suggestion (deterministic fallback, not LLM recursion)
        if priority == "critical" or amount >= 1_000_000:
            action = "escalate"
            reason_en = "High-value transaction (≥ AED 1,000,000) requires supervisor approval."
            reason_ar = "المعاملة عالية القيمة (≥ مليون درهم) تتطلب موافقة المشرف."
        elif priority == "high":
            action = "manual_match"
            reason_en = "High-priority exception — review transaction details manually to identify counterpart."
            reason_ar = "استثناء ذو أولوية عالية — راجع تفاصيل المعاملة يدوياً للعثور على المقابل."
        else:
            action = "manual_match"
            reason_en = "Review and manually match or reject this transaction."
            reason_ar = "راجع المعاملة وطابقها يدوياً أو ارفضها."

        return {
            "exception_id": exception_id,
            "suggested_action": action,
            "reason_en": reason_en,
            "reason_ar": reason_ar,
            "factors": {
                "amount": details.get("amount"),
                "priority_level": priority,
                "exception_type": details.get("exception_type"),
            },
            "human_approval_required": True,
        }

    async def _tool_get_match_result(self, match_result_id: int) -> dict:
        r = await self._db.execute(
            select(MatchResult).where(MatchResult.id == match_result_id)
        )
        mr = r.scalar_one_or_none()
        if not mr:
            return {"error": f"MatchResult {match_result_id} not found"}
        return {
            "id": mr.id,
            "run_id": mr.run_id,
            "transaction_a_id": mr.transaction_a_id,
            "transaction_b_id": mr.transaction_b_id,
            "match_type": mr.match_type.value,
            "rule_matched": mr.rule_matched,
            "confidence_score": float(mr.confidence_score),
            "match_status": mr.match_status.value,
            "explanation": mr.explanation,
        }

    async def _tool_get_run_summary(self, run_id: int) -> dict:
        r = await self._db.execute(
            select(ReconciliationRun).where(ReconciliationRun.id == run_id)
        )
        run = r.scalar_one_or_none()
        if not run:
            return {"error": f"Run {run_id} not found"}
        return {
            "run_id": run.id,
            "run_date": str(run.run_date),
            "status": run.status.value,
            "total_transactions": run.total_transactions,
            "matched_count": run.matched_count,
            "exception_count": run.exception_count,
            "auto_reconciled_pct": run.auto_reconciled_pct,
            "duration_seconds": run.duration_seconds,
        }

    async def _tool_search_transactions(
        self,
        query: str,
        source_id: int | None = None,
        limit: int = 5,
    ) -> list[dict]:
        stmt = select(Transaction).where(
            or_(
                Transaction.reference_no.ilike(f"%{query}%"),
                Transaction.description.ilike(f"%{query}%"),
                Transaction.counterparty.ilike(f"%{query}%"),
            )
        )
        if source_id is not None:
            stmt = stmt.where(Transaction.source_id == source_id)
        stmt = stmt.limit(limit)
        r = await self._db.execute(stmt)
        txns = r.scalars().all()
        return [
            {
                "id": t.id,
                "source_id": t.source_id,
                "reference_no": t.reference_no,
                "description": t.description,
                "counterparty": t.counterparty,
                "amount": float(t.amount),
                "currency": t.currency,
                "transaction_date": str(t.transaction_date),
                "status": t.status.value,
            }
            for t in txns
        ]
