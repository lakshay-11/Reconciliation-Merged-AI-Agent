"""
LLM tool definitions (FR-08).

These are the Anthropic tool-calling schemas passed to the Claude API.
Each tool maps to a real async function in agent.py that executes
against the database.

Tool catalog:
  get_exception_details    — fetch a single exception + linked transaction
  list_exceptions          — list open exceptions for a run (filtered/sorted)
  suggest_resolution       — propose an action for an exception
  get_match_result         — retrieve a match result with confidence explanation
  get_run_summary          — reconciliation run KPIs
  search_transactions      — full-text search across transactions
"""

from __future__ import annotations

# Anthropic tool schemas (passed as `tools=` list to the API)
TOOLS: list[dict] = [
    {
        "name": "get_exception_details",
        "description": (
            "Retrieve full details of a single reconciliation exception: "
            "the transaction amount, date, reference, counterparty, priority score, "
            "and any existing resolution actions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exception_id": {
                    "type": "integer",
                    "description": "Primary key of the exception_queue row.",
                },
            },
            "required": ["exception_id"],
        },
    },
    {
        "name": "list_exceptions",
        "description": (
            "List open exceptions for a reconciliation run. "
            "Can filter by priority level (critical/high/medium/low) and limit results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "Reconciliation run to query.",
                },
                "priority_level": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Filter to this priority level only (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "suggest_resolution",
        "description": (
            "Generate a suggested resolution action for an exception based on "
            "transaction details, counterparty history, and the reconciliation context. "
            "Returns one of: manual_match, writeoff, escalate, reject. "
            "Also provides a plain-language explanation in Arabic and English."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exception_id": {
                    "type": "integer",
                    "description": "Exception to analyze.",
                },
            },
            "required": ["exception_id"],
        },
    },
    {
        "name": "get_match_result",
        "description": (
            "Retrieve a specific match result including confidence score, "
            "rule that triggered it, and the human-readable explanation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "match_result_id": {
                    "type": "integer",
                    "description": "Primary key of the match_results row.",
                },
            },
            "required": ["match_result_id"],
        },
    },
    {
        "name": "get_run_summary",
        "description": (
            "Return KPI summary for a completed reconciliation run: "
            "total transactions, auto-matched count, exception count, "
            "auto-reconciliation rate, and duration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "Reconciliation run ID.",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "search_transactions",
        "description": (
            "Full-text search across transactions by reference number, "
            "description, or counterparty. Useful for finding the ledger entry "
            "that should match an unmatched bank transaction."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (reference, description, or counterparty name).",
                },
                "source_id": {
                    "type": "integer",
                    "description": "Limit to a specific source (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
]
