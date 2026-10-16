# Repositorio-Enfoque-amd-act-III

AMD Hackathon — AI Invoice-to-Order Reconciliation Agent.

Current state: **reconciliation core only** (deterministic, Decimal-based, fully
unit-tested). No LLM is installed or required; all Evolus / vLLM / AMD GPU
integrations remain behind interfaces pending verified APIs and runtimes
(see [`docs/RECONNAISSANCE.md`](docs/RECONNAISSANCE.md)).

## Layout

```
src/recon/         reconciliation core package
  models.py        canonical typed schemas (Invoice, PurchaseOrder, ...)
  policy.py        tolerances + machine-readable reason codes
  engine.py        deterministic reconciliation (pure functions)
  llm.py           LLM interface + scripted mock (no real provider yet)
tests/             pytest suite
docs/              reconnaissance, data contracts, policies, open decisions
```

## Local setup & tests

Requires Python >= 3.11. From the repository root:

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
pytest -q
```

No network access, model download, GPU, or credentials are needed to run the
test suite.

## Key guarantees

- Monetary math uses `decimal.Decimal` exclusively; floats are rejected by the
  schema layer.
- Every tolerance comes from an explicit, versioned `ReconciliationPolicy`;
  nothing is hardcoded or assumed.
- Missing, invalid, or ambiguous data always yields `MANUAL_REVIEW` with a
  BLOCKING reason code — never an approval recommendation.
- Results are pure functions of inputs and carry a SHA-256 digest for audit.

## Documentation

- [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) — schemas & serialization
- [`docs/RECONCILIATION_POLICY.md`](docs/RECONCILIATION_POLICY.md) — comparison rules & reason codes
- [`docs/OPEN_DECISIONS.md`](docs/OPEN_DECISIONS.md) — unresolved business questions (read before configuring production tolerances)
