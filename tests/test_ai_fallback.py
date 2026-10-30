import logging

import pytest

from app.ai import providers
from app.core.logging import JsonFormatter, redact


class FakeClient:
    provider, model = "fake", "fake-1"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out, {"tokens_in": 10, "tokens_out": 5}


@pytest.fixture()
def fake(monkeypatch):
    def install(outputs):
        client = FakeClient(outputs)
        monkeypatch.setattr(providers, "get_ai_client", lambda: client)
        return client
    return install


RECAP_TEXT = {"text": "Riya: we agreed to use PayFlow. Action: Sam to update the budget by Friday. Who signs invoices?"}


def test_valid_ai_output_is_validated_and_not_saved(client, fake):
    good = ('```json\n{"summary": "Chose PayFlow.", "decisions": ["Use PayFlow"], "action_items": '
            '[{"title": "Update budget", "owner": "Sam Lee", "due_date": "not a date", "priority": "URGENT", '
            '"confidence": 3}], "open_questions": [], "risks": []}\n```')
    ai = fake([good])
    before = len(client.get("/api/items?meeting_id=3").json())
    res = client.post("/api/meetings/3/recap", json=RECAP_TEXT).json()
    assert res["ai_mode"] == "ai" and res["saved"] is False and ai.calls == 1
    item = res["recap"]["action_items"][0]
    assert item["due_date"] is None and item["priority"] == "medium" and item["confidence"] == 1.0
    assert len(client.get("/api/items?meeting_id=3").json()) == before  # never silently saved


def test_invalid_json_retries_once_then_falls_back(client, fake):
    ai = fake(["not json at all", '{"summary": ""}'])
    res = client.post("/api/meetings/3/recap", json=RECAP_TEXT).json()
    assert ai.calls == 2
    assert res["ai_mode"] == "basic"
    assert res["recap"]["action_items"][0]["owner"] == "Sam Lee"


def test_timeout_falls_back_and_never_crashes(client, fake):
    ai = fake([TimeoutError("slow"), TimeoutError("slow")])
    res = client.post("/api/meetings/2/briefs", json={"person_name": "Daniel Okafor"})
    assert res.status_code == 200 and res.json()["ai_mode"] == "basic" and ai.calls == 2
    assert "Daniel" in res.json()["brief"]["content"]["headline"]


def test_retry_succeeds_on_second_attempt(client, fake):
    fake([ConnectionError("blip"), '{"nudges": []}'])
    res = client.post("/api/meetings/3/nudges").json()
    assert res["ai_mode"] == "ai"
    assert res["nudges"] and all(n["message"] for n in res["nudges"])  # templates fill any gaps


def test_secrets_are_redacted_from_logs():
    assert "sk-ant-abc123456789" not in redact("key=sk-ant-abc123456789")
    assert "abcdefghijkl" not in redact("Authorization: Bearer abcdefghijkl")
    record = logging.LogRecord("t", logging.INFO, "", 0, "using my-secret-value", (), None)
    assert "my-secret-value" not in JsonFormatter(secrets=("my-secret-value",)).format(record)
