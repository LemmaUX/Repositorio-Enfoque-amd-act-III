"""Reconciliation policy: tolerances, reason codes, decision rules.

Every tolerance is **explicit and configurable** — the engine never assumes a
financial threshold. The defaults below are placeholders for local testing
only; production values are an open business decision
(docs/OPEN_DECISIONS.md).

Comparison convention (deterministic, Decimal-only):

* ``absolute`` tolerance: |delta| <= absolute passes.
* ``relative`` tolerance: |delta| <= relative * |expected| passes.
* A comparison passes if it satisfies **either** configured bound (both must
  be exceeded to fail) — this "OR" semantics is itself a policy choice that
  needs business confirmation (docs/OPEN_DECISIONS.md D3).
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReasonCode(str, Enum):
    """Stable, machine-readable finding codes. **Never rename or reuse.**

    New findings get new codes; retired codes stay listed as DEPRECATED.
    """

    # Successes / informational
    MATCH_OK = "MATCH_OK"                       # within all tolerances
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"       # differs but inside bounds

    # Hard deterministic failures (severity ERROR -> REJECT)
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"     # invoice vs PO currency differ
    SUPPLIER_MISMATCH = "SUPPLIER_MISMATCH"     # invoice supplier != PO supplier
    DUPLICATE_INVOICE_ID = "DUPLICATE_INVOICE_ID"
    DUPLICATE_PO_ID = "DUPLICATE_PO_ID"

    # Amount discrepancies
    GROSS_AMOUNT_MISMATCH = "GROSS_AMOUNT_MISMATCH"
    TAX_AMOUNT_MISMATCH = "TAX_AMOUNT_MISMATCH"
    NET_AMOUNT_MISMATCH = "NET_AMOUNT_MISMATCH"
    LINE_TOTAL_MISMATCH = "LINE_TOTAL_MISMATCH"
    LINE_QUANTITY_MISMATCH = "LINE_QUANTITY_MISMATCH"
    MISSING_LINE_ITEM = "MISSING_LINE_ITEM"
    UNEXPECTED_LINE_ITEM = "UNEXPECTED_LINE_ITEM"

    # Missing / ambiguous data (severity BLOCKING -> MANUAL_REVIEW)
    MISSING_TAX_AMOUNT = "MISSING_TAX_AMOUNT"
    MISSING_NET_AMOUNT = "MISSING_NET_AMOUNT"
    TAX_RATE_UNKNOWN = "TAX_RATE_UNKNOWN"
    INCOMPLETE_DOCUMENT = "INCOMPLETE_DOCUMENT"
    INVALID_INPUT = "INVALID_INPUT"

    @property
    def is_blocking(self) -> bool:
        """Codes that must prevent any auto-approval recommendation."""
        return self in _BLOCKING_CODES


_BLOCKING_CODES = frozenset(
    {
        ReasonCode.MISSING_TAX_AMOUNT,
        ReasonCode.MISSING_NET_AMOUNT,
        ReasonCode.TAX_RATE_UNKNOWN,
        ReasonCode.INCOMPLETE_DOCUMENT,
        ReasonCode.INVALID_INPUT,
    }
)


class Tolerance(BaseModel):
    """Explicit amount-comparison tolerance. At least one bound required."""

    model_config = ConfigDict(frozen=True)

    absolute: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Max allowed absolute difference in document currency units.",
    )
    relative: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"), le=Decimal("1"),
        description="Max allowed difference as a fraction of |expected|.",
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> "Tolerance":
        if self.absolute is None and self.relative is None:
            raise ValueError("Tolerance requires at least one of absolute/relative")
        return self

    def permits(self, delta: Decimal, expected: Decimal) -> bool:
        """Deterministic check: passes if within either configured bound."""
        adelta = abs(delta)
        if self.absolute is not None and adelta <= self.absolute:
            return True
        if self.relative is not None and adelta <= self.relative * abs(expected):
            return True
        return False


class ReconciliationPolicy(BaseModel):
    """Versioned bundle of every threshold the engine uses."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    gross_tolerance: Tolerance
    tax_tolerance: Tolerance
    net_tolerance: Tolerance
    line_tolerance: Tolerance = Field(
        description="Tolerance applied to per-line extended totals."
    )
    compare_line_items: bool = Field(default=True)
    require_tax_amount: bool = Field(
        default=True,
        description="If True, invoices without tax_amount are BLOCKED to manual "
        "review instead of silently treated as tax-free.",
    )

    @classmethod
    def test_defaults(cls) -> "ReconciliationPolicy":
        """Placeholder policy for unit tests ONLY — not a business-approved set.

        Absolute $0.01 cent rounding tolerance on every amount comparison.
        See docs/OPEN_DECISIONS.md (D1/D2) before using anywhere real.
        """
        cent = Tolerance(absolute=Decimal("0.01"))
        return cls(
            version="test-defaults-0",
            gross_tolerance=cent,
            tax_tolerance=cent,
            net_tolerance=cent,
            line_tolerance=cent,
        )
