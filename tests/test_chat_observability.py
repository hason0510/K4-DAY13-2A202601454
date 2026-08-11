from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.main import app


REQUIRED_CONTEXT = {
    "correlation_id",
    "user_id_hash",
    "session_id",
    "feature",
    "model",
    "env",
}


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-01",
                "session_id": "session-01",
                "feature": "qa",
                "message": "Explain observability",
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]


def test_chat_propagates_correlation_id_and_scrubs_pii(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    correlation_id = "req-deadbeef"

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-request-id": correlation_id},
            json={
                "user_id": "student@vinuni.edu.vn",
                "session_id": "session-02",
                "feature": "qa",
                "message": "Call 090-123-4567 or use card 4111 1111 1111 1111",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == correlation_id
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.json()["correlation_id"] == correlation_id

    raw_log = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw_log
    assert "090-123-4567" not in raw_log
    assert "4111 1111 1111 1111" not in raw_log

    api_events = [
        event
        for event in map(json.loads, raw_log.splitlines())
        if event.get("service") == "api"
    ]
    assert api_events
    assert all(REQUIRED_CONTEXT <= event.keys() for event in api_events)
    assert all(event["correlation_id"] == correlation_id for event in api_events)
