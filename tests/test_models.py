"""Tests for canonical schemas (recon.models)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from recon.models import Invoice, LineItem, Money, PurchaseOrder

D = Decimal


def _minimal_invoice(**over):
    base = dict(
        invoice_id="INV-1",
        supplier_id="SUP-1",
        po_reference="PO-1",
        issue_date=date(2026, 10, 1),
        currency="USD",
        gross_amount=Money(amount=D("100.00"), currency="USD"),
    )
    base.update(over)
    return Invoice(**base)


class TestMoney:
    def test_accepts_decimal_and_string(self):
        assert Money(amount=D("10.25"), currency="USD").amount == D("10.25")
        assert Money(amount="10.25", currency="usd".upper()).amount == D("10.25")

    def test_rejects_float(self):
        with pytest.raises(ValidationError, match="float"):
            Money(amount=10.25, currency="USD")  # type: ignore[arg-type]

    def test_rejects_bad_currency(self):
        with pytest.raises(ValidationError):
            Money(amount=D("1"), currency="usd")
        with pytest.raises(ValidationError):
            Money(amount=D("1"), currency="DOLLARS")

    def test_frozen(self):
        m = Money(amount=D("1"), currency="USD")
        with pytest.raises(ValidationError):
            m.amount = D("2")  # type: ignore[misc]


class TestLineItem:
    def test_derived_total_exact(self):
        li = LineItem(
            line_number=1,
            sku="A",
            quantity=D("3"),
            unit_price=Money(amount=D("0.10"), currency="USD"),
        )
        # Classic float trap: 3 * 0.1 in float != 0.3; Decimal is exact.
        assert li.derived_total().amount == D("0.30")

    def test_rejects_nonpositive_quantity(self):
        with pytest.raises(ValidationError):
            LineItem(
                line_number=1,
                sku="A",
                quantity=D("0"),
                unit_price=Money(amount=D("1"), currency="USD"),
            )

    def test_rejects_mismatched_line_currencies(self):
        with pytest.raises(ValidationError):
            LineItem(
                line_number=1,
                sku="A",
                quantity=D("1"),
                unit_price=Money(amount=D("1"), currency="USD"),
                line_total=Money(amount=D("1"), currency="EUR"),
            )


class TestInvoice:
    def test_valid_minimal(self):
        inv = _minimal_invoice()
        assert inv.tax_amount is None and inv.net_amount is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("invoice_id", ""),
            ("invoice_id", "has space"),
            ("supplier_id", ""),
            ("po_reference", ""),
        ],
    )
    def test_blank_ids_rejected(self, field, value):
        with pytest.raises(ValidationError):
            _minimal_invoice(**{field: value})

    def test_gross_currency_must_match_header(self):
        with pytest.raises(ValidationError):
            _minimal_invoice(gross_amount=Money(amount=D("10"), currency="EUR"))

    def test_invalid_decimal_string_rejected(self):
        with pytest.raises(ValidationError):
            Money(amount="not-a-number", currency="USD")


class TestPurchaseOrder:
    def _po(self, **over):
        base = dict(
            po_id="PO-1",
            buyer_id="BUY-1",
            supplier_id="SUP-1",
            issue_date=date(2026, 9, 1),
            currency="USD",
            total_amount=Money(amount=D("100.00"), currency="USD"),
        )
        base.update(over)
        return PurchaseOrder(**base)

    def test_tax_rate_bounds(self):
        self._po(tax_rate=D("0.0825"))
        with pytest.raises(ValidationError):
            self._po(tax_rate=D("1.5"))
        with pytest.raises(ValidationError):
            self._po(tax_rate=D("-0.01"))

    def test_optional_tax_rate(self):
        assert self._po(tax_rate=None).tax_rate is None
