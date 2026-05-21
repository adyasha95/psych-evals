# SKILL.md: psych-evals

## What this project does

psych-evals is an open-source evaluation framework for psychiatric AI systems.
It runs structured safety tests against any deployed AI system and produces
clear pass/fail results with per-test reasoning.

It covers two failure modes:

1. **Hallucinated clinical guidelines**: The AI invents a medication dose,
   misquotes a DSM-5 criterion, or cites a protocol that does not exist.

2. **GDPR Article 9 violations**: The AI reproduces, leaks, or enables
   re-identification of mental health data in ways that violate EU data
   protection law.

---

## How to run evals

### Against OpenAI or Anthropic directly

```bash
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and JUDGE_API_KEY
psych-evals
```

### Against your own deployed system

```bash
# Edit .env: set TARGET_ENDPOINT and TARGET_ENDPOINT_API_KEY
psych-evals
```

### Run a single category

```bash
psych-evals --category hallucination
psych-evals --category gdpr
```

### Save results to JSON

```bash
psych-evals --output results/run_$(date +%Y%m%d).json
```

### List available categories

```bash
psych-evals --list-categories
```

---

## How to interpret results

Each test case returns:
- `passed: true/false` -- safe or unsafe behaviour detected.
- `score: 0.0 to 1.0` -- 0.7+ passes, below 0.7 fails.
- `reasoning` -- one to three sentences explaining the decision.
- `violations` -- specific issues found (empty on a pass).

A system with a pass rate below 80% should not be deployed with real patients.
A 100% pass rate is a necessary, not sufficient, condition for safety.

---

## How to add a new eval category

Create a new folder under `evals/` with two files:

```
evals/
  your_category_name/
    test_cases.json
    rubric.md
```

### test_cases.json schema

Every test case object must have:

```json
{
  "id": "unique_id_string",
  "category": "your_category_name",
  "prompt": "The text to send to the target system.",
  "pass_criteria": "Plain-English description of what a safe response looks like.",
  "fail_indicators": ["specific phrases or patterns that indicate failure"]
}
```

For hallucination categories, also include:

```json
{
  "ground_truth": {
    "facts": ["verified fact 1", "verified fact 2"],
    "source": "DSM-5 / APA Guideline / FDA label / citation"
  }
}
```

For GDPR categories, also include:

```json
{
  "article": "GDPR Article 9",
  "pii_markers": {
    "names": ["Full Name"],
    "diagnoses": ["diagnosis string"],
    "medications": ["drug name dose"],
    "quasi_identifiers": ["occupation", "location", "age"]
  }
}
```

### rubric.md

Describe the scoring scale (0.0 to 1.0), the pass threshold, what constitutes
a violation, and any instructions for the LLM judge. See `evals/hallucination/rubric.md`
or `evals/gdpr/rubric.md` for examples.

### Scoring routing

The scorer routes by category name prefix:
- Category names starting with `gdpr` use GDPR scoring (rule-based + LLM judge with Article 9 prompt).
- All other category names use hallucination scoring (LLM judge against ground truth).

To add a fully custom scoring strategy, extend `EvalScorer.score()` in
`psych_evals/scorer.py`.

---

## How the framework works (technical summary)

```
EvalRunner.run_all()
  for each category in evals/:
    load test_cases.json and rubric.md
    for each test case:
      send prompt to target system (OpenAI / Anthropic / custom endpoint)
      pass response to EvalScorer.score()
        hallucination: LLM judge compares response to ground_truth facts
        gdpr: regex PII checks + LLM judge evaluates Article 9 compliance
      append result {test_case, response, score, elapsed, error}
  build summary {total, passed, failed, errored, pass_rate}

EvalReport(results)
  .print()        -> rich terminal output with colour-coded pass/fail
  .to_json()      -> JSON string for CI or audit log
  .save(path)     -> write JSON to file
```

---

## Configuration reference

All configuration is via environment variables. See `.env.example` for the
full list. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for target (if using OpenAI mode) | Required |
| `OPENAI_MODEL` | Model to evaluate | `gpt-4o` |
| `ANTHROPIC_API_KEY` | Anthropic API key (if using Anthropic mode) | Optional |
| `TARGET_ENDPOINT` | URL of custom endpoint to evaluate | Optional |
| `TARGET_ENDPOINT_API_KEY` | Bearer token for custom endpoint | Optional |
| `JUDGE_PROVIDER` | Provider for the LLM-as-judge scorer | `openai` |
| `JUDGE_API_KEY` | API key for the judge model | Falls back to target key |
| `JUDGE_MODEL` | Judge model name | `gpt-4o` |
| `TARGET_TIMEOUT` | Seconds before target request times out | `30` |

---

## Design decisions

**Why LLM-as-judge?** Clinical hallucination requires semantic understanding
that regex cannot provide. The judge model compares responses against verified
ground-truth facts and identifies specific deviations. The judge is always a
different, trusted model from the one being evaluated.

**Why rule-based PII checks for GDPR?** Regex catches clear-cut name+diagnosis
reproductions faster and more reliably than an LLM for structured patterns.
The LLM judge then handles subtler violations (quasi-identifiers, re-identification
risk) that rules cannot capture. Both layers are applied and merged.

**Why no score caching?** Each run evaluates the live system. Caching results
would defeat the purpose of testing a deployed endpoint that may change.

**Why exit code 1 on failure?** The CLI is designed to work in CI pipelines.
A non-zero exit on any test failure allows `psych-evals` to gate deployments.

---

## Extending to new modalities

psych-evals currently supports text-in/text-out systems. Planned extensions:

- **Multimodal**: accept image inputs (e.g. patient charts, PHQ-9 scanned forms).
- **Conversation**: run multi-turn dialogues rather than single prompts.
- **Async batch**: run large test suites in parallel with rate-limit handling.

Contributions welcome. See the contributing section in `README.md`.
