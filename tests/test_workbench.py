"""Offline workbench integration checks. Fake model calls stay in temp dirs.

These exercise transport/evidence handling. They are never homework records or
evidence that a real model met the specification.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import db
from agent.config import database_scope, db_path
from server.workbench import collect_tool_calls, create_app


@pytest.fixture
def bench(world, tmp_path, monkeypatch):
    monkeypatch.setenv("CARTWHEEL_DB", str(world["db"]))
    monkeypatch.setenv("CARTWHEEL_POLICIES_DIR", str(world["policies"]))
    monkeypatch.setenv("CARTWHEEL_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("server.workbench.load_env", lambda: None)
    records = tmp_path / "hw1-session.jsonl"
    with TestClient(create_app(tmp_path / "state", records)) as client:
        yield client, records, tmp_path / "state"


def new_conversation(client, role="shopper", user_id=1):
    response = client.post("/api/conversations", json={"role": role, "user_id": user_id})
    assert response.status_code == 200
    return response.json()["id"]


def install_fake_model(monkeypatch, calls):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-placeholder")

    async def fake_run(agent, message, **kwargs):
        # Only the user's message reaches the model. Expectations are metadata.
        calls.append((message, str(db_path()), kwargs["context"]))
        assert "PRIVATE EXPECTATION" not in message
        assert "PRIVATE EXPECTATION" not in agent.instructions
        with db.connection() as conn:
            if message == "mutate fixture":
                db.set_order_status(conn, 4127, "cancelled")
            order_status = db.get_order(conn, 4127).status
        items = [
            SimpleNamespace(type="tool_call_item", call_id="call-1", tool_name="get_order",
                            raw_item={"arguments": '{"order_id":4127}'}),
            SimpleNamespace(type="tool_call_output_item", call_id="call-1",
                            output=json.dumps({"ok": True, "status": order_status})),
        ]
        return SimpleNamespace(final_output=f"Offline fixture: {order_status}", new_items=items)

    monkeypatch.setattr("server.workbench.Runner.run", fake_run)


def test_missing_key_stays_honest_and_does_not_write_records(bench):
    client, records, _ = bench
    status = client.get("/api/status").json()
    assert status["data_ready"] is True
    assert status["provider_configured"] is False
    assert status["ready"] is False
    assert status["saved_count"] == 0
    identifier = new_conversation(client)
    response = client.post(f"/api/conversations/{identifier}/messages", json={"message": "Hello", "expected": "Answer"})
    assert response.status_code == 503
    assert not records.exists()
    assert client.get(f"/api/conversations/{identifier}").json()["turns"] == []


def test_demo_identity_is_validated_from_database(bench):
    client, _, _ = bench
    assert client.post("/api/conversations", json={"role": "support", "user_id": 1}).status_code == 403
    identifier = new_conversation(client, "merchant", 9002)
    record = client.get(f"/api/conversations/{identifier}").json()
    assert record["store_id"] == 2
    assert client.post("/api/conversations", json={"role": "merchant", "user_id": 9002, "store_id": 1}).status_code == 422


def test_world_is_isolated_per_conversation_and_expectations_stay_out_of_prompt(bench, monkeypatch, world):
    client, _, _ = bench
    calls = []
    install_fake_model(monkeypatch, calls)
    a, b = new_conversation(client), new_conversation(client)
    before = db_path()
    for identifier, message in [(a, "mutate fixture"), (a, "check again"), (b, "check baseline")]:
        response = client.post(f"/api/conversations/{identifier}/messages", json={"message": message, "expected": "PRIVATE EXPECTATION"})
        assert response.status_code == 200
    assert calls[0][1] == calls[1][1] != calls[2][1]
    assert client.get(f"/api/conversations/{a}").json()["turns"][-1]["response"] == "Offline fixture: cancelled"
    assert client.get(f"/api/conversations/{b}").json()["turns"][-1]["response"] == "Offline fixture: delivered"
    assert db_path() == before
    with db.connection() as conn:
        assert db.get_order(conn, 4127).status == "delivered"


def test_export_requires_human_judgment_is_idempotent_and_preserves_all_turns(bench, monkeypatch):
    client, records, _ = bench
    install_fake_model(monkeypatch, [])
    identifier = new_conversation(client)
    path = f"/api/conversations/{identifier}"
    no_prediction = client.post(path + "/messages", json={"message": "Hello"})
    assert no_prediction.status_code == 422
    for message in ("First question", "Follow-up question"):
        assert client.post(path + "/messages", json={"message": message, "expected": "PRIVATE EXPECTATION"}).status_code == 200
    assert client.post(path + "/save", json={"expected": "Answer"}).status_code == 422
    passing = {"expected": "Use the order lookup", "requirement": "AUTH-1", "met_requirement": True, "problem_source": None}
    assert client.post(path + "/save", json={**passing, "problem_source": "prompt"}).status_code == 422
    assert client.post(path + "/save", json={**passing, "requirement": "MADEUP-1"}).status_code == 422
    for _ in range(2):
        result = client.post(path + "/save", json=passing)
        assert result.status_code == 200
        assert result.json()["saved_count"] == 1
    lines = records.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["request"] == "First question"
    assert len(record["turns"]) == 2
    assert len(record["tool_calls"]) == 2
    assert record["initial_expected"] == "PRIVATE EXPECTATION"
    assert record["met_requirement"] is True
    assert record["tool_calls"][0]["arguments"] == {"order_id": 4127}
    assert record["tool_calls"][0]["result"]["ok"] is True
    assert client.post(path + "/messages", json={"message": "Another"}).status_code == 409
    assert client.get("/api/records/download").text == records.read_text()


def test_model_failure_cannot_be_saved_or_silently_retried(bench, monkeypatch):
    client, records, _ = bench
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-placeholder")

    async def fail(*args, **kwargs):
        raise RuntimeError("Private provider details must not be returned")

    monkeypatch.setattr("server.workbench.Runner.run", fail)
    identifier = new_conversation(client)
    path = f"/api/conversations/{identifier}"
    response = client.post(path + "/messages", json={"message": "Refund", "expected": "Queue"})
    assert response.status_code == 502
    assert "Private provider" not in response.text
    assert client.get(path).json()["failed"] is True
    assert client.post(path + "/messages", json={"message": "Retry"}).status_code == 409
    assert client.post(path + "/save", json={"expected": "Queue", "requirement": "ESC-1", "met_requirement": False, "problem_source": "prompt"}).status_code == 409
    assert not records.exists()


def test_cross_origin_requests_are_rejected(bench):
    client, _, _ = bench
    response = client.post("/api/conversations", headers={"Origin": "https://unrelated.example"}, json={"role": "shopper", "user_id": 1})
    assert response.status_code == 403


def test_database_scope_is_independent_for_async_tasks(tmp_path, monkeypatch):
    baseline = tmp_path / "base.db"
    monkeypatch.setenv("CARTWHEEL_DB", str(baseline))

    async def scoped(path):
        with database_scope(path):
            await asyncio.sleep(0)
            return db_path()

    async def run():
        return await asyncio.gather(scoped(tmp_path / "one.db"), scoped(tmp_path / "two.db"))

    assert asyncio.run(run()) == [tmp_path / "one.db", tmp_path / "two.db"]
    assert db_path() == baseline


def test_tool_evidence_matches_call_ids_instead_of_output_position():
    items = [
        SimpleNamespace(type="tool_call_item", call_id="a", tool_name="one", raw_item={"arguments": "{}"}),
        SimpleNamespace(type="tool_call_item", call_id="b", tool_name="two", raw_item={"arguments": "{}"}),
        SimpleNamespace(type="tool_call_output_item", call_id="b", output='{"answer":2}'),
        SimpleNamespace(type="tool_call_output_item", call_id="a", output='{"answer":1}'),
    ]
    assert [row["result"] for row in collect_tool_calls(items)] == [{"answer": 1}, {"answer": 2}]
