# Recon Agent — Multi-Source Reconciliation Agent

**Track 4: AI Finance Controller — Razorpay AI Buildathon**

## What it does

Reconciles a batch of transactions across three independent sources of truth:

- `payment_gateway.csv` — what the payment processor recorded
- `bank_statement.csv` — what actually cleared the bank (dates lag, fees differ)
- `internal_ledger.csv` — what the company's books say

The agent matches records across all three, resolves ambiguous cases with an
LLM adjudicator, and produces:

- a **match rate** (exact / fuzzy / LLM-resolved / unresolved)
- a full **audit trail** (every match, and *why* it was made)
- an honest **exception list** — records it could not reconcile, with a stated reason

## Why this design

Real reconciliation is never a single clean join. Bank clearing delays shift
dates, gateway fees get netted differently in the ledger, IDs get typo'd on
manual entry, and duplicates happen. The pipeline is staged so the
LLM is only invoked where deterministic logic genuinely can't decide —
not as a hammer for the whole problem:

1. **Exact match** — transaction ID equality. No ambiguity, no LLM.
2. **Fuzzy match** — amount tolerance + date window + counterparty similarity
   scored deterministically. High-confidence matches auto-accept.
3. **LLM adjudication** — only mid-confidence candidates get sent to the
   adjudicator, with the specific reasons it's ambiguous, and it must return
   a decision + rationale.
4. **Exception list** — anything left is reported, not hidden or forced.

## Architecture

```
src/
  generate_data.py   # builds the synthetic 3-source batch with known ground truth
  matcher.py          # exact + fuzzy deterministic matching engine
  adjudicator.py       # pluggable LLM interface (Mock here, Ollama for real use)
  reconcile.py        # orchestrates the pipeline end-to-end
  report.py            # builds the match-rate report + exception list + audit trail
  cli.py               # entry point
```

## Running it

```bash
pip install -r requirements.txt
python -m src.cli --records 60 --seed 42
```

Outputs land in `reports/`:
- `report.md` — human-readable summary
- `audit_trail.json` — every decision, with reasoning
- `exceptions.csv` — unresolved records

## Swapping in a real local LLM

By default this runs with `MockAdjudicator` (deterministic, transparent —
see `src/adjudicator.py`) so the pipeline runs anywhere with no external
calls. To use a real local model:

```bash
ollama pull llama3.2
ollama serve
python -m src.cli --adjudicator ollama --model llama3.2
```

No other code changes — `adjudicator.py` defines one interface both
implementations satisfy.

## What broke, and how we got out

See `NOTES.md` — kept live during the build.
