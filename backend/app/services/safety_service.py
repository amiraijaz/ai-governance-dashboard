BLOCKED_TERMS = {"malware", "exploit", "phishing"}


def evaluate_safety(text: str) -> dict:
    lowered = text.lower()
    hits = [term for term in BLOCKED_TERMS if term in lowered]
    score = 1.0 - 0.3 * len(hits)
    return {
        "score": max(score, 0.0),
        "flagged": bool(hits),
        "matches": hits,
    }
