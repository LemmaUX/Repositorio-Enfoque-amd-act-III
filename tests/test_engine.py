"""Tests for the deterministic reconciliation engine (recon.engine).

Covers: matching invoices, amount mismatches, tax errors, missing fields,
currency mismatches, duplicate identifiers, rounding boundaries, incomplete
data, determinism, and audit records.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from recon.engine import make_audit_record, reconcile_batch, reconcile_pair, result_digest
from recon.models import LineItem, Money
from recon.models import MatchDecision
from recon.policy import ReasonCode, ReconciliationPolicy, Tolerance

from conftest import make_invoice, make_po, money

D = Decimal


def codes(result):
    return {d.reason_code for d in result.discrepancies}


class TestMatching:
    def test_exact_match_auto(self, policy):
        r = reconcile_pair(make_invoice(), make_po(), policy)
        assert r.decision is MatchDecision.AUTO_MATCH
        assert r.auto_approvable
        assert codes(r) == {ReasonCode.MATCH_OK.value}

    def test_within_tolerance_is_auto_but_visible(self, policy):
        # tax 82.50 is exactly 8.25% of net 1000.00; gross carries a half-cent
        # rounding difference (1082.505) inside the 0.01 absolute tolerance.
        inv = make_invoice(gross="1082.505")
        r = reconcile_pair(inv, make_po(), policy)
        assert r.decision is MatchDecision.AUTO_MATCH
        assert r.auto_approvable
        assert ReasonCode.WITHIN_TOLERANCE.value in codes(r)
        assert ReasonCode.MATCH_OK.value in codes(r)

    def test_deterministic_same_inputs_same_output(self, policy):
        inv, po = make_invoice(), make_po()
        r1, r2 = reconcile_pair(inv, po, policy), reconcile_pair(inv, po, policy)
        assert r1.model_dump_json() == r2.model_dump_json()
        assert result_digest(r1) == result_digest(r2)


class TestAmountMismatch:
    def test_gross_over_po_total_rejected(self, policy):
        inv = make_invoice(gross="1200.00", tax="82.50", net="1117.50")
        r = reconcile_pair(inv, make_po(), policy)
        assert r.decision is MatchDecision.REJECT
        assert not r.auto_approvable
        assert ReasonCode.GROSS_AMOUNT_MISMATCH.value in codes(r)
        d = next(x for x in r.discrepancies if x.reason_code == "GROSS_AMOUNT_MISMATCH")
        assert d.delta == D("117.50")

    def test_zero_tolerance_flags_one_cent(self, zero_tolerance_policy):
        inv = make_invoice(gross="1082.51")
        r = reconcile_pair(inv, make_po(), zero_tolerance_policy)
        assert r.decision is MatchDecision.REJECT
        assert ReasonCode.GROSS_AMOUNT_MISMATCH.value in codes(r)


class TestTaxErrors:
    def test_tax_too_high(self, policy):
        # gross 1082.50 -> net 1000.00 -> expected tax 82.50; invoice says 100.
        inv = make_invoice(gross="1100.00", tax="100.00", net="1000.00")
        r = reconcile_pair(inv, make_po(total="1100.00"), policy)
        assert ReasonCode.TAX_AMOUNT_MISMATCH.value in codes(r)
        assert r.decision is MatchDecision.REJECT

    def test_missing_tax_amount_blocks(self, policy):
        inv = make_invoice(tax=None, net=None)
        r = reconcile_pair(inv, make_po(), policy)
        assert r.decision is MatchDecision.MANUAL_REVIEW
        assert not r.auto_approvable
        assert ReasonCode.MISSING_TAX_AMOUNT.value in codes(r)

    def test_unknown_tax_rate_blocks(self, policy):
        inv = make_invoice()
        r = reconcile_pair(inv, make_po(tax_rate=None), policy)
        assert r.decision is MatchDecision.MANUAL_REVIEW
        assert ReasonCode.TAX_RATE_UNKNOWN.value in codes(r)

    def test_net_consistency_check(self, policy):
        inv = make_invoice(net="999.00")  # gross-tax = 1000.00, stated 999.00
        r = reconcile_pair(inv, make_po(), policy)
        assert ReasonCode.NET_AMOUNT_MISMATCH.value in codes(r)
        assert r.decision is MatchDecision.REJECT


class TestCurrencyMismatch:
    def test_currency_mismatch_rejects_and_never_auto(self, policy):
        inv = make_invoice(currency="EUR", lines=None)
        inv = inv.model_copy(
            update={
                "gross_amount": money("1082.50", "EUR"),
                "tax_amount": money("82.50", "EUR"),
                "net_amount": money("1000.00", "EUR"),
                "line_items": [
                    LineItem(line_number=1, sku="SKU-A", quantity=D("10"),
                             unit_price=money("100.00", "EUR"))
                ],
            }
        )
        r = reconcile_pair(inv, make_po(), policy)
        assert r.decision is MatchDecision.REJECT
        assert not r.auto_approvable
        assert ReasonCode.CURRENCY_MISMATCH.value in codes(r)


class TestLineItems:
    def test_quantity_mismatch_with_matching_totals_is_warning(self, policy):
        # Ordered 10 @ 100.00; invoiced 9 @ 110.00 -> same extended total,
        # quantity differs. Header and line totals reconcile, so the only
        # finding is a WARNING -> MATCH_WITH_DISCREPANCY (never auto-approved).
        inv = make_invoice(
            lines=[LineItem(line_number=1, sku="SKU-A", quantity=D("9"),
                            unit_price=money("111.3888888889"))],
        )
        po = make_po(lines=[LineItem(line_number=1, sku="SKU-A", quantity=D("10"),
                                     unit_price=money("100.00"),
                                     line_total=money("1000.00"))])
        inv = inv.model_copy(update={
            "line_items": [LineItem(line_number=1, sku="SKU-A", quantity=D("9"),
                                    unit_price=money("111.3888888889"),
                                    line_total=money("1000.00"))]
        })
        r = reconcile_pair(inv, po, policy)
        assert ReasonCode.LINE_QUANTITY_MISMATCH.value in codes(r)
        # warnings alone (no ERROR/BLOCKING) -> match_with_discrepancy
        assert r.decision is MatchDecision.MATCH_WITH_DISCREPANCY
        assert not r.auto_approvable

    def test_underbilled_line_rejects_on_total_mismatch(self, policy):
        # Invoiced 9 @ 100.00 vs ordered 10 @ 100.00: both the header gross and
        # the line total exceed tolerance -> deterministic REJECT.
        inv = make_invoice(
            lines=[LineItem(line_number=1, sku="SKU-A", quantity=D("9"),
                            unit_price=money("100.00"))],
            gross="982.50", tax="82.50", net="900.00",
        )
        r = reconcile_pair(inv, make_po(total="982.50"), policy)
        assert ReasonCode.LINE_QUANTITY_MISMATCH.value in codes(r)
        assert ReasonCode.LINE_TOTAL_MISMATCH.value in codes(r)
        assert r.decision is MatchDecision.REJECT
        assert not r.auto_approvable

    def test_sku_mismatch_blocks(self, policy):
        inv = make_invoice(
            lines=[LineItem(line_number=1, sku="SKU-B", quantity=D("10"),
                            unit_price=money("100.00"))]
        )
        r = reconcile_pair(inv, make_po(), policy)
        assert r.decision is MatchDecision.MANUAL_REVIEW
        assert ReasonCode.INVALID_INPUT.value in codes(r)

    def test_unexpected_line_flagged(self, policy):
        inv = make_invoice(
            lines=[
                LineItem(line_number=1, sku="SKU-A", quantity=D("10"),
                         unit_price=money("100.00")),
                LineItem(line_number=2, sku="SKU-Z", quantity=D("1"),
                         unit_price=money("50.00")),
            ]
        )
        r = reconcile_pair(inv, make_po(), policy)
        assert ReasonCode.UNEXPECTED_LINE_ITEM.value in codes(r)


class TestRoundingBoundaries:
    @pytest.mark.parametrize(
        "delta,expect_within",
        [
            ("0.009", True),   # strictly inside 0.01
            ("0.010", True),   # exactly at boundary: inclusive <=
            ("0.011", False),  # outside
        ],
    )
    def test_absolute_boundary_inclusive(self, policy, delta, expect_within):
        gross = (D("1082.50") + D(delta)).normalize()
        inv = make_invoice(gross=str(gross), tax=None, net=None)
        r = reconcile_pair(inv, make_po(tax_rate=None), policy)
        within = ReasonCode.WITHIN_TOLERANCE.value in codes(r)
        mismatch = ReasonCode.GROSS_AMOUNT_MISMATCH.value in codes(r)
        assert within == expect_within
        assert mismatch == (not expect_within)

    def test_relative_tolerance(self):
        pol = ReconciliationPolicy(
            version="rel-test",
            gross_tolerance=Tolerance(relative=D("0.001")),
            tax_tolerance=Tolerance(absolute=D("0")),
            net_tolerance=Tolerance(absolute=D("0")),
            line_tolerance=Tolerance(absolute=D("0")),
        )
        # 1082.50 * 0.001 = 1.0825; delta 1.00 is inside, 2.00 outside.
        ok = make_invoice(gross="1083.50", tax=None, net=None)
        bad = make_invoice(gross="1084.50", tax=None, net=None)
        po = make_po(tax_rate=None)
        assert ReasonCode.WITHIN_TOLERANCE.value in codes(reconcile_pair(ok, po, pol))
        assert ReasonCode.GROSS_AMOUNT_MISMATCH.value in codes(reconcile_pair(bad, po, pol))

    def test_no_float_contamination(self, policy):
        # 0.1 + 0.2 style trap handled exactly by Decimal.
        inv = make_invoice(gross="0.30", tax="0.00", net="0.30")
        po = make_po(total="0.30", tax_rate="0")
        po_lines = po.model_copy(update={"line_items": [
            LineItem(line_number=1, sku="S", quantity=D("3"),
                     unit_price=money("0.10"))]})
        inv2 = inv.model_copy(update={"line_items": po_lines.line_items})
        r = reconcile_pair(inv2, po_lines, policy)
        assert r.decision is MatchDecision.AUTO_MATCH


class TestDuplicatesAndIncomplete:
    def test_duplicate_invoice_id_manual_review(self, policy):
        inv = make_invoice()
        results = reconcile_batch([inv, inv], [make_po()], policy)
        assert len(results) == 2
        for r in results:
            assert r.decision is MatchDecision.MANUAL_REVIEW
            assert not r.auto_approvable
            assert ReasonCode.DUPLICATE_INVOICE_ID.value in codes(r)

    def test_duplicate_po_id_manual_review(self, policy):
        po = make_po()
        results = reconcile_batch([make_invoice()], [po, po], policy)
        assert results[0].decision is MatchDecision.MANUAL_REVIEW
        assert ReasonCode.DUPLICATE_PO_ID.value in codes(results[0])

    def test_missing_po_reference_manual_review(self, policy):
        inv = make_invoice(po_reference="PO-MISSING")
        results = reconcile_batch([inv], [make_po()], policy)
        assert results[0].decision is MatchDecision.MANUAL_REVIEW
        assert ReasonCode.INCOMPLETE_DOCUMENT.value in codes(results[0])
        assert not results[0].auto_approvable

    def test_batch_clean_pair_auto(self, policy):
        results = reconcile_batch([make_invoice()], [make_po()], policy)
        assert results[0].decision is MatchDecision.AUTO_MATCH


class TestAudit:
    def test_audit_record_shape_and_digest(self, policy):
        r = reconcile_pair(make_invoice(), make_po(), policy)
        a = make_audit_record(r, record_id="AUD-1", timestamp_utc="2026-10-16T00:00:00Z")
        assert a.invoice_id == r.invoice_id and a.po_id == r.po_id
        assert a.decision is r.decision
        assert a.policy_version == r.policy_version
        assert a.result_digest == result_digest(r)
        # digest stable across rebuilds of the same result
        r2 = reconcile_pair(make_invoice(), make_po(), policy)
        assert result_digest(r2) == a.result_digest

    def test_digest_changes_with_decision(self, policy):
        good = reconcile_pair(make_invoice(), make_po(), policy)
        bad = reconcile_pair(make_invoice(gross="9999.00"), make_po(), policy)
        assert result_digest(good) != result_digest(bad)
