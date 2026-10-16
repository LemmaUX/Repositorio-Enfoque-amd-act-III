"""LLM interface + deterministic mock. No model is required to run tests.

Deliberate boundaries (see docs/RECONNAISSANCE.md §4–§6):

* This module defines only an abstract contract. There is **no** vLLM,
  Evolus, or AMD GPU implementation here — those APIs are unverified and
  must not be invented. A real adapter will be added in a later mission
  once a served endpoint is VERIFIED, and it will implement this Protocol.
* The reconciliation engine never calls an LLM. Any future LLM output is
  advisory input to human review, never an auto-approval signal.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from recon.models import ReconciliationResult


class LLMRequest(BaseModel):
    """Provider-neutral request envelope."""

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1)
    system: str = Field(default="")
    max_tokens: int = Field(default=512, gt=0, le=8192)
    temperature: float = Field(
        default=0.0,
        description="Advisory only; mocks are deterministic regardless.",
    )


class LLMResponse(BaseModel):
    """Provider-neutral response envelope."""

    model_config = ConfigDict(frozen=True)

    text: str
    model_id: str = Field(description="Identifier reported by the provider.")
    finish_reason: str = Field(default="stop")


@runtime_checkable
class LLMClient(Protocol):
    """Minimal contract every future provider adapter must satisfy."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Blocking single-shot completion. Must raise on any provider error;
        implementations may NEVER return fabricated success."""
        ...


class MockLLMClient:
    """Deterministic scripted mock for unit tests.

    Responses are pre-programmed per prompt substring (first match wins),
    with a canned default. Nothing networked, nothing learned.
    """

    def __init__(
        self,
        script: Sequence[tuple[str, str]] = (),
        *,
        default_text: str = "",
        model_id: str = "mock-llm-v0",
    ) -> None:
        self._script = list(script)
        self._default = default_text
        self._model_id = model_id
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        for needle, reply in self._script:
            if needle in request.prompt:
                return LLMResponse(text=reply, model_id=self._model_id)
        return LLMResponse(text=self._default, model_id=self._model_id)


def summarize_for_review(result: ReconciliationResult, client: LLMClient) -> str:
    """Example of the ONLY sanctioned LLM use: producing a human-readable
    summary of an already-computed deterministic result. The decision itself
    is taken from ``result`` before any model call."""
    if result.auto_approvable:
        # No LLM needed (and never used as an approval gate).
        return "Clean auto-match; no review required."
    req = LLMRequest(
        prompt=(
            "Summarize these reconciliation findings for a human reviewer. "
            f"Decision: {result.decision.value}. "
            f"Reason codes: {[d.reason_code for d in result.discrepancies]}"
        )
    )
    return client.complete(req).text
