# server/schemas.py
# Purpose: Pydantic v2 models for validating /api/chat requests & shaping responses.
# Notes:
# - Keep DTOs close to the route surface; easy to re-use in docs/tests.

# CHANGED: removed inline import comments + normalized formatting so Ruff I001/Black/isort pass
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(
        ..., min_length=1, max_length=4000
    )  # CHANGED: Black formatting only (no behavior change)
    model: Literal["gpt-3.5-turbo", "gpt-4"] = (
        "gpt-3.5-turbo"  # CHANGED: Black formatting only (no behavior change)
    )
    session_id: Optional[str] = None  # <-- ADDED: optional session support


class ChatResponse(BaseModel):
    reply: str


class ErrorResponse(BaseModel):
    error: str
    code: int
    request_id: Optional[str] = None
    details: Optional[List[dict]] = (
        None  # CHANGED: Black formatting only (no behavior change)
    )


# ---------------------- Sessions DTOs ----------------------
class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(
        default=None, max_length=200
    )  # CHANGED: Black formatting only (no behavior change)

    @field_validator(
        "title", mode="before"
    )  # <-- CHANGED: run BEFORE built-in constraints
    @classmethod
    def _strip_or_none(cls, v: Optional[str]) -> Optional[str]:
        """
        Normalize title on create: trim whitespace; treat empty/whitespace-only as None.
        This lets the server apply a default title gracefully instead of 400.  # <-- CHANGED
        """
        if v is None:
            return None
        if isinstance(v, str):
            stripped = v.strip()
            return stripped or None
        return v


class UpdateSessionRequest(BaseModel):  # <-- ADDED: DTO for PATCH /api/sessions/:id
    title: str = Field(
        ..., min_length=1, max_length=200
    )  # CHANGED: Black formatting only (no behavior change)

    @field_validator(
        "title", mode="before"
    )  # <-- CHANGED: ensure whitespace-only becomes invalid BEFORE min_length
    @classmethod
    def _strip_and_require_nonempty(cls, v: str) -> str:
        """
        Normalize & validate: trim and ensure non-empty after trimming.         # <-- CHANGED
        """
        if v is None:
            raise ValueError("Title cannot be empty or whitespace.")
        if not isinstance(v, str):
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or whitespace.")
        return stripped


class AppendMessageRequest(BaseModel):
    role: Literal["user", "assistant"]  # restrict roles
    content: str = Field(..., min_length=1)  # ensure non-empty content
    tokens: Optional[int] = Field(
        default=None, ge=0
    )  # CHANGED: Black formatting only (no behavior change)


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
