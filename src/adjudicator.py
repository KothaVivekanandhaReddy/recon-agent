"""
Adjudicator interface. Any implementation gets a candidate pair with the
specific signals that made deterministic matching ambiguous, and must return
a decision + rationale. This is the ONLY place the pipeline calls out to an
LLM — everything the deterministic matcher can already decide never reaches
here.
"""
from __future__ import annotations
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AdjudicationRequest:
    gateway_record: dict
    candidate_record: dict
    candidate_source: str  # "bank" or "ledger"
    signals: dict          # e.g. {"amount_diff": 340.5, "date_diff_days": 4, "id_similarity": 0.89}


@dataclass
class AdjudicationResult:
    match: bool
    confidence: float
    rationale: str
    resolved_by: str  # "mock" or model name


class Adjudicator(ABC):
    @abstractmethod
    def adjudicate(self, req: AdjudicationRequest) -> AdjudicationResult:
        ...


class MockAdjudicator(Adjudicator):
    """
    Deterministic stand-in used in this sandbox (no external model access
    here). Rules mirror what a real LLM adjudicator should conclude given
    the same signals — used to validate the pipeline end-to-end. Every
    decision states which signal it leaned on, exactly as a real LLM
    rationale would, so swapping in a real model changes nothing else.
    """

    def adjudicate(self, req: AdjudicationRequest) -> AdjudicationResult:
        s = req.signals
        amount_diff = float(s.get("amount_diff", 0))
        date_diff = float(s.get("date_diff_days", 0))
        id_sim = float(s.get("id_similarity", 0))
        gross = float(req.gateway_record.get("amount", 1) or 1)

        # Fee-netting pattern: amount is short by a small, plausible fee %.
        # Real fee-netted records keep the SAME transaction ID — only the
        # amount changes — so require high ID similarity too. Without this,
        # amount+date proximity alone can coincidentally match two unrelated
        # transactions (found via cross-seed testing, see NOTES.md).
        if 0 < amount_diff / gross < 0.03 and date_diff <= 1 and id_sim >= 0.85:
            return AdjudicationResult(
                match=True, confidence=0.86,
                rationale=(
                    f"Amount differs by {amount_diff:.2f} "
                    f"({amount_diff/gross:.1%} of gross) with matching date — "
                    "consistent with a processing fee netted out on this source."
                ),
                resolved_by="mock",
            )

        # Clearing-delay pattern: same amount, ID; date within a plausible window
        if amount_diff == 0 and 1 < date_diff <= 5 and id_sim >= 0.99:
            return AdjudicationResult(
                match=True, confidence=0.9,
                rationale=(
                    f"Amount and ID match exactly; date differs by {date_diff} days — "
                    "consistent with standard bank clearing delay, not a distinct transaction."
                ),
                resolved_by="mock",
            )

        # Likely typo: very high ID similarity, amount/date otherwise match
        if id_sim >= 0.85 and amount_diff == 0 and date_diff <= 1:
            return AdjudicationResult(
                match=True, confidence=0.75,
                rationale=(
                    f"ID similarity {id_sim:.0%} with identical amount and date — "
                    "likely a manual-entry typo rather than a different transaction."
                ),
                resolved_by="mock",
            )

        return AdjudicationResult(
            match=False, confidence=0.4,
            rationale=(
                f"Signals too weak to conclude a match (amount_diff={amount_diff:.2f}, "
                f"date_diff={date_diff}d, id_similarity={id_sim:.0%}) — "
                "escalating to exception list rather than guessing."
            ),
            resolved_by="mock",
        )


class OllamaAdjudicator(Adjudicator):
    """
    Real local-LLM adjudicator via Ollama's HTTP API (http://localhost:11434).
    Not usable inside this sandbox (no network access to run a local model
    server here) — provided so this swaps in with zero pipeline changes on
    a machine that has Ollama running.
    """

    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host

    def adjudicate(self, req: AdjudicationRequest) -> AdjudicationResult:
        import urllib.request

        prompt = f"""You are a financial reconciliation adjudicator. Decide if these two
records refer to the SAME underlying transaction.

Gateway record: {json.dumps(req.gateway_record)}
Candidate ({req.candidate_source}) record: {json.dumps(req.candidate_record)}
Computed signals: {json.dumps(req.signals)}

Respond ONLY as JSON: {{"match": true/false, "confidence": 0-1, "rationale": "..."}}"""

        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }).encode()

        request = urllib.request.Request(
            f"{self.host}/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as resp:
            payload = json.loads(resp.read())

        decision = json.loads(payload["response"])
        return AdjudicationResult(
            match=bool(decision["match"]),
            confidence=float(decision["confidence"]),
            rationale=decision["rationale"],
            resolved_by=self.model,
        )


def get_adjudicator(kind: str, model: str = "llama3.2") -> Adjudicator:
    if kind == "mock":
        return MockAdjudicator()
    if kind == "ollama":
        return OllamaAdjudicator(model=model)
    raise ValueError(f"Unknown adjudicator kind: {kind}")
