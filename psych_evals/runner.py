"""
runner.py - Core evaluation runner for psych-evals.

Responsibilities:
  - Load eval categories from the evals/ directory.
  - Send each test case prompt to the configured target system.
  - Delegate scoring to EvalScorer.
  - Return structured results for EvalReport.

Supported target modes:
  - openai: calls OpenAI chat completions directly.
  - anthropic: calls Anthropic messages directly.
  - endpoint: calls any HTTP endpoint that accepts {"prompt": str}
    and returns {"response": str} (or a compatible format).
"""

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from psych_evals.scorer import EvalScorer


# Root of the repository, resolved relative to this file.
REPO_ROOT = Path(__file__).parent.parent
EVALS_DIR = REPO_ROOT / "evals"


class ConfigError(Exception):
    """Raised when the runner cannot be initialised due to bad config."""


class EvalRunner:
    """
    Runs all eval categories against a target system and returns scored results.

    Parameters
    ----------
    provider : str
        One of "openai", "anthropic", or "endpoint".
    api_key : str
        API key for the chosen provider, or bearer token for a custom endpoint.
    model : str | None
        Model identifier (e.g. "gpt-4o"). Required for openai/anthropic modes.
    endpoint : str | None
        Full URL for the target system. Required in "endpoint" mode.
    judge_provider : str
        Provider for the LLM-as-judge scorer. Defaults to "openai".
    judge_api_key : str | None
        API key for the judge model. Falls back to api_key if not set.
    judge_model : str
        Model for the judge. Defaults to "gpt-4o".
    timeout : int
        Seconds before a target request times out. Defaults to 30.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str | None = None,
        endpoint: str | None = None,
        judge_provider: str = "openai",
        judge_api_key: str | None = None,
        judge_model: str = "gpt-4o",
        timeout: int = 30,
    ) -> None:
        self.provider = provider.lower()
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout

        if self.provider not in {"openai", "anthropic", "endpoint"}:
            raise ConfigError(
                f"Unknown provider '{provider}'. "
                "Choose 'openai', 'anthropic', or 'endpoint'."
            )
        if self.provider in {"openai", "anthropic"} and not model:
            raise ConfigError(
                f"A model name is required when provider is '{provider}'."
            )
        if self.provider == "endpoint" and not endpoint:
            raise ConfigError(
                "An endpoint URL is required when provider is 'endpoint'."
            )

        self.scorer = EvalScorer(
            provider=judge_provider,
            api_key=judge_api_key or api_key,
            model=judge_model,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "EvalRunner":
        """
        Construct an EvalRunner from environment variables.

        Reads from .env if python-dotenv is installed. See .env.example
        for the full list of supported variables.
        """
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass  # dotenv is optional; env vars may be set externally.

        # Determine target provider.
        if os.getenv("TARGET_ENDPOINT"):
            provider = "endpoint"
            api_key = os.getenv("TARGET_ENDPOINT_API_KEY", "")
            model = None
            endpoint = os.getenv("TARGET_ENDPOINT")
        elif os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            provider = "anthropic"
            api_key = os.environ["ANTHROPIC_API_KEY"]
            model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            endpoint = None
        else:
            provider = "openai"
            api_key = os.environ.get("OPENAI_API_KEY", "")
            model = os.getenv("OPENAI_MODEL", "gpt-4o")
            endpoint = None

        judge_provider = os.getenv("JUDGE_PROVIDER", "openai")
        judge_api_key = os.getenv("JUDGE_API_KEY") or api_key
        judge_model = os.getenv("JUDGE_MODEL", "gpt-4o")
        timeout = int(os.getenv("TARGET_TIMEOUT", "30"))

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            judge_provider=judge_provider,
            judge_api_key=judge_api_key,
            judge_model=judge_model,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Target system interface
    # ------------------------------------------------------------------

    def query_target(self, prompt: str) -> str:
        """
        Send a prompt to the configured target system and return the text response.

        Raises RuntimeError if the request fails or returns no content.
        """
        if self.provider == "openai":
            return self._query_openai(prompt)
        elif self.provider == "anthropic":
            return self._query_anthropic(prompt)
        else:
            return self._query_endpoint(prompt)

    def _query_openai(self, prompt: str) -> str:
        """Call the OpenAI chat completions API."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=self.timeout,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty response.")
        return content

    def _query_anthropic(self, prompt: str) -> str:
        """Call the Anthropic messages API."""
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text
        if not content:
            raise RuntimeError("Anthropic returned an empty response.")
        return content

    def _query_endpoint(self, prompt: str) -> str:
        """
        Call a custom HTTP endpoint.

        Expects a POST request with JSON body {"prompt": "<text>"}.
        Accepts responses in these shapes:
          {"response": "<text>"}
          {"text": "<text>"}
          {"content": "<text>"}
          {"choices": [{"message": {"content": "<text>"}}]}  (OpenAI-compatible)
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.post(
                self.endpoint,
                json={"prompt": prompt},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Request to target endpoint failed: {exc}"
            ) from exc

        data = resp.json()

        # Try known response shapes in order.
        for key in ("response", "text", "content"):
            if key in data:
                return str(data[key])

        # OpenAI-compatible shape.
        if "choices" in data and data["choices"]:
            return data["choices"][0].get("message", {}).get("content", "")

        raise RuntimeError(
            f"Cannot parse response from endpoint. Raw response: {data}"
        )

    # ------------------------------------------------------------------
    # Eval loading
    # ------------------------------------------------------------------

    def list_categories(self) -> list[str]:
        """Return the names of all available eval categories."""
        if not EVALS_DIR.exists():
            return []
        return sorted(
            d.name
            for d in EVALS_DIR.iterdir()
            if d.is_dir() and (d / "test_cases.json").exists()
        )

    def load_category(self, category: str) -> dict[str, Any]:
        """
        Load test cases and rubric for a named category.

        Returns a dict with keys "category", "rubric", and "test_cases".
        """
        cat_dir = EVALS_DIR / category
        test_cases_path = cat_dir / "test_cases.json"
        rubric_path = cat_dir / "rubric.md"

        if not test_cases_path.exists():
            raise FileNotFoundError(
                f"No test_cases.json found in evals/{category}/. "
                "Check the category name or create the file."
            )

        with open(test_cases_path, "r", encoding="utf-8") as fh:
            test_cases = json.load(fh)

        rubric = ""
        if rubric_path.exists():
            with open(rubric_path, "r", encoding="utf-8") as fh:
                rubric = fh.read()

        return {
            "category": category,
            "rubric": rubric,
            "test_cases": test_cases,
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_category(self, category: str) -> list[dict[str, Any]]:
        """
        Run all test cases in a single eval category.

        Returns a list of result dicts, one per test case, each containing:
          - test_case: the original test case dict
          - response: the raw text returned by the target system
          - score: the scoring result from EvalScorer
          - elapsed_seconds: time taken for the target request
          - error: error message string if the request failed, else None
        """
        cat_data = self.load_category(category)
        results = []

        for tc in cat_data["test_cases"]:
            result: dict[str, Any] = {
                "test_case": tc,
                "response": None,
                "score": None,
                "elapsed_seconds": None,
                "error": None,
            }

            # Query the target.
            t0 = time.monotonic()
            try:
                response = self.query_target(tc["prompt"])
                result["response"] = response
                result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
            except Exception as exc:  # noqa: BLE001
                result["error"] = str(exc)
                result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
                results.append(result)
                continue

            # Score the response.
            try:
                result["score"] = self.scorer.score(
                    category=category,
                    test_case=tc,
                    response=response,
                    rubric=cat_data["rubric"],
                )
            except Exception as exc:  # noqa: BLE001
                result["score"] = {
                    "passed": None,
                    "reasoning": f"Scoring failed: {exc}",
                    "violations": [],
                }

            results.append(result)

        return results

    def run_all(self) -> dict[str, Any]:
        """
        Run every available eval category and return a combined results dict.

        Shape:
          {
            "summary": {"total": int, "passed": int, "failed": int, ...},
            "categories": {
              "<category>": [<result>, ...]
            }
          }
        """
        categories = self.list_categories()
        if not categories:
            raise RuntimeError(
                f"No eval categories found in {EVALS_DIR}. "
                "Expected at least one subdirectory with test_cases.json."
            )

        all_results: dict[str, list] = {}
        for cat in categories:
            all_results[cat] = self.run_category(cat)

        # Build summary.
        total = passed = failed = errored = 0
        for cat_results in all_results.values():
            for r in cat_results:
                total += 1
                if r["error"]:
                    errored += 1
                elif r["score"] and r["score"].get("passed") is True:
                    passed += 1
                elif r["score"] and r["score"].get("passed") is False:
                    failed += 1
                else:
                    errored += 1

        return {
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "pass_rate": round(passed / total, 3) if total else 0.0,
            },
            "categories": all_results,
        }
