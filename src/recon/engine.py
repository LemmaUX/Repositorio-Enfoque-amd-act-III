"""Deterministic invoice-to-PO reconciliation engine.

Properties guaranteed by design (and asserted in tests):

* **Pure & deterministic** — no clock, randomness, or I/O; identical inputs
  always produce byte-identical canonical results.
* **Decimal-only money math** — floats never enter a comparison.
* **Fail-safe decisions** — missing/invalid/ambiguous data yields
  ``MANUAL_REVIEW`` with a BLOCKING reason code, never ``AUTO_MATCH``.
* **Explicit tolerances** — every threshold comes from the injected
  :class:`ReconciliationPolicy`; nothing is hardcoded.

Decision precedence (highest wins):
``REJECT`` (hard mismatch) > ``MANUAL_REVIEW`` (blocking/incomplete) >
``MATCH_WITH_DISCREPANCY`` (warning/info findings) > ``AUTO_MATCH``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from pydantic import ValidationError

from recon.models import (
    AuditRecord,
    Discrepancy,
    DiscrepancyField,
    Invoice,
    MatchDecision,
    PurchaseOrder,
    ReconciliationResult,
    Severity,
)
from recon.policy import ReasonCode, ReconciliationPolicy, Tolerance


def _canon_json(result: ReconciliationResult) -> str:
    """Canonical JSON for digesting: sorted keys, Decimal as exact string."""
    return json.dumps(
        result.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def result_digest(result: ReconciliationResult) -> str:
    """Deterministic SHA-256 hex digest over the canonical result JSON."""
    return hashlib.sha256(_canon_json(result).encode("utf-8")).hexdigest()


def make_audit_record(
    result: ReconciliationResult,
    *,
    record_id: str,
    timestamp_utc: str,
    actor: str = "recon-engine",
) -> AuditRecord:
    """Build an audit record from a result. Caller supplies the timestamp so
    the engine itself stays pure/deterministic."""
    return AuditRecord(
        record_id=record_id,
        timestamp_utc=timestamp_utc,
        actor=actor,
        invoice_id=result.invoice_id,
        po_id=result.po_id,
        decision=result.decision,
        reason_codes=[d.reason_code for d in result.discrepancies],
        policy_version=result.policy_version,
        result_digest=result_digest(result),
    )


def _cmp_amount(
    *,
    field: DiscrepancyField,
    code: ReasonCode,
    expected: Decimal,
    actual: Decimal,
    tolerance: Tolerance,
    out: list[Discrepancy],
) -> None:
    delta = actual - expected
    if delta == 0:
        return  # exact match: silent success
    if tolerance.permits(delta, expected):
        out.append(
            Discrepancy(
                reason_code=ReasonCode.WITHIN_TOLERANCE.value,
                field=field,
                severity=Severity.INFO,
                expected=str(expected),
                actual=str(actual),
                delta=delta,
                detail="difference within configured tolerance",
            )
        )
    else:
        out.append(
            Discrepancy(
                reason_code=code.value,
                field=field,
                severity=Severity.ERROR,
                expected=str(expected),
                actual=str(actual),
                delta=delta,
                detail="difference exceeds configured tolerance",
            )
        )


def reconcile_pair(
    invoice: Invoice,
    po: PurchaseOrder,
    policy: ReconciliationPolicy,
) -> ReconciliationResult:
    """Reconcile one invoice against one purchase order, deterministically."""
    findings: list[Discrepancy] = []

    # --- Hard identity checks ------------------------------------------------
    if invoice.currency != po.currency:
        findings.append(
            Discrepancy(
                reason_code=ReasonCode.CURRENCY_MISMATCH.value,
                field=DiscrepancyField.CURRENCY,
                severity=Severity.BLOCKING,
                expected=po.currency,
                actual=invoice.currency,
                detail="invoice and PO currencies differ; no FX policy defined "
                "(docs/OPEN_DECISIONS.md D4)",
            )
        )
    if invoice.supplier_id != po.supplier_id:
        findings.append(
            Discrepancy(
                reason_code=ReasonCode.SUPPLIER_MISMATCH.value,
                field=DiscrepancyField.DOCUMENT,
                severity=Severity.ERROR,
                expected=po.supplier_id,
                actual=invoice.supplier_id,
                detail="invoice supplier does not match PO supplier",
            )
        )

    # --- Gross amount vs PO total --------------------------------------------
    _cmp_amount(
        field=DiscrepancyField.GROSS_AMOUNT,
        code=ReasonCode.GROSS_AMOUNT_MISMATCH,
        expected=po.total_amount.amount,
        actual=invoice.gross_amount.amount,
        tolerance=policy.gross_tolerance,
        out=findings,
    )

    # --- Tax -------------------------------------------------------------------
    if invoice.tax_amount is None:
        if policy.require_tax_amount:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.MISSING_TAX_AMOUNT.value,
                    field=DiscrepancyField.MISSING_FIELD,
                    severity=Severity.BLOCKING,
                    detail="invoice tax_amount absent; assuming zero would be an "
                    "invented financial policy",
                )
            )
    elif po.tax_rate is None:
        findings.append(
            Discrepancy(
                reason_code=ReasonCode.TAX_RATE_UNKNOWN.value,
                field=DiscrepancyField.TAX_AMOUNT,
                severity=Severity.BLOCKING,
                actual=str(invoice.tax_amount.amount),
                detail="PO carries no tax_rate; expected tax cannot be derived",
            )
        )
    else:
        net_expected_from_gross = invoice.gross_amount.amount - invoice.tax_amount.amount
        expected_tax = (net_expected_from_gross * po.tax_rate)
        _cmp_amount(
            field=DiscrepancyField.TAX_AMOUNT,
            code=ReasonCode.TAX_AMOUNT_MISMATCH,
            expected=expected_tax,
            actual=invoice.tax_amount.amount,
            tolerance=policy.tax_tolerance,
            out=findings,
        )

    # --- Net amount -------------------------------------------------------------
    if invoice.net_amount is not None and invoice.tax_amount is not None:
        expected_net = invoice.gross_amount.amount - invoice.tax_amount.amount
        _cmp_amount(
            field=DiscrepancyField.NET_AMOUNT,
            code=ReasonCode.NET_AMOUNT_MISMATCH,
            expected=expected_net,
            actual=invoice.net_amount.amount,
            tolerance=policy.net_tolerance,
            out=findings,
        )

    # --- Line items ---------------------------------------------------------
    if policy.compare_line_items:
        findings.extend(_compare_lines(invoice, po, policy))

    # --- Decision --------------------------------------------------------------
    decision = _decide(findings)

    return _stamp_match_ok(
        _promote_within_tolerance(
            ReconciliationResult(
                invoice_id=invoice.invoice_id,
                po_id=po.po_id,
                decision=decision,
                discrepancies=findings,
                policy_version=policy.version,
            )
        )
    )


def _stamp_match_ok(result: ReconciliationResult) -> ReconciliationResult:
    """Attach a leading MATCH_OK info finding to clean auto-matches (idempotent)."""
    if result.decision is not MatchDecision.AUTO_MATCH:
        return result
    if any(d.reason_code == ReasonCode.MATCH_OK.value for d in result.discrepancies):
        return result
    findings = list(result.discrepancies)
    findings.insert(
        0,
        Discrepancy(
            reason_code=ReasonCode.MATCH_OK.value,
            field=DiscrepancyField.DOCUMENT,
            severity=Severity.INFO,
            detail="all comparisons exact or within configured tolerances",
        ),
    )
    return result.model_copy(update={"discrepancies": findings})


def _promote_within_tolerance(result: ReconciliationResult) -> ReconciliationResult:
    """Tolerance-level differences are *accepted matches*, not discrepancies.

    A result whose only findings are INFO ``WITHIN_TOLERANCE`` entries is
    promoted to ``AUTO_MATCH`` with a leading ``MATCH_OK`` finding; the
    tolerance findings remain in the list for auditability. This keeps the
    guarantee intact: promotion only ever happens from INFO findings — any
    WARNING/ERROR/BLOCKING finding still prevents auto-approval.
    """
    if result.decision is not MatchDecision.MATCH_WITH_DISCREPANCY:
        return result
    substantive = [d for d in result.discrepancies
                   if d.reason_code != ReasonCode.WITHIN_TOLERANCE.value]
    if substantive:
        return result
    return result.model_copy(update={"decision": MatchDecision.AUTO_MATCH})


def _compare_lines(
    invoice: Invoice, po: PurchaseOrder, policy: ReconciliationPolicy
) -> list[Discrepancy]:
    findings: list[Discrepancy] = []
    inv_lines = {li.line_number: li for li in invoice.line_items}
    po_lines = {li.line_number: li for li in po.line_items}
    if len(inv_lines) != len(invoice.line_items):
        findings.append(
            Discrepancy(
                reason_code=ReasonCode.INVALID_INPUT.value,
                field=DiscrepancyField.DUPLICATE_ID,
                severity=Severity.BLOCKING,
                detail="duplicate line_number values on invoice",
            )
        )
    if len(po_lines) != len(po.line_items):
        findings.append(
            Discrepancy(
                reason_code=ReasonCode.INVALID_INPUT.value,
                field=DiscrepancyField.DUPLICATE_ID,
                severity=Severity.BLOCKING,
                detail="duplicate line_number values on PO",
            )
        )
    for num in sorted(set(po_lines) | set(inv_lines)):
        ili, pli = inv_lines.get(num), po_lines.get(num)
        if pli is not None and ili is None:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.MISSING_LINE_ITEM.value,
                    field=DiscrepancyField.LINE_TOTAL,
                    severity=Severity.WARNING,
                    expected=str(pli.derived_total().amount),
                    detail=f"invoice lacks line {num} present on PO",
                )
            )
            continue
        if ili is not None and pli is None:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.UNEXPECTED_LINE_ITEM.value,
                    field=DiscrepancyField.LINE_TOTAL,
                    severity=Severity.WARNING,
                    actual=str(ili.derived_total().amount),
                    detail=f"invoice bills line {num} not present on PO",
                )
            )
            continue
        assert ili is not None and pli is not None
        if ili.sku != pli.sku:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.INVALID_INPUT.value,
                    field=DiscrepancyField.LINE_TOTAL,
                    severity=Severity.BLOCKING,
                    expected=pli.sku,
                    actual=ili.sku,
                    detail=f"line {num}: SKU mismatch; ambiguous pairing",
                )
            )
            continue
        if ili.quantity != pli.quantity:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.LINE_QUANTITY_MISMATCH.value,
                    field=DiscrepancyField.LINE_QUANTITY,
                    severity=Severity.WARNING,
                    expected=str(pli.quantity),
                    actual=str(ili.quantity),
                    delta=ili.quantity - pli.quantity,
                    detail=f"line {num}: invoiced quantity differs from ordered",
                )
            )
        exp_total = pli.line_total or pli.derived_total()
        act_total = ili.line_total or ili.derived_total()
        _cmp_amount(
            field=DiscrepancyField.LINE_TOTAL,
            code=ReasonCode.LINE_TOTAL_MISMATCH,
            expected=exp_total.amount,
            actual=act_total.amount,
            tolerance=policy.line_tolerance,
            out=findings,
        )
    return findings


_ERROR_CODES = {
    ReasonCode.GROSS_AMOUNT_MISMATCH.value,
    ReasonCode.TAX_AMOUNT_MISMATCH.value,
    ReasonCode.NET_AMOUNT_MISMATCH.value,
    ReasonCode.LINE_TOTAL_MISMATCH.value,
    ReasonCode.SUPPLIER_MISMATCH.value,
    ReasonCode.DUPLICATE_INVOICE_ID.value,
    ReasonCode.DUPLICATE_PO_ID.value,
}


def _decide(findings: Sequence[Discrepancy]) -> MatchDecision:
    severities = {f.severity for f in findings}
    codes = {f.reason_code for f in findings}
    if Severity.BLOCKING in severities:
        # Missing/invalid/ambiguous data can never auto-approve. A currency
        # mismatch is additionally a deterministic hard failure -> REJECT.
        if codes == {ReasonCode.CURRENCY_MISMATCH.value}:
            return MatchDecision.REJECT
        return MatchDecision.MANUAL_REVIEW
    if Severity.ERROR in severities:
        return MatchDecision.REJECT if codes & _ERROR_CODES else MatchDecision.MANUAL_REVIEW
    if severities:
        return MatchDecision.MATCH_WITH_DISCREPANCY
    return MatchDecision.AUTO_MATCH


def reconcile_batch(
    invoices: Iterable[Invoice],
    pos: Iterable[PurchaseOrder],
    policy: ReconciliationPolicy,
) -> list[ReconciliationResult]:
    """Reconcile each invoice to its referenced PO.

    * Duplicate invoice IDs / PO IDs are flagged (DUPLICATE_*_ID, BLOCKING)
      and every affected pair goes to MANUAL_REVIEW.
    * Invoices whose ``po_reference`` matches no PO are flagged
      INCOMPLETE_DOCUMENT -> MANUAL_REVIEW.
    """
    po_by_id: dict[str, PurchaseOrder] = {}
    dup_po_ids: set[str] = set()
    for po in pos:
        if po.po_id in po_by_id:
            dup_po_ids.add(po.po_id)
        else:
            po_by_id[po.po_id] = po

    seen_invoice_ids: set[str] = set()
    dup_invoice_ids: set[str] = set()
    for inv in invoices:
        if inv.invoice_id in seen_invoice_ids:
            dup_invoice_ids.add(inv.invoice_id)
        seen_invoice_ids.add(inv.invoice_id)

    results: list[ReconciliationResult] = []
    for inv in invoices:
        findings: list[Discrepancy] = []
        if inv.invoice_id in dup_invoice_ids:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.DUPLICATE_INVOICE_ID.value,
                    field=DiscrepancyField.DUPLICATE_ID,
                    severity=Severity.BLOCKING,
                    detail="invoice_id appears more than once in the batch",
                )
            )
        po = po_by_id.get(inv.po_reference)
        if po is None:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.INCOMPLETE_DOCUMENT.value,
                    field=DiscrepancyField.MISSING_FIELD,
                    severity=Severity.BLOCKING,
                    expected=inv.po_reference,
                    detail="no purchase order matches po_reference",
                )
            )
        if po is not None and po.po_id in dup_po_ids:
            findings.append(
                Discrepancy(
                    reason_code=ReasonCode.DUPLICATE_PO_ID.value,
                    field=DiscrepancyField.DUPLICATE_ID,
                    severity=Severity.BLOCKING,
                    detail="referenced po_id appears more than once in the batch",
                )
            )
        if po is not None:
            pair = reconcile_pair(inv, po, policy)
            findings.extend(
                d for d in pair.discrepancies
                if d.reason_code != ReasonCode.MATCH_OK.value
            )
        result = ReconciliationResult(
            invoice_id=inv.invoice_id,
            po_id=inv.po_reference,
            decision=_decide(findings),
            discrepancies=findings,
            policy_version=policy.version,
        )
        # Promote tolerance-only outcomes to AUTO_MATCH, then stamp MATCH_OK
        # once so batch and pair paths behave identically.
        results.append(_stamp_match_ok(_promote_within_tolerance(result)))
    return results
