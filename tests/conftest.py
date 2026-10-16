"""Shared pytest fixtures: factories for valid documents + a test policy."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from recon.models import Invoice, LineItem, Money, PurchaseOrder
from recon.policy import ReconciliationPolicy, Tolerance

D = Decimal


def money(s: str, cur: str = "USD") -> Money:
    return Money(amount=D(s), currency=cur)


def make_invoice(
    *,
    invoice_id: str = "INV-001",
    supplier_id: str = "SUP-42",
    po_reference: str = "PO-100",
    gross: str = "1082.50",
    tax: Optional[str] = "82.50",
    net: Optional[str] = "1000.00",
    currency: str = "USD",
    lines: Optional[list[LineItem]] = None,
) -> Invoice:
    if lines is None:
        lines = [
            LineItem(
                line_number=1,
                sku="SKU-A",
                quantity=D("10"),
                unit_price=money("100.00", currency),
            )
        ]
    return Invoice(
        invoice_id=invoice_id,
        supplier_id=supplier_id,
        po_reference=po_reference,
        issue_date=date(2026, 10, 1),
        currency=currency,
        gross_amount=money(gross, currency),
        tax_amount=money(tax, currency) if tax is not None else None,
        net_amount=money(net, currency) if net is not None else None,
        line_items=lines,
    )


def make_po(
    *,
    po_id: str = "PO-100",
    buyer_id: str = "BUY-7",
    supplier_id: str = "SUP-42",
    total: str = "1082.50",
    tax_rate: Optional[str] = "0.0825",
    currency: str = "USD",
    lines: Optional[list[LineItem]] = None,
) -> PurchaseOrder:
    if lines is None:
        lines = [
            LineItem(
                line_number=1,
                sku="SKU-A",
                quantity=D("10"),
                unit_price=money("100.00", currency),
            )
        ]
    return PurchaseOrder(
        po_id=po_id,
        buyer_id=buyer_id,
        supplier_id=supplier_id,
        issue_date=date(2026, 9, 15),
        currency=currency,
        total_amount=money(total, currency),
        tax_rate=D(tax_rate) if tax_rate is not None else None,
        line_items=lines,
    )


@pytest.fixture()
def policy() -> ReconciliationPolicy:
    """Placeholder cent-tolerance policy for tests ONLY (not business-approved)."""
    return ReconciliationPolicy.test_defaults()


@pytest.fixture()
def zero_tolerance_policy() -> ReconciliationPolicy:
    return ReconciliationPolicy(
        version="zero-tol-test",
        gross_tolerance=Tolerance(absolute=D("0")),
        tax_tolerance=Tolerance(absolute=D("0")),
        net_tolerance=Tolerance(absolute=D("0")),
        line_tolerance=Tolerance(absolute=D("0")),
    )
