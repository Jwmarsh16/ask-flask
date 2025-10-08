# server/schemas.py
# Purpose: Pydantic v2 models for validating /api/chat requests & shaping responses.
# Notes:
# - Keep DTOs close to the route surface; easy to re-use in docs/tests.

from __future__ import annotations

from typing import Literal, Optional, List  # <-- CHANGED: add List for details

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)  # inline-change: guardrails
    model: Literal["gpt-3.5-turbo", "gpt-4"] = "gpt-3.5-turbo"  # inline-change: enum constraint


class ChatResponse(BaseModel):
    reply: str


class ErrorResponse(BaseModel):
    error: str
    code: int
    request_id: Optional[str] = None
    details: Optional[List[dict]] = None  # <-- CHANGED: optional validation details for 400s
