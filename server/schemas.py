# server/schemas.py
# Purpose: Pydantic v2 models for validating /api/chat requests & shaping responses.
# Notes:
# - Keep DTOs close to the route surface; easy to re-use in docs/tests.

from __future__ import annotations

from typing import Literal, Optional, List  # <-- CHANGED: add List for details
from datetime import datetime               # <-- ADDED: for session DTOs

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)  # inline-change: guardrails
    model: Literal["gpt-3.5-turbo", "gpt-4"] = "gpt-3.5-turbo"  # inline-change: enum constraint
    session_id: Optional[str] = None  # <-- ADDED: optional session support


class ChatResponse(BaseModel):
    reply: str


class ErrorResponse(BaseModel):
    error: str
    code: int
    request_id: Optional[str] = None
    details: Optional[List[dict]] = None  # <-- CHANGED: optional validation details for 400s


# ---------------------- NEW: Sessions DTOs ----------------------
class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)  # <-- ADDED: optional title with a sensible max


class AppendMessageRequest(BaseModel):
    role: Literal["user", "assistant"]  # <-- ADDED: restrict roles
    content: str = Field(..., min_length=1)  # <-- ADDED: ensure non-empty content
    tokens: Optional[int] = Field(default=None, ge=0)  # <-- ADDED: optional non-negative token count


class SessionSummary(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None


class SessionDetail(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # messages list shape is provided by API; explicit message DTO optional here
