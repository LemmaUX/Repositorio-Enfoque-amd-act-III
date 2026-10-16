"""Canonical typed schemas for the reconciliation core.

Design rules (see docs/DATA_CONTRACTS.md):

* All monetary values use :class:`decimal.Decimal` — never ``float`` — so
  arithmetic is exact and reproducible.
* Missing / invalid data fails schema validation loudly; it can never be
  coerced into an "approved" state.
* Enums are string-valued so they serialize to stable, machine-readable
  JSON without depending on Python enum internals.
"""

from __future__ import annotations

import re
from datetime import date as _date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ID_RE = re.compile(r"^\S+$")  # non-empty, no whitespace


class Money(BaseModel):
    """An exact decimal amount paired with an ISO-4217 currency code."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal = Field(
        description="Exact decimal value. Floats are rejected at validation time."
    )
    currency: str = Field(description="ISO-4217 alpha-3 code, e.g. 'USD'.")

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError(
                "float monetary values are forbidden; pass a Decimal or str"
            )
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, Decimal):
            return v
        if isinstance(v, str):
            try:
                return Decimal(v)
            except Exception as exc:  # decimal.InvalidOperation etc.
                raise ValueError(f"invalid decimal string: {v!r}") from exc
        raise TypeError(f"unsupported type for Money.amount: {type(v)!r}")

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        if not _CURRENCY_RE.match(v):
            raise ValueError(f"currency must be ISO-4217 alpha-3 uppercase, got {v!r}")
        return v


def _validate_identifier(v: str) -> str:
    if not v or not _ID_RE.match(v):
        raise ValueError(f"identifier must be non-empty without whitespace, got {v!r}")
    return v


class LineItem(BaseModel):
    """One line on an invoice or purchase order (quantity x unit price)."""

    model_config = ConfigDict(frozen=True)

    line_number: int = Field(ge=1)
    sku: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0, description="Must be strictly positive.")
    unit_price: Money
    line_total: Optional[Money] = Field(
        default=None,
        description="Authoritative extended total for this line; if omitted the "
        "engine derives quantity * unit_price.",
    )

    @field_validator("sku")
    @classmethod
    def _sku_id(cls, v: str) -> str:
        return _validate_identifier(v)

    @model_validator(mode="after")
    def _check_currency(self) -> "LineItem":
        if self.line_total is not None and self.line_total.currency != self.unit_price.currency:
            raise ValueError("line_total.currency must equal unit_price.currency")
        return self

    def derived_total(self) -> Money:
        """Quantity * unit price, exact in Decimal."""
        return Money(amount=self.quantity * self.unit_price.amount,
                     currency=self.unit_price.currency)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class Invoice(BaseModel):
    """Canonical invoice document."""

    model_config = ConfigDict(frozen=True)

    invoice_id: str
    supplier_id: str
    po_reference: str = Field(
        description="Purchase order this invoice bills against."
    )
    issue_date: _date
    currency: str
    gross_amount: Money
    tax_amount: Optional[Money] = Field(
        default=None,
        description="If absent, tax cannot be verified; the engine flags "
        "MISSING_TAX_AMOUNT rather than assuming zero.",
    )
    net_amount: Optional[Money] = Field(
        default=None,
        description="Optional pre-tax subtotal. If absent the engine derives "
        "gross - tax when both are present.",
    )
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("invoice_id", "supplier_id", "po_reference")
    @classmethod
    def _ids(cls, v: str) -> str:
        return _validate_identifier(v)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        if not _CURRENCY_RE.match(v):
            raise ValueError(f"currency must be ISO-4217 alpha-3 uppercase, got {v!r}")
        return v

    @model_validator(mode="after")
    def _consistent_currencies(self) -> "Invoice":
        if self.gross_amount.currency != self.currency:
            raise ValueError("gross_amount.currency must match invoice currency")
        for m, name in ((self.tax_amount, "tax_amount"), (self.net_amount, "net_amount")):
            if m is not None and m.currency != self.currency:
                raise ValueError(f"{name}.currency must match invoice currency")
        for li in self.line_items:
            if li.unit_price.currency != self.currency:
                raise ValueError(
                    f"line item {li.line_number} currency must match invoice currency"
                )
        return self


class PurchaseOrder(BaseModel):
    """Canonical purchase order document."""

    model_config = ConfigDict(frozen=True)

    po_id: str
    buyer_id: str
    supplier_id: str
    issue_date: _date
    currency: str
    total_amount: Money
    tax_rate: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Fractional expected tax rate, e.g. 0.0825. Absent means "
        "tax-rate checks are skipped with REASON: TAX_RATE_UNKNOWN.",
    )
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("po_id", "buyer_id", "supplier_id")
    @classmethod
    def _ids(cls, v: str) -> str:
        return _validate_identifier(v)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        if not _CURRENCY_RE.match(v):
            raise ValueError(f"currency must be ISO-4217 alpha-3 uppercase, got {v!r}")
        return v

    @model_validator(mode="after")
    def _consistent_currencies(self) -> "PurchaseOrder":
        if self.total_amount.currency != self.currency:
            raise ValueError("total_amount.currency must match PO currency")
        for li in self.line_items:
            if li.unit_price.currency != self.currency:
                raise ValueError(
                    f"line item {li.line_number} currency must match PO currency"
                )
        return self


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------

class DiscrepancyField(str, Enum):
    """Fields that the deterministic engine compares."""

    GROSS_AMOUNT = "gross_amount"
    TAX_AMOUNT = "tax_amount"
    NET_AMOUNT = "net_amount"
    CURRENCY = "currency"
    LINE_TOTAL = "line_total"
    LINE_QUANTITY = "line_quantity"
    MISSING_FIELD = "missing_field"
    DUPLICATE_ID = "duplicate_id"
    DOCUMENT = "document"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"  # guarantees NO auto-approval


class Discrepancy(BaseModel):
    """A single machine-readable finding between an invoice and a PO."""

    model_config = ConfigDict(frozen=True)

    reason_code: str = Field(
        description="Stable machine-readable code from recon.policy.ReasonCode."
    )
    field: DiscrepancyField
    severity: Severity
    expected: Optional[str] = Field(
        default=None, description="Canonical string of the expected value."
    )
    actual: Optional[str] = Field(
        default=None, description="Canonical string of the observed value."
    )
    delta: Optional[Decimal] = Field(
        default=None, description="Signed difference (actual - expected) where numeric."
    )
    detail: str = Field(default="", description="Human-readable explanation.")

    @field_validator("reason_code")
    @classmethod
    def _code_shape(cls, v: str) -> str:
        if not re.match(r"^[A-Z][A-Z0-9_]*$", v):
            raise ValueError(f"reason_code must be UPPER_SNAKE, got {v!r}")
        return v


class MatchDecision(str, Enum):
    """Outcome of reconciling one invoice/PO pair.

    ``MANUAL_REVIEW`` is the guaranteed safe fallback: any missing, invalid,
    or ambiguous input must map here, never to ``AUTO_MATCH``.
    """

    AUTO_MATCH = "auto_match"                # within all configured tolerances
    MATCH_WITH_DISCREPANCY = "match_with_discrepancy"  # matched but noteworthy
    REJECT = "reject"                        # deterministic hard failure (e.g. currency mismatch)
    MANUAL_REVIEW = "manual_review"          # cannot safely decide


class ReconciliationResult(BaseModel):
    """Full result for one invoice-vs-PO comparison."""

    model_config = ConfigDict(frozen=True)

    invoice_id: str
    po_id: str
    decision: MatchDecision
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    policy_version: str = Field(
        description="Which policy configuration produced this result."
    )

    @property
    def auto_approvable(self) -> bool:
        """True only for a clean AUTO_MATCH — the single approval signal."""
        return self.decision is MatchDecision.AUTO_MATCH and not any(
            d.severity in (Severity.ERROR, Severity.BLOCKING)
            for d in self.discrepancies
        )


class AuditRecord(BaseModel):
    """Append-only audit entry for one reconciliation event.

    Timestamps are supplied by the caller (the engine itself stays pure and
    deterministic); persistence/PII policy is an open business question
    (docs/OPEN_DECISIONS.md).
    """

    model_config = ConfigDict(frozen=True)

    record_id: str
    timestamp_utc: _date | str = Field(
        description="Caller-provided UTC timestamp (ISO string or date)."
    )
    actor: str = Field(description="Who/what produced the result, e.g. 'recon-engine'.")
    invoice_id: str
    po_id: str
    decision: MatchDecision
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str
    result_digest: str = Field(
        description="Deterministic SHA-256 hex digest of the canonical result JSON."
    )

    @field_validator("record_id", "actor")
    @classmethod
    def _ids(cls, v: str) -> str:
        return _validate_identifier(v)
