#!/usr/bin/env python3
"""
Run psych-evals against the configured model and update the README results table.

Published MedQA / USMLE scores are hardcoded per model so the table shows the
domain safety gap between general medical benchmarks and psychiatric-specific
safety scenarios.

Usage:
    python scripts/update_readme.py
    python scripts/update_readme.py --output results/run_$(date +%Y%m%d).json
    python scripts/update_readme.py --dry-run   # print table, skip README write
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Published MedQA (USMLE 4-option) accuracy scores.
# Sources: OpenAI GPT-4 Technical Report (2023); Nori et al. 2023;
#          Anthropic Claude 3 / 3.5 Model Cards (2024).
MEDQA_SCORES: dict[str, tuple[float, str]] = {
    "gpt-4o":                      (90.2, "OpenAI GPT-4 Technical Report (2023)"),
    "gpt-4":                       (90.2, "OpenAI GPT-4 Technical Report (2023)"),
    "gpt-4-turbo":                 (90.2, "OpenAI GPT-4 Technical Report (2023)"),
    "gpt-3.5-turbo":               (57.6, "Nori et al., Can GPT-4 pass USMLE? (2023)"),
    "claude-3-5-sonnet-20241022":  (88.7, "Anthropic Claude 3.5 Sonnet Model Card (2024)"),
    "claude-3-5-haiku-20241022":   (73.7, "Anthropic Claude 3.5 Haiku Model Card (2024)"),
    "claude-3-opus-20240229":      (88.0, "Anthropic Claude 3 Model Card (2024)"),
    "claude-3-sonnet-20240229":    (82.7, "Anthropic Claude 3 Model Card (2024)"),
    "claude-3-haiku-20240307":     (75.2, "Anthropic Claude 3 Model Card (2024)"),
}

README_START = "<!-- BENCHMARK_RESULTS_START -->"
README_END = "<!-- BENCHMARK_RESULTS_END -->"


def _lookup_medqa(model: str) -> tuple[float, str] | None:
    key = model.lower().strip()
    if key in MEDQA_SCORES:
        return MEDQA_SCORES[key]
    for k, v in MEDQA_SCORES.items():
        if key.startswith(k) or k.startswith(key):
            return v
    return None


def _category_pass_rate(cat_results: list) -> float:
    total = len(cat_results)
    if not total:
        return 0.0
    passed = sum(
        1 for r in cat_results
        if r.get("score") and r["score"].get("passed") is True
    )
    return round(passed / total * 100, 1)


def build_table(model: str, results: dict, run_date: str) -> str:
    summary = results["summary"]
    categories = results.get("categories", {})

    overall_pct = round(summary["pass_rate"] * 100, 1)
    hall_pct = _category_pass_rate(categories.get("hallucination", []))
    gdpr_pct = _category_pass_rate(categories.get("gdpr", []))

    medqa = _lookup_medqa(model)
    medqa_pct_str = f"{medqa[0]}%" if medqa else "—"
    medqa_source = medqa[1] if medqa else "see literature"

    gap_row = ""
    if medqa:
        gap = overall_pct - medqa[0]
        sign = "+" if gap >= 0 else ""
        gap_row = (
            f"| Domain safety gap vs MedQA | **{sign}{gap:.1f} pp** "
            f"| psych-evals overall minus MedQA baseline |\n"
        )

    return (
        f"_Last updated: {run_date} · model: `{model}` · "
        f"{summary['total']} test cases · "
        f"{summary['passed']} passed · {summary['failed']} failed_\n"
        "\n"
        "| Benchmark | Score | Notes |\n"
        "|-----------|------:|-------|\n"
        f"| MedQA / USMLE (published) | {medqa_pct_str} "
        f"| General medical knowledge · {medqa_source} |\n"
        f"| psych-evals hallucination | **{hall_pct}%** "
        f"| 12 psychiatric-specific clinical scenarios |\n"
        f"| psych-evals GDPR Article 9 | **{gdpr_pct}%** "
        f"| 12 PII + special-category data scenarios |\n"
        f"| **psych-evals overall** | **{overall_pct}%** "
        f"| {summary['total']} scenarios across both failure modes |\n"
        f"{gap_row}"
    ).rstrip()


def update_readme(table: str) -> None:
    readme = REPO_ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(README_START)}.*?{re.escape(README_END)}", re.DOTALL
    )
    if not pattern.search(content):
        raise ValueError(
            f"README.md is missing the {README_START} / {README_END} markers."
        )
    new_content = pattern.sub(
        f"{README_START}\n{table}\n{README_END}", content
    )
    readme.write_text(new_content, encoding="utf-8")
    print("README.md updated.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run psych-evals and update the README benchmark table."
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Save full JSON results to this path (e.g. results/run_001.json).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the table without writing to README.md.",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    from psych_evals.runner import EvalRunner
    from psych_evals.report import EvalReport

    print("Running psych-evals…")
    runner = EvalRunner.from_env()
    results = runner.run_all()

    report = EvalReport(results)
    report.print()

    model_label = runner.model or "custom-endpoint"
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    table = build_table(model_label, results, run_date)

    if args.dry_run:
        print("\n--- README table preview ---")
        print(table)
        print("--- (dry run: README not written) ---")
    else:
        update_readme(table)

    if args.output:
        saved = report.save(args.output)
        print(f"Results saved to: {saved}")

    if results["summary"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
