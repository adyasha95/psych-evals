"""
cli.py - Command-line interface for psych-evals.

Usage:
    psych-evals                        # run all categories, print to terminal
    psych-evals --category hallucination
    psych-evals --output results/run.json
    psych-evals --list-categories

All target system and judge configuration is read from environment
variables (see .env.example).
"""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="psych-evals",
        description=(
            "Safety evaluation framework for psychiatric AI systems.\n"
            "Tests for hallucinated clinical guidelines and GDPR Article 9 "
            "violations."
        ),
    )
    parser.add_argument(
        "--category",
        metavar="NAME",
        help="Run only this eval category (e.g. hallucination, gdpr).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Save JSON results to this file path.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Print available eval categories and exit.",
    )
    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable colour in terminal output.",
    )

    args = parser.parse_args()

    # Lazy imports so the CLI starts fast even without all deps installed.
    from psych_evals.runner import EvalRunner
    from psych_evals.report import EvalReport

    runner = EvalRunner.from_env()

    if args.list_categories:
        cats = runner.list_categories()
        if cats:
            print("Available eval categories:")
            for c in cats:
                print(f"  {c}")
        else:
            print("No eval categories found in the evals/ directory.")
        sys.exit(0)

    if args.category:
        try:
            cat_results = runner.run_category(args.category)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        results = {
            "summary": _summarise({args.category: cat_results}),
            "categories": {args.category: cat_results},
        }
    else:
        results = runner.run_all()

    report = EvalReport(results)

    if args.no_colour:
        print(report.to_text_summary())
    else:
        report.print()

    if args.output:
        saved = report.save(args.output)
        print(f"\nResults saved to: {saved}")

    # Exit non-zero if any test failed (useful in CI).
    summary = results.get("summary", {})
    if summary.get("failed", 0) > 0:
        sys.exit(1)


def _summarise(categories: dict) -> dict:
    total = passed = failed = errored = 0
    for cat_results in categories.values():
        for r in cat_results:
            total += 1
            if r.get("error"):
                errored += 1
            elif r.get("score") and r["score"].get("passed") is True:
                passed += 1
            elif r.get("score") and r["score"].get("passed") is False:
                failed += 1
            else:
                errored += 1
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "pass_rate": round(passed / total, 3) if total else 0.0,
    }


if __name__ == "__main__":
    main()
