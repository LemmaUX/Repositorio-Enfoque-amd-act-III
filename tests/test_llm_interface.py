"""Tests for the LLM interface + mock. No real model is required."""

from __future__ import annotations

import pytest

from recon.engine import reconcile_pair
from recon.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    MockLLMClient,
    summarize_for_review,
)
from recon.models import MatchDecision

from conftest import make_invoice, make_po


class TestMockClient:
    def test_conforms_to_protocol(self):
        assert isinstance(MockLLMClient(), LLMClient)

    def test_scripted_response_first_match_wins(self):
        client = MockLLMClient(
            script=[("tax", "Tax exceeds PO rate."), ("gross", "Gross differs.")],
            default_text="No findings.",
        )
        assert client.complete(LLMRequest(prompt="why is tax wrong")).text == \
            "Tax exceeds PO rate."
        assert client.complete(LLMRequest(prompt="gross amount issue")).text == \
            "Gross differs."
        assert client.complete(LLMRequest(prompt="anything else")).text == "No findings."

    def test_calls_are_recorded(self):
        client = MockLLMClient()
        req = LLMRequest(prompt="hello")
        resp = client.complete(req)
        assert isinstance(resp, LLMResponse)
        assert resp.model_id == "mock-llm-v0"
        assert client.calls == [req]

    def test_deterministic_repeat(self):
        client = MockLLMClient(script=[("x", "y")])
        r1 = client.complete(LLMRequest(prompt="x"))
        r2 = client.complete(LLMRequest(prompt="x"))
        assert r1 == r2


class TestRequestValidation:
    def test_empty_prompt_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMRequest(prompt="")

    def test_max_tokens_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMRequest(prompt="p", max_tokens=0)
        with pytest.raises(ValidationError):
            LLMRequest(prompt="p", max_tokens=10_000)


class TestSummarizeForReview:
    def test_clean_auto_match_never_calls_llm(self, policy):
        result = reconcile_pair(make_invoice(), make_po(), policy)
        assert result.decision is MatchDecision.AUTO_MATCH
        client = MockLLMClient(script=[(".", "should not be used")])
        text = summarize_for_review(result, client)
        assert text == "Clean auto-match; no review required."
        assert client.calls == []  # LLM must not influence approvals at all

    def test_discrepant_result_summarized_via_mock(self, policy):
        result = reconcile_pair(make_invoice(gross="1200.00"), make_po(), policy)
        client = MockLLMClient(default_text="Manual review: gross mismatch.")
        text = summarize_for_review(result, client)
        assert text == "Manual review: gross mismatch."
        assert len(client.calls) == 1
