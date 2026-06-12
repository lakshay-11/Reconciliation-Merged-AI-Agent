"""
Agent chat API (FR-08).

POST /api/agent/chat   — send a message to the reconciliation AI agent
"""

from __future__ import annotations

from typing import Annotated, Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import ReconciliationAgent
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


class ChatRequest(BaseModel):
    message: str
    context: str | None = None


class ToolCallOut(BaseModel):
    tool: str
    input: dict[str, Any]
    result: Any


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[ToolCallOut]


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(body: ChatRequest, db: DbDep):
    """Send a free-form message to the reconciliation AI agent.

    The agent may call internal tools (fetch exception details, list runs,
    search transactions, etc.) before returning a bilingual recommendation.
    All suggestions require human approval — the agent never takes action
    autonomously (RFP FR-08 human-in-the-loop mandate).
    """
    if not settings.anthropic_api_key or settings.anthropic_api_key == "your-anthropic-api-key-here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured. Add your key to the .env file.",
        )

    try:
        agent = ReconciliationAgent(db)
        result = await agent.chat(user_message=body.message, context=body.context)
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Anthropic API key is invalid. Check ANTHROPIC_API_KEY in your .env file.",
        )
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Anthropic rate limit reached. Please try again shortly.",
        )
    except anthropic.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic API error: {exc}",
        )

    return ChatResponse(
        response=result["response"],
        tool_calls=[
            ToolCallOut(tool=tc["tool"], input=tc["input"], result=tc["result"])
            for tc in result["tool_calls"]
        ],
    )
