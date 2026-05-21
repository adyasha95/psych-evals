"""
tests/test_runner.py

Unit tests for EvalRunner that do not require live API keys.
All external calls are mocked.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from psych_evals.runner import EvalRunner, ConfigError, EVALS_DIR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_runner(**overrides) -> EvalRunner:
    """Return a minimally configured EvalRunner with a mocked scorer."""
    defaults = {
        "provider": "openai",
        "api_key": "test-key",
        "model": "gpt-4o",
        "judge_api_key": "test-judge-key",
    }
    defaults.update(overrides)
    runner = EvalRunner(**defaults)
    runner.scorer = MagicMock()
    runner.scorer.score.return_value = {
        "passed": True,
        "score": 1.0,
        "reasoning": "Mocked pass.",
        "violations": [],
        "strategy": "hallucination",
    }
    return runner


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

def test_valid_openai_config():
    runner = make_runner(provider="openai", model="gpt-4o")
    assert runner.provider == "openai"
    assert runner.model == "gpt-4o"


def test_valid_anthropic_config():
    runner = make_runner(provider="anthropic", model="claude-3-5-sonnet-20241022")
    assert runner.provider == "anthropic"


def test_valid_endpoint_config():
    runner = make_runner(
        provider="endpoint",
        model=None,
        endpoint="https://api.example.com/v1/chat",
    )
    assert runner.provider == "endpoint"


def test_missing_model_raises_config_error():
    with pytest.raises(ConfigError, match="model name"):
        EvalRunner(provider="openai", api_key="k", model=None)


def test_missing_endpoint_raises_config_error():
    with pytest.raises(ConfigError, match="endpoint URL"):
        EvalRunner(provider="endpoint", api_key="k", model=None, endpoint=None)


def test_unknown_provider_raises_config_error():
    with pytest.raises(ConfigError, match="Unknown provider"):
        EvalRunner(provider="vertexai", api_key="k", model="m")


# ---------------------------------------------------------------------------
# Category loading tests
# ---------------------------------------------------------------------------

def test_list_categories_returns_known_categories():
    runner = make_runner()
    cats = runner.list_categories()
    # At minimum, hallucination and gdpr should exist.
    assert "hallucination" in cats
    assert "gdpr" in cats


def test_load_category_returns_test_cases():
    runner = make_runner()
    data = runner.load_category("hallucination")
    assert data["category"] == "hallucination"
    assert isinstance(data["test_cases"], list)
    assert len(data["test_cases"]) >= 10


def test_load_category_test_cases_have_required_fields():
    runner = make_runner()
    data = runner.load_category("hallucination")
    for tc in data["test_cases"]:
        assert "id" in tc, f"Test case missing 'id': {tc}"
        assert "prompt" in tc, f"Test case missing 'prompt': {tc}"
        assert "pass_criteria" in tc, f"Test case missing 'pass_criteria': {tc}"


def test_load_gdpr_test_cases_have_article_field():
    runner = make_runner()
    data = runner.load_category("gdpr")
    for tc in data["test_cases"]:
        assert "article" in tc, f"GDPR test case missing 'article': {tc}"
        assert "Article 9" in tc["article"], (
            f"GDPR test case does not reference Article 9: {tc['id']}"
        )


def test_load_category_nonexistent_raises():
    runner = make_runner()
    with pytest.raises(FileNotFoundError, match="test_cases.json"):
        runner.load_category("nonexistent_category_xyz")


# ---------------------------------------------------------------------------
# Target query tests (mocked)
# ---------------------------------------------------------------------------

def test_query_openai_returns_text():
    runner = make_runner(provider="openai")
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Lithium therapeutic range is 0.8 to 1.2 mEq/L."

    # OpenAI is imported lazily inside _query_openai, so we patch it at source.
    with patch("openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_response
        with patch.dict("sys.modules", {"openai": MagicMock(OpenAI=MockOpenAI)}):
            result = runner._query_openai("What is the lithium therapeutic range?")

    assert "Lithium" in result or "lithium" in result or "0.8" in result


def test_query_endpoint_parses_response_key():
    runner = make_runner(
        provider="endpoint",
        model=None,
        endpoint="https://api.example.com/v1/chat",
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "This is the answer."}
    mock_resp.raise_for_status = MagicMock()

    with patch("psych_evals.runner.requests.post", return_value=mock_resp):
        result = runner._query_endpoint("Test prompt.")

    assert result == "This is the answer."


def test_query_endpoint_parses_openai_compatible_shape():
    runner = make_runner(
        provider="endpoint",
        model=None,
        endpoint="https://api.example.com/v1/chat",
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "OpenAI format response."}}]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("psych_evals.runner.requests.post", return_value=mock_resp):
        result = runner._query_endpoint("Test prompt.")

    assert result == "OpenAI format response."


# ---------------------------------------------------------------------------
# Run category tests (end-to-end with mocked target)
# ---------------------------------------------------------------------------

def test_run_category_returns_one_result_per_test_case():
    runner = make_runner()

    with patch.object(runner, "query_target", return_value="Mocked response."):
        results = runner.run_category("hallucination")

    cat_data = runner.load_category("hallucination")
    assert len(results) == len(cat_data["test_cases"])


def test_run_category_result_structure():
    runner = make_runner()

    with patch.object(runner, "query_target", return_value="Mocked response."):
        results = runner.run_category("hallucination")

    for r in results:
        assert "test_case" in r
        assert "response" in r
        assert "score" in r
        assert "elapsed_seconds" in r
        assert "error" in r


def test_run_category_error_captured_not_raised():
    runner = make_runner()

    with patch.object(
        runner, "query_target", side_effect=RuntimeError("Connection refused.")
    ):
        results = runner.run_category("hallucination")

    # All results should have errors, none should be unhandled exceptions.
    for r in results:
        assert r["error"] is not None
        assert "Connection refused" in r["error"]


# ---------------------------------------------------------------------------
# run_all tests
# ---------------------------------------------------------------------------

def test_run_all_summary_contains_expected_keys():
    runner = make_runner()

    with patch.object(runner, "query_target", return_value="Mocked response."):
        results = runner.run_all()

    summary = results["summary"]
    for key in ("total", "passed", "failed", "errored", "pass_rate"):
        assert key in summary, f"Summary missing key: {key}"


def test_run_all_pass_rate_between_zero_and_one():
    runner = make_runner()

    with patch.object(runner, "query_target", return_value="Mocked response."):
        results = runner.run_all()

    rate = results["summary"]["pass_rate"]
    assert 0.0 <= rate <= 1.0


def test_run_all_contains_all_categories():
    runner = make_runner()
    available = runner.list_categories()

    with patch.object(runner, "query_target", return_value="Mocked response."):
        results = runner.run_all()

    for cat in available:
        assert cat in results["categories"]
