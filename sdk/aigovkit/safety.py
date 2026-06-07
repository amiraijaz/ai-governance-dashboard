import httpx


class SafetyChecker:
    def __init__(self, endpoint: str = "http://localhost:8000"):
        self.endpoint = endpoint.rstrip("/")

    def evaluate(self, text: str) -> dict:
        r = httpx.post(f"{self.endpoint}/api/safety/evaluate", json={"text": text}, timeout=10)
        r.raise_for_status()
        return r.json()

    def is_safe(self, text: str, threshold: float = 0.7) -> bool:
        return self.evaluate(text)["score"] >= threshold
