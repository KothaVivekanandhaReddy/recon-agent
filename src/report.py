from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path


def write_reports(result: dict, out_dir: Path, ground_truth: list[dict] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "audit_trail.json", "w", encoding="utf-8") as f:
        json.dump(result["audit_trail"], f, indent=2, default=str)

    with open(out_dir / "exceptions.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["txn_id", "source", "reason"])
        writer.writeheader()
        for e in result["exceptions"]:
            writer.writerow(e)

    stage_counts = Counter(a["stage"] for a in result["audit_trail"])

    scoring_section = ""
    if ground_truth is not None:
        scoring_section = _score_against_ground_truth(result, ground_truth)

    md = f"""# Reconciliation Report

## Summary

- Gateway records: {result['total_gateway_records']} ({result['duplicates_found']} duplicates detected and removed → {result['deduped_gateway_records']} unique)
- Total match checks (bank + ledger): {result['total_checks']}
- **Match rate: {result['match_rate']:.1%}**
- Unresolved exceptions: {len(result['exceptions'])}

## Resolution breakdown

| Stage | Count | Meaning |
|---|---|---|
| exact | {stage_counts.get('exact', 0)} | Transaction ID matched exactly — no ambiguity |
| fuzzy_auto | {stage_counts.get('fuzzy_auto', 0)} | Near-identical signals, auto-accepted without LLM |
| llm_resolved | {stage_counts.get('llm_resolved', 0)} | Ambiguous case, adjudicator confirmed a match |
| llm_rejected | {stage_counts.get('llm_rejected', 0)} | Ambiguous case, adjudicator declined to match |
| duplicate_detected | {stage_counts.get('duplicate_detected', 0)} | Gateway fired the same transaction twice |
| unresolved | {stage_counts.get('unresolved', 0)} | No plausible candidate found — genuine exception |

{scoring_section}

## Exceptions (honest, not hidden)

{"None — everything reconciled." if not result['exceptions'] else _format_exceptions(result['exceptions'])}
"""
    with open(out_dir / "report.md", "w", encoding="utf-8") as f:
        f.write(md)


def _format_exceptions(exceptions: list[dict]) -> str:
    lines = ["| Txn ID | Source | Reason |", "|---|---|---|"]
    for e in exceptions:
        lines.append(f"| {e['txn_id']} | {e['source']} | {e['reason']} |")
    return "\n".join(lines)


SHOULD_BE_MISSING = {
    "bank": {"missing_in_bank"},
    "ledger": {"missing_in_ledger"},
}
RESOLVED_STAGES = {"exact", "fuzzy_auto", "llm_resolved"}
EXCEPTION_STAGES = {"unresolved", "llm_rejected"}


def _score_against_ground_truth(result: dict, ground_truth: list[dict]) -> str:
    """
    Per-source precision/recall against known ground truth — not just a
    match-rate number, since match rate alone can hide false positives.
    Shared logic with tests/test_scoring.py.
    """
    gt = {g["txn_id"]: g["discrepancy"] for g in ground_truth}
    by_key = {}
    for a in result["audit_trail"]:
        if a["source"] in ("bank", "ledger"):
            by_key.setdefault((a["txn_id"], a["source"]), []).append(a)

    tp = fp = fn = tn = 0
    errors = []
    for txn_id, disc in gt.items():
        for source in ("bank", "ledger"):
            entries = by_key.get((txn_id, source), [])
            stages = {e["stage"] for e in entries}
            was_matched = bool(stages & RESOLVED_STAGES)
            was_exception = bool(stages & EXCEPTION_STAGES)
            should_be_missing = disc in SHOULD_BE_MISSING[source]

            if should_be_missing:
                if was_exception:
                    tn += 1
                elif was_matched:
                    fp += 1
                    errors.append((txn_id, source, "false_positive"))
            else:
                if was_matched:
                    tp += 1
                elif was_exception:
                    fn += 1
                    errors.append((txn_id, source, "false_negative"))

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")

    error_lines = "\n".join(f"- {t} [{s}]: {k}" for t, s, k in errors) if errors else "None."

    return f"""## Self-scoring against known ground truth

This batch is synthetic with known injected discrepancies, so precision and
recall are measured against ground truth, not asserted:

| Metric | Count |
|---|---|
| True positives (correct matches) | {tp} |
| True negatives (correct exceptions) | {tn} |
| False positives (wrongly matched) | {fp} |
| False negatives (missed a real match) | {fn} |
| **Precision** | {f'{precision:.1%}' if precision == precision else 'n/a'} |
| **Recall** | {f'{recall:.1%}' if recall == recall else 'n/a'} |

Classification errors:
{error_lines}

**Caveat:** the mock adjudicator's rules were written with knowledge of the
injection patterns in this synthetic generator, so this score is a pipeline
correctness check, not a claim about how a real LLM would perform on
unseen, real-world data. Swapping in `OllamaAdjudicator` and re-running is
the real test.
"""
