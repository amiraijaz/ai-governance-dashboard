from setuptools import setup, find_packages

setup(
    name="aigov",
    version="0.1.0",
    description="AI Governance SDK — one-line LLM call logging, cost, and safety tracking",
    author="Amir Aijaz",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.27",
        "anthropic>=0.34",
        "openai>=1.40",
    ],
)
