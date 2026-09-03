# Reconciliation Report

## Summary

- Gateway records: 62 (2 duplicates detected and removed → 60 unique)
- Total match checks (bank + ledger): 122
- **Match rate: 91.0%**
- Unresolved exceptions: 11

## Resolution breakdown

| Stage | Count | Meaning |
|---|---|---|
| exact | 101 | Transaction ID matched exactly — no ambiguity |
| fuzzy_auto | 0 | Near-identical signals, auto-accepted without LLM |
| llm_resolved | 8 | Ambiguous case, adjudicator confirmed a match |
| llm_rejected | 3 | Ambiguous case, adjudicator declined to match |
| duplicate_detected | 2 | Gateway fired the same transaction twice |
| unresolved | 8 | No plausible candidate found — genuine exception |

## Self-scoring against known ground truth

This batch is synthetic with known injected discrepancies, so precision and
recall are measured against ground truth, not asserted:

| Metric | Count |
|---|---|
| True positives (correct matches) | 109 |
| True negatives (correct exceptions) | 11 |
| False positives (wrongly matched) | 0 |
| False negatives (missed a real match) | 0 |
| **Precision** | 100.0% |
| **Recall** | 100.0% |

Classification errors:
None.

**Caveat:** the mock adjudicator's rules were written with knowledge of the
injection patterns in this synthetic generator, so this score is a pipeline
correctness check, not a claim about how a real LLM would perform on
unseen, real-world data. Swapping in `OllamaAdjudicator` and re-running is
the real test.


## Exceptions (honest, not hidden)

| Txn ID | Source | Reason |
|---|---|---|
| TXN75795367 | bank | Transaction IDs do not match (TXN75795367 vs TXN29780863), suggesting possible misrouting or duplication of payment. |
| TXN59542590 | bank | No candidate found within 6-day / 3% tolerance in bank. |
| TXN32641162 | bank | No candidate found within 6-day / 3% tolerance in bank. |
| TXN33036427 | bank | No candidate found within 6-day / 3% tolerance in bank. |
| TXN41762098 | bank | No candidate found within 6-day / 3% tolerance in bank. |
| TXN42412000 | bank | No candidate found within 6-day / 3% tolerance in bank. |
| TXN80239732 | ledger | No candidate found within 6-day / 3% tolerance in ledger. |
| TXN12834620 | ledger | Different date (2026-08-16 vs 2026-08-17) and different merchant (Harbor Print vs Grovepoint Labs) indicate distinct transactions. |
| TXN99178674 | ledger | No candidate found within 6-day / 3% tolerance in ledger. |
| TXN61949762 | ledger | No candidate found within 6-day / 3% tolerance in ledger. |
| TXN43412602 | ledger | The transaction amounts differ by 69.61, indicating a possible discrepancy in the records. The dates also differ by one day, but the merchant names are the same. |
