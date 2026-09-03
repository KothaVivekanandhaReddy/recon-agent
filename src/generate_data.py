"""
Generates a synthetic reconciliation batch: three CSVs (gateway, bank, ledger)
derived from one ground-truth transaction set, with deliberately injected
discrepancies of known type. Ground truth is saved separately so we can
score our own pipeline's accuracy honestly.
"""
import argparse
import csv
import random
import string
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

MERCHANTS = [
    "Acme Retail", "Bluebird Foods", "Crest Logistics", "Delta Textiles",
    "Everline Media", "Fernway Studio", "Grovepoint Labs", "Harbor Print",
    "Indigo Travel", "Junction Cafe",
]

DISCREPANCY_TYPES = [
    "clean",              # matches perfectly everywhere
    "date_shift",         # bank clears N days later
    "amount_fee_netted",  # ledger amount = gross - fee
    "id_typo",             # one char changed in an ID on one source
    "missing_in_bank",     # not yet cleared
    "missing_in_ledger",   # not yet booked
    "duplicate_gateway",   # gateway double-fired the record
]


@dataclass
class Txn:
    txn_id: str
    date: date
    amount: float
    merchant: str
    discrepancy: str


def _rand_id(rng: random.Random) -> str:
    return "TXN" + "".join(rng.choices(string.digits, k=8))


def _typo(txn_id: str, rng: random.Random) -> str:
    pos = rng.randrange(3, len(txn_id))  # keep the TXN prefix intact
    digit = rng.choice([d for d in string.digits if d != txn_id[pos]])
    return txn_id[:pos] + digit + txn_id[pos + 1:]


def generate(n_records: int, seed: int, out_dir: Path) -> list[dict]:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    ground_truth = []
    gateway_rows, bank_rows, ledger_rows = [], [], []

    start = date(2026, 8, 1)

    for i in range(n_records):
        txn_id = _rand_id(rng)
        txn_date = start + timedelta(days=rng.randrange(0, 30))
        amount = round(rng.uniform(150, 45000), 2)
        merchant = rng.choice(MERCHANTS)
        disc = rng.choices(
            DISCREPANCY_TYPES,
            weights=[40, 15, 15, 10, 8, 8, 4],  # mostly clean, realistic tail
            k=1,
        )[0]

        ground_truth.append(asdict(Txn(txn_id, txn_date, amount, merchant, disc)))

        gw_row = {"txn_id": txn_id, "date": txn_date.isoformat(), "amount": amount, "merchant": merchant}
        bank_row = {"bank_ref": txn_id, "value_date": txn_date.isoformat(), "credit_amount": amount, "narration": merchant}
        led_row = {"entry_id": txn_id, "posted_date": txn_date.isoformat(), "net_amount": amount, "party": merchant}

        if disc == "date_shift":
            bank_row["value_date"] = (txn_date + timedelta(days=rng.randint(2, 5))).isoformat()

        elif disc == "amount_fee_netted":
            fee = round(amount * rng.uniform(0.015, 0.025), 2)
            led_row["net_amount"] = round(amount - fee, 2)

        elif disc == "id_typo":
            # typo lands on the ledger side only
            led_row["entry_id"] = _typo(txn_id, rng)

        elif disc == "missing_in_bank":
            bank_row = None

        elif disc == "missing_in_ledger":
            led_row = None

        gateway_rows.append(gw_row)
        if bank_row:
            bank_rows.append(bank_row)
        if led_row:
            ledger_rows.append(led_row)

        if disc == "duplicate_gateway":
            dup = dict(gw_row)
            gateway_rows.append(dup)  # gateway fired twice, same id

    _write_csv(out_dir / "payment_gateway.csv", gateway_rows, ["txn_id", "date", "amount", "merchant"])
    _write_csv(out_dir / "bank_statement.csv", bank_rows, ["bank_ref", "value_date", "credit_amount", "narration"])
    _write_csv(out_dir / "internal_ledger.csv", ledger_rows, ["entry_id", "posted_date", "net_amount", "party"])
    _write_csv(out_dir / "ground_truth.csv", ground_truth, ["txn_id", "date", "amount", "merchant", "discrepancy"])

    return ground_truth


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="data")
    args = parser.parse_args()

    gt = generate(args.records, args.seed, Path(args.out))
    from collections import Counter
    counts = Counter(r["discrepancy"] for r in gt)
    print(f"Generated {args.records} ground-truth records into {args.out}/")
    for k, v in counts.items():
        print(f"  {k}: {v}")
