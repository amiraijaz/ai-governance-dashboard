from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_safety_evaluate():
    response = client.post("/api/safety/evaluate", json={"text": "hello world"})
    assert response.status_code == 200
    assert "score" in response.json()
