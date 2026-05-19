PRICING_PER_1K = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICING_PER_1K.get(model)
    if not rates:
        return 0.0
    return (input_tokens / 1000) * rates["input"] + (output_tokens / 1000) * rates["output"]


def summarize_cost() -> dict:
    return {"total_usd": 0.0, "by_model": {}, "by_day": []}
