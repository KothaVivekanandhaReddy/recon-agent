"""
Orchestrates the full reconciliation: gateway vs bank, gateway vs ledger.
Deterministic matches resolve immediately; ambiguous fuzzy candidates are
escalated to the adjudicator; anything still unresolved is an exception.
"""
from __future__ import annotations
import csv
from pathlib import Path

from .matcher import match_source, find_candidates
from .adjudicator import Adjudicator, AdjudicationRequest


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_reconciliation(data_dir: Path, adjudicator: Adjudicator) -> dict:
    gateway_rows = _load_csv(data_dir / "payment_gateway.csv")
    bank_rows = _load_csv(data_dir / "bank_statement.csv")
    ledger_rows = _load_csv(data_dir / "internal_ledger.csv")

    # Detect gateway-side duplicates first: same txn_id appearing twice
    seen, dup_ids = set(), set()
    for row in gateway_rows:
        if row["txn_id"] in seen:
            dup_ids.add(row["txn_id"])
        seen.add(row["txn_id"])
    # dedupe for matching purposes, but record the duplicate as its own audit entry
    deduped_gateway = []
    seen_again = set()
    for row in gateway_rows:
        if row["txn_id"] in seen_again:
            continue
        deduped_gateway.append(row)
        seen_again.add(row["txn_id"])

    audit_trail = []
    exceptions = []

    for dup_id in dup_ids:
        audit_trail.append({
            "txn_id": dup_id, "source": "gateway", "stage": "duplicate_detected",
            "confidence": 1.0,
            "rationale": "Same transaction ID appeared more than once in the gateway export — treated as a duplicate fire, not a new transaction.",
        })

    def process_source(other_rows: list[dict], source: str):
        decisions, _ = match_source(deduped_gateway, other_rows, source)
        for d in decisions:
            gw_row = next(r for r in deduped_gateway if r["txn_id"] == d.gateway_txn_id)

            if d.stage in ("exact", "fuzzy_auto"):
                audit_trail.append({
                    "txn_id": d.gateway_txn_id, "source": source, "stage": d.stage,
                    "confidence": d.confidence, "rationale": d.rationale,
                    "matched_key": d.matched_key,
                })
            elif d.stage == "unresolved":
                exceptions.append({
                    "txn_id": d.gateway_txn_id, "source": source,
                    "reason": d.rationale,
                })
                audit_trail.append({
                    "txn_id": d.gateway_txn_id, "source": source, "stage": "unresolved",
                    "confidence": 0.0, "rationale": d.rationale,
                })
            elif d.stage == "llm":
                candidates = find_candidates(gw_row, other_rows, source)
                best = candidates[0]
                req = AdjudicationRequest(
                    gateway_record=gw_row, candidate_record=best["row"],
                    candidate_source=source, signals=best["signals"],
                )
                result = adjudicator.adjudicate(req)
                if result.match:
                    audit_trail.append({
                        "txn_id": d.gateway_txn_id, "source": source, "stage": "llm_resolved",
                        "confidence": result.confidence, "rationale": result.rationale,
                        "matched_key": d.matched_key, "resolved_by": result.resolved_by,
                    })
                else:
                    exceptions.append({
                        "txn_id": d.gateway_txn_id, "source": source,
                        "reason": result.rationale,
                    })
                    audit_trail.append({
                        "txn_id": d.gateway_txn_id, "source": source, "stage": "llm_rejected",
                        "confidence": result.confidence, "rationale": result.rationale,
                        "resolved_by": result.resolved_by,
                    })

    process_source(bank_rows, "bank")
    process_source(ledger_rows, "ledger")

    total_checks = len(audit_trail)
    matched = sum(1 for a in audit_trail if a["stage"] in ("exact", "fuzzy_auto", "llm_resolved", "duplicate_detected"))

    return {
        "total_gateway_records": len(gateway_rows),
        "deduped_gateway_records": len(deduped_gateway),
        "duplicates_found": len(dup_ids),
        "total_checks": total_checks,
        "matched": matched,
        "match_rate": round(matched / total_checks, 4) if total_checks else 0,
        "exceptions": exceptions,
        "audit_trail": audit_trail,
    }
