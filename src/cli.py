import argparse
import csv
from pathlib import Path

from .generate_data import generate
from .reconcile import run_reconciliation
from .report import write_reports
from .adjudicator import get_adjudicator


def main():
    parser = argparse.ArgumentParser(description="Multi-source reconciliation agent")
    parser.add_argument("--records", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--report-dir", type=str, default="reports")
    parser.add_argument("--adjudicator", choices=["mock", "ollama"], default="mock")
    parser.add_argument("--model", type=str, default="llama3.2")
    parser.add_argument("--skip-generate", action="store_true", help="reuse existing data/ instead of regenerating")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    report_dir = Path(args.report_dir)

    if args.skip_generate:
        gt_path = data_dir / "ground_truth.csv"
        ground_truth = list(csv.DictReader(open(gt_path, encoding="utf-8"))) if gt_path.exists() else None
    else:
        ground_truth = generate(args.records, args.seed, data_dir)

    adjudicator = get_adjudicator(args.adjudicator, args.model)

    print(f"Running reconciliation with adjudicator={args.adjudicator} ...")
    result = run_reconciliation(data_dir, adjudicator)

    write_reports(result, report_dir, ground_truth)

    print(f"\nMatch rate: {result['match_rate']:.1%}")
    print(f"Exceptions: {len(result['exceptions'])}")
    print(f"Reports written to {report_dir}/report.md")


if __name__ == "__main__":
    main()
