# server/services/openai_client.py
# Purpose: Single place for OpenAI calls with retries, jitter, and a minimal
# circuit breaker. Keeps Flask routes thin and testable.
# Notes:
# - Accepts an already-configured OpenAI client (from server.app).
# - Emits lightweight logs via the provided logger (optional).
# - Fully typed; friendly to mypy.

from __future__ import annotations

import logging  # stdlib logging interface
import random
import time
from typing import Any, Dict, Iterator, List, Optional


class OpenAIService:
    """Typed façade around the OpenAI client.

    Features:
    - Per-call retries with exponential backoff + jitter
    - Minimal circuit breaker (opens after N consecutive failures)
    - Thin, explicit surface usable by Flask routes and tests
    """

    def __init__(
        self,
        client: Any,  # OpenAI() instance injected by the app  # inline-change: explicit dependency injection
        logger: Optional[
            logging.Logger
        ] = None,  # inline-change: optional structured logger
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        breaker_threshold: int = 3,
        breaker_cooldown: float = 20.0,
    ) -> None:
        self._client = client
        self._logger = logger
        self._timeout = timeout
        self._max_retries = max_retries
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown = breaker_cooldown
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    # ---- Circuit breaker helpers -------------------------------------------------

    def _check_breaker(self) -> None:
        now = time.monotonic()
        if now < self._breaker_open_until:
            # Breaker is open → fail fast
            raise RuntimeError("circuit_open")  # inline-change: explicit failure mode

    def _record_success(self) -> None:
        self._consecutive_failures = 0  # inline-change: reset on success

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._breaker_threshold:
            self._breaker_open_until = time.monotonic() + self._breaker_cooldown
            if self._logger:
                self._logger.error(
                    "circuit opened",
                    extra={
                        "event": "breaker.open",
                        "cooldown_s": self._breaker_cooldown,
                        "failures": self._consecutive_failures,
                    },
                )

    # ---- Public API --------------------------------------------------------------

    def complete(self, model: str, messages: List[Dict[str, str]]) -> str:
        """Non-streaming completion: returns the assistant text."""
        self._check_breaker()
        attempt = 0
        while True:
            try:
                resp = self._client.chat.completions.create(  # type: ignore[no-untyped-call]
                    model=model,
                    messages=messages,
                    timeout=self._timeout,  # inline-change: per-request timeout hint
                )
                self._record_success()
                content = (resp.choices[0].message.content or "").strip()

                if self._logger:
                    usage = getattr(resp, "usage", None)
                    extra = {"event": "openai.chat.complete", "model": model}
                    if usage:
                        extra.update(
                            {
                                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                                "completion_tokens": getattr(
                                    usage, "completion_tokens", None
                                ),
                                "total_tokens": getattr(usage, "total_tokens", None),
                            }
                        )
                    self._logger.info("openai chat complete", extra=extra)

                return content
            except Exception as exc:  # noqa: BLE001
                if self._logger:
                    self._logger.warning(
                        "openai chat error",
                        extra={
                            "event": "openai.chat.error",
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
                self._record_failure()
                if attempt >= self._max_retries:
                    raise
                backoff = min(1.0 * (2**attempt), 5.0) + random.uniform(
                    0, 0.25
                )  # inline-change: jitter
                time.sleep(backoff)
                attempt += 1

    def stream(self, model: str, messages: List[Dict[str, str]]) -> Iterator[str]:
        """Streaming completion: yields token chunks as strings."""
        self._check_breaker()
        attempt = 0
        while True:
            try:
                stream = self._client.chat.completions.create(  # type: ignore[no-untyped-call]
                    model=model,
                    messages=messages,
                    stream=True,
                    timeout=self._timeout,
                )
                self._record_success()
                for chunk in stream:
                    # SDK shape: chunk.choices[0].delta.content
                    try:
                        choices = getattr(chunk, "choices", [])
                        if not choices:
                            continue
                        delta = getattr(choices[0], "delta", None)
                        if not delta:
                            continue
                        token = getattr(delta, "content", None)
                        if token:
                            yield token
                    except Exception:  # noqa: BLE001
                        # Defensive: ignore malformed partials
                        continue
                return
            except Exception as exc:  # noqa: BLE001
                if self._logger:
                    self._logger.warning(
                        "openai chat stream error",
                        extra={
                            "event": "openai.chat.stream.error",
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
                self._record_failure()
                if attempt >= self._max_retries:
                    raise
                backoff = min(1.0 * (2**attempt), 5.0) + random.uniform(0, 0.25)
                time.sleep(backoff)
                attempt += 1

    # ---- Introspection (optional) -----------------------------------------------

    @property
    def breaker_open(self) -> bool:
        """True if the breaker is currently open (cooling down)."""
        return time.monotonic() < self._breaker_open_until
