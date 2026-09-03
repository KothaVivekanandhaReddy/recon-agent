"""
Deterministic matching engine. Two stages:
  1. Exact match on ID — resolved immediately, no LLM.
  2. Fuzzy candidate scoring — computes signals (amount diff, date diff,
     ID similarity). High-confidence candidates auto-accept; mid-confidence
     candidates go to the adjudicator; nothing found becomes an exception.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher


def _id_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _parse_date(s: str) -> date:
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


@dataclass
class MatchDecision:
    gateway_txn_id: str
    source: str                # "bank" or "ledger"
    matched_key: str | None    # the key in the other source, if any
    stage: str                 # "exact" | "fuzzy_auto" | "llm" | "unresolved"
    confidence: float
    rationale: str


AMOUNT_TOL_PCT = 0.03   # up to 3% off (covers fee-netting) still a *candidate*
DATE_WINDOW_DAYS = 6     # bank clearing delay window
FUZZY_AUTO_ACCEPT = 0.97  # signals this strong auto-accept, skip the LLM


def find_candidates(gw_row: dict, other_rows: list[dict], source: str) -> list[dict]:
    """Return plausible candidates within amount/date tolerance, with signals attached."""
    id_field = "bank_ref" if source == "bank" else "entry_id"
    date_field = "value_date" if source == "bank" else "posted_date"
    amount_field = "credit_amount" if source == "bank" else "net_amount"

    gw_date = _parse_date(gw_row["date"])
    candidates = []
    for row in other_rows:
        try:
            row_date = _parse_date(row[date_field])
        except Exception:
            continue
        date_diff = abs((row_date - gw_date).days)
        if date_diff > DATE_WINDOW_DAYS:
            continue

        amount_diff = abs(float(row[amount_field]) - float(gw_row["amount"]))
        if amount_diff / max(float(gw_row["amount"]), 1) > AMOUNT_TOL_PCT and amount_diff > 1:
            # still allow if ID is near-exact (typo case) even if amount matches exactly
            if not (amount_diff < 0.01):
                continue

        id_sim = _id_similarity(gw_row["txn_id"], row[id_field])

        candidates.append({
            "row": row,
            "signals": {
                "amount_diff": round(amount_diff, 2),
                "date_diff_days": date_diff,
                "id_similarity": round(id_sim, 3),
            },
        })

    # best candidates first: closest ID match, then smallest amount diff
    candidates.sort(key=lambda c: (-c["signals"]["id_similarity"], c["signals"]["amount_diff"]))
    return candidates


def match_source(gateway_rows: list[dict], other_rows: list[dict], source: str) -> tuple[list[MatchDecision], list[dict]]:
    """
    Matches gateway_rows against one other source. Returns decisions and the
    list of "used up" other_rows (to detect duplicates / unmatched leftovers later).
    """
    id_field = "bank_ref" if source == "bank" else "entry_id"
    decisions = []
    consumed_keys = set()
    remaining_other = list(other_rows)

    for gw_row in gateway_rows:
        # Stage 1: exact ID match, not already consumed
        exact = next((r for r in remaining_other if r[id_field] == gw_row["txn_id"] and r[id_field] not in consumed_keys), None)
        if exact:
            decisions.append(MatchDecision(
                gateway_txn_id=gw_row["txn_id"], source=source, matched_key=exact[id_field],
                stage="exact", confidence=1.0, rationale="Exact ID match.",
            ))
            consumed_keys.add(exact[id_field])
            continue

        # Stage 2: fuzzy candidates
        candidates = find_candidates(gw_row, [r for r in remaining_other if r[id_field] not in consumed_keys], source)
        if not candidates:
            decisions.append(MatchDecision(
                gateway_txn_id=gw_row["txn_id"], source=source, matched_key=None,
                stage="unresolved", confidence=0.0,
                rationale=f"No candidate found within {DATE_WINDOW_DAYS}-day / {AMOUNT_TOL_PCT:.0%} tolerance in {source}.",
            ))
            continue

        best = candidates[0]
        sig = best["signals"]
        if sig["id_similarity"] >= FUZZY_AUTO_ACCEPT and sig["amount_diff"] < 0.01 and sig["date_diff_days"] == 0:
            decisions.append(MatchDecision(
                gateway_txn_id=gw_row["txn_id"], source=source, matched_key=best["row"][id_field],
                stage="fuzzy_auto", confidence=0.99, rationale="Near-identical ID, amount, and date.",
            ))
            consumed_keys.add(best["row"][id_field])
        else:
            # ambiguous — flagged for LLM adjudication upstream
            decisions.append(MatchDecision(
                gateway_txn_id=gw_row["txn_id"], source=source, matched_key=best["row"][id_field],
                stage="llm", confidence=0.0, rationale="Ambiguous — needs adjudication.",
            ))
            # do NOT consume yet; orchestrator finalizes after adjudication

    return decisions, remaining_other
