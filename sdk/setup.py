from setuptools import setup, find_packages

LONG_DESCRIPTION = """\
aigov — Python SDK for Vigil, the open-source AI governance dashboard.

* One-line LLM call logging with cost + latency tracking
* Eval framework: LLM-as-judge (local), RAG metrics (local with `aigov[evals]`),
  and dashboard-backed eval suites with results stored against the governance
  dashboard
* Synchronous, 2-second timeout, never raises on logging failure

Local-only judge example:

    from aigov.evals import judge
    result = judge(cases, rubric=YAML_RUBRIC)

Dashboard-backed evals (run + store against your Vigil instance):

    from aigov import AIGovLogger
    logger = AIGovLogger(api_key="sk_...", model_id="<uuid>",
                        dashboard_url="https://your-vigil",
                        token="<session JWT>")
    run = logger.evals.run_suite(suite_id, cases=[...])
"""

setup(
    name="aigov",
    version="0.2.0",
    description=(
        "AI Governance SDK — one-line LLM call logging plus evals "
        "(LLM-as-judge, RAG metrics, drift)"
    ),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Amir Aijaz",
    url="https://github.com/amiraijaz/ai-governance-dashboard",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.27",
        "pyyaml>=6.0",
        "anthropic>=0.34",
        "openai>=1.40",
    ],
    extras_require={
        # Heavy deps for local RAG execution. Judge + drift work without these.
        "evals": [
            "ragas>=0.1.21",
            "datasets>=2.21.0",
            "langchain-openai>=0.2.0",
            "langchain-anthropic>=0.2.0",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
    ],
)
