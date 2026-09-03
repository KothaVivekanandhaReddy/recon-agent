"""
Honest scoring against ground truth. Not a unit test framework — a script
that answers: for every gateway transaction x source pair, did the pipeline
reach the RIGHT conclusion (matched when it should, exception when it should)?

This is what "the bar" (measured precision/recall, false-positive cost)
actually requires — a match-rate number alone doesn't prove correctness.
"""
import csv
import json
from pathlib import Path

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")

SHOULD_BE_MISSING = {
    "bank": {"missing_in_bank"},
    "ledger": {"missing_in_ledger"},
}


def load_ground_truth():
    with open(DATA_DIR / "ground_truth.csv", encoding="utf-8") as f:
        return {r["txn_id"]: r["discrepancy"] for r in csv.DictReader(f)}


def load_audit_trail():
    with open(REPORT_DIR / "audit_trail.json", encoding="utf-8") as f:
        return json.load(f)


def score():
    gt = load_ground_truth()
    audit = load_audit_trail()

    # index audit entries by (txn_id, source)
    by_key = {}
    for a in audit:
        if a["source"] in ("bank", "ledger"):
            by_key.setdefault((a["txn_id"], a["source"]), []).append(a)

    RESOLVED_STAGES = {"exact", "fuzzy_auto", "llm_resolved"}
    EXCEPTION_STAGES = {"unresolved", "llm_rejected"}

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
                    tn += 1  # correctly flagged as missing
                elif was_matched:
                    fp += 1  # WRONG: matched something that shouldn't exist here
                    errors.append((txn_id, source, "false_positive", disc))
                # if neither, gateway-side duplicate consumed the audit slot differently — skip
            else:
                if was_matched:
                    tp += 1  # correctly matched
                elif was_exception:
                    fn += 1  # WRONG: should have matched, didn't
                    errors.append((txn_id, source, "false_negative", disc))

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")

    print(f"True positives (correct matches):     {tp}")
    print(f"True negatives (correct exceptions):   {tn}")
    print(f"False positives (wrongly matched):     {fp}")
    print(f"False negatives (missed a real match): {fn}")
    print(f"Precision: {precision:.1%}" if precision == precision else "Precision: n/a")
    print(f"Recall:    {recall:.1%}" if recall == recall else "Recall: n/a")

    if errors:
        print("\nErrors:")
        for txn_id, source, kind, disc in errors:
            print(f"  {txn_id} [{source}] {kind} (true discrepancy: {disc})")
    else:
        print("\nNo classification errors against ground truth.")


if __name__ == "__main__":
    score()
