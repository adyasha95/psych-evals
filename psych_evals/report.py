"""
report.py - Result formatting and output for psych-evals.

Takes the structured results dict produced by EvalRunner.run_all()
and renders it as:
  - Rich terminal output (colour-coded pass/fail)
  - JSON file suitable for CI pipelines or audit logs
  - Plain-text summary for non-technical stakeholders

Usage:
    from psych_evals.report import EvalReport

    report = EvalReport(results)
    report.print()
    report.save("results/run_2024_01_15.json")
    summary = report.to_text_summary()
"""

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Colour helpers (graceful fallback if rich is not installed)
# ---------------------------------------------------------------------------

def _try_rich() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_RICH = _try_rich()


def _pass_label(passed: bool | None) -> str:
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    return "ERROR"


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------

class EvalReport:
    """
    Renders and saves eval results produced by EvalRunner.run_all().

    Parameters
    ----------
    results : dict
        The dict returned by EvalRunner.run_all().
    run_id : str | None
        Optional identifier for this run (e.g. a git SHA or timestamp).
        Auto-generated from UTC time if not provided.
    """

    def __init__(
        self,
        results: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        self.results = results
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "run_%Y%m%d_%H%M%S"
        )
        self.generated_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Terminal output
    # ------------------------------------------------------------------

    def print(self) -> None:
        """Print results to the terminal. Uses rich if available."""
        if _HAS_RICH:
            self._print_rich()
        else:
            print(self.to_text_summary())

    def _print_rich(self) -> None:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()
        summary = self.results.get("summary", {})

        console.print()
        console.rule("[bold cyan]psych-evals results[/bold cyan]")
        console.print(f"  Run ID : [dim]{self.run_id}[/dim]")
        console.print(f"  Time   : [dim]{self.generated_at}[/dim]")
        console.print()

        # Summary bar.
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errored = summary.get("errored", 0)
        pass_rate = summary.get("pass_rate", 0.0)

        colour = "green" if pass_rate >= 0.8 else ("yellow" if pass_rate >= 0.5 else "red")
        console.print(
            f"  [{colour}]{passed}/{total} passed[/{colour}]  "
            f"[red]{failed} failed[/red]  "
            f"[yellow]{errored} errored[/yellow]  "
            f"pass rate: [{colour}]{pass_rate:.0%}[/{colour}]"
        )
        console.print()

        for category, cat_results in self.results.get("categories", {}).items():
            cat_pass = sum(
                1 for r in cat_results
                if r.get("score") and r["score"].get("passed") is True
            )
            cat_total = len(cat_results)
            console.print(
                f"[bold]{category.upper()}[/bold]  "
                f"({cat_pass}/{cat_total} passed)"
            )

            table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
            table.add_column("ID", style="dim", width=14)
            table.add_column("Result", width=7)
            table.add_column("Score", width=6)
            table.add_column("Reasoning", no_wrap=False, max_width=60)

            for r in cat_results:
                tc = r["test_case"]
                score_data = r.get("score") or {}
                passed = score_data.get("passed")
                label = _pass_label(passed)
                colour = "green" if passed is True else ("red" if passed is False else "yellow")
                score_str = f"{score_data.get('score', 0.0):.2f}"
                reasoning = score_data.get("reasoning", r.get("error", ""))
                reasoning_wrapped = textwrap.shorten(reasoning, width=120, placeholder="...")

                table.add_row(
                    tc.get("id", "?"),
                    f"[{colour}]{label}[/{colour}]",
                    score_str,
                    reasoning_wrapped,
                )

            console.print(table)

            # Print violations for failed cases.
            for r in cat_results:
                score_data = r.get("score") or {}
                violations = score_data.get("violations", [])
                if violations and score_data.get("passed") is False:
                    tc_id = r["test_case"].get("id", "?")
                    console.print(f"  [red]Violations in {tc_id}:[/red]")
                    for v in violations:
                        console.print(f"    [red]x[/red] {v}")
                    console.print()

        console.rule()
        console.print()

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def to_text_summary(self) -> str:
        """Return a plain-text summary suitable for logs or email."""
        summary = self.results.get("summary", {})
        lines = [
            "=" * 60,
            "psych-evals results",
            f"Run ID : {self.run_id}",
            f"Time   : {self.generated_at}",
            "=" * 60,
            (
                f"TOTAL   : {summary.get('total', 0)}"
                f"  PASSED  : {summary.get('passed', 0)}"
                f"  FAILED  : {summary.get('failed', 0)}"
                f"  ERRORED : {summary.get('errored', 0)}"
            ),
            f"Pass rate: {summary.get('pass_rate', 0.0):.0%}",
            "",
        ]

        for category, cat_results in self.results.get("categories", {}).items():
            lines.append(f"--- {category.upper()} ---")
            for r in cat_results:
                tc = r["test_case"]
                score_data = r.get("score") or {}
                label = _pass_label(score_data.get("passed"))
                score_val = score_data.get("score", 0.0)
                reasoning = score_data.get("reasoning", r.get("error", ""))
                lines.append(
                    f"  [{label}] {tc.get('id', '?')}  "
                    f"score={score_val:.2f}  {reasoning[:100]}"
                )
                for v in score_data.get("violations", []):
                    lines.append(f"         ! {v}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the full results as a serialisable dict."""
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            **self.results,
        }

    def to_json(self, indent: int = 2) -> str:
        """Return the results as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, path: str | Path) -> Path:
        """
        Save the results as a JSON file.

        Creates parent directories if they do not exist.
        Returns the resolved path.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_json(), encoding="utf-8")
        return out.resolve()
