"""Reconciliation core for the AMD Hackathon invoice-to-order agent.

Deterministic, Decimal-based reconciliation only. All LLM / Evolus / vLLM
integrations live behind interfaces (see :mod:`recon.llm`) and have **no**
real implementation until their APIs and runtimes are verified — see
``docs/RECONNAISSANCE.md``.
"""

from recon.models import (  # noqa: F401
    AuditRecord,
    Discrepancy,
    Invoice,
    MatchDecision,
    Money,
    PurchaseOrder,
    ReconciliationResult,
)
from recon.policy import (  # noqa: F401
    ReasonCode,
    ReconciliationPolicy,
    Tolerance,
)
from recon.engine import reconcile_pair, reconcile_batch  # noqa: F401

__all__ = [
    "AuditRecord",
    "Discrepancy",
    "Invoice",
    "Money",
    "PurchaseOrder",
    "ReconciliationResult",
    "MatchDecision",
    "ReasonCode",
    "ReconciliationPolicy",
    "Tolerance",
    "reconcile_pair",
    "reconcile_batch",
]
