"""
psych-evals: Safety evaluation framework for psychiatric AI systems.

Covers two core failure modes:
  1. Hallucinated clinical guidelines (dosages, DSM-5 criteria, protocols)
  2. GDPR Article 9 violations (reproduction or leakage of special-category
     mental health data)

Quickstart:
    from psych_evals.runner import EvalRunner
    from psych_evals.report import EvalReport

    runner = EvalRunner.from_env()
    results = runner.run_all()
    report = EvalReport(results)
    report.print()
    report.save("results/run_001.json")
"""

__version__ = "0.1.0"
__author__ = "psych-evals contributors"
__license__ = "MIT"
