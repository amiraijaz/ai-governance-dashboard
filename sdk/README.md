# aigov

Python SDK for [Vigil](https://github.com/amiraijaz/ai-governance-dashboard), the open-source AI governance dashboard.

## Install

```bash
pip install aigov           # core: logging + judge + drift
pip install aigov[evals]    # adds Ragas + LangChain for local RAG evaluation
```

Core install is dependency-light (`httpx`, `pyyaml`, the official `anthropic` and `openai` SDKs). The `[evals]` extra pulls Ragas and the LangChain wrappers (~150 MB) only when you need to run RAG metrics locally.

## Quick log

```python
from aigov import AIGovLogger

logger = AIGovLogger(
    api_key="sk_...",                       # X-API-Key from the dashboard
    model_id="<uuid-of-registered-model>",
    dashboard_url="https://your-vigil.example.com",
)

response = logger.call(
    provider="anthropic",
    model="claude-haiku-4-5",
    messages=[{"role": "user", "content": "Hello"}],
    user_id="user_123",
)
```

The logger is **synchronous**, has a **2-second timeout**, and **never raises** on a logging failure. Adding it cannot slow down or break the host application.

---

## Evals

Two modes, pick whichever fits your workflow.

### Mode A — local execution

The SDK computes the eval itself and returns the result. No dashboard required.

#### `judge()` — LLM-as-judge against a YAML rubric

```python
from aigov.evals import judge

RUBRIC = """
name: "Support quality"
criteria:
  - name: professional_tone
    description: "Response maintains a professional, courteous tone"
    scale: 5
  - name: factual_accuracy
    description: "Claims are accurate and not fabricated"
    scale: 5
  - name: helpfulness
    description: "Response actually addresses the user's need"
    scale: 5
pass_threshold: 3.5
"""

cases = [
    {"input": "How do I cancel?",
     "output": "Settings → Billing → Cancel. Access continues until period end."},
    {"input": "Refund policy?",
     "output": "Within 14 days, no questions asked."},
]

result = judge(cases, rubric=RUBRIC)
print(result["summary"])
# {'total_cases': 2, 'passed': 2, 'errored': 0, 'pass_rate': 1.0,
#  'criteria_means': {'professional_tone': 4.5, ...}, ...}

for r in result["per_case"]:
    print(r["mean_score"], r["passed"], r["scores"])
```

`judge()` needs only an API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) in the environment. Anthropic is preferred; OpenAI is the fallback. It runs concurrent LLM calls behind a bounded semaphore (default 5) so a 50-case run does not fire 50 simultaneous requests. A single malformed response marks **that case** errored — the rest of the run continues.

#### `rag()` — reference-free RAG metrics

```python
from aigov.evals import rag

cases = [{
    "query": "Where are my invoices?",
    "response": "Billing → Invoices. Download as PDF.",
    "contexts": ["Invoices are listed under Billing → Invoices and download as PDF."],
}]

result = rag(cases, threshold=0.7)
```

`rag()` is a Ragas wrapper computing **faithfulness**, **answer_relevancy**, and **context_precision**. It requires the optional extras:

```bash
pip install aigov[evals]
```

Without them, `rag()` raises a clean `EvalDependenciesNotInstalled` with the install hint. With them, it also needs `OPENAI_API_KEY` (Ragas uses OpenAI embeddings).

#### `drift()` — two-sample drift on a single metric

```python
from aigov.evals import drift

result = drift(
    current=recent_latencies_ms,
    baseline=last_week_latencies_ms,
    pct_threshold=25.0,
)
# {'baseline_mean': 812.4, 'current_mean': 1184.9,
#  'pct_change': 45.9, 'z_score': 3.21, 'drifted': True, ...}
```

Stdlib-only — uses Wilcoxon rank-sum as a `scipy`-free approximation. A signal is flagged only when **both** the effect size and statistical significance cross threshold (the same both-conditions rule as the dashboard detector), so well-instrumented apps don't flag trivially-significant 2 % shifts.

For full **log-backed multi-signal drift** (latency p95, response length, and error rate against your audit logs), use the dashboard suite — see Mode B.

### Mode B — dashboard-backed (recommended for teams)

Eval suites are reusable, run on demand or on a schedule, and store results against your governance dashboard's Evaluations tab. Auth is via the dashboard session JWT (the access_token returned from `/api/auth/login`), not the X-API-Key used for logging.

```python
from aigov import AIGovLogger

logger = AIGovLogger(
    api_key="sk_...",
    model_id="<uuid>",
    dashboard_url="https://your-vigil.example.com",
    token="<session JWT>",        # or set AIGOV_TOKEN in the environment
)

suite = logger.evals.create_suite(
    name="Support quality",
    eval_type="llm_judge",
    config={"rubric": RUBRIC},
)

run = logger.evals.run_suite(suite["id"], cases=cases)
# Poll until terminal.
import time
while True:
    info = logger.evals.get_run(run["run_id"])
    if info["status"] in ("complete", "failed"):
        break
    time.sleep(2)
print(info["summary"])
```

Unlike `logger.call` (which swallows logging failures), dashboard eval calls **raise** on HTTP errors. They are user-driven and silent failure would hide real bugs. Catch `aigov.evals.DashboardError` to handle them.

---

## Errors

All eval errors inherit from `aigov.evals.EvalError`. The specific subclasses:

| | Raised when |
|---|---|
| `EvalDependenciesNotInstalled` | `rag()` called without `aigov[evals]` installed |
| `RubricError` | YAML rubric is malformed or fails structural validation |
| `NoLLMConfigured` | `judge()` / `rag()` called with no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| `DashboardError` | Mode B HTTP call failed (network, 4xx/5xx, or non-JSON body) |

---

MIT licensed. Issues and pull requests at the [main repo](https://github.com/amiraijaz/ai-governance-dashboard).
