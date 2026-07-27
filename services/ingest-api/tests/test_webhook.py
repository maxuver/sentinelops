import json
from pathlib import Path

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.queue import AlertQueue

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client():
    with TestClient(app) as client:
        # Replace the real Redis connection with an in-memory fake.
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        app.state.queue = AlertQueue(client=fake)
        client.fake_redis = fake
        yield client


@pytest.fixture
def crashloop_payload():
    return json.loads((FIXTURES / "crashloop.json").read_text())


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_with_redis_up(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_webhook_accepts_and_queues_alert(client, crashloop_payload):
    resp = client.post("/webhook/alertmanager", json=crashloop_payload)
    assert resp.status_code == 202
    assert resp.json() == {"queued": 1}

    async def read_stream():
        return await client.fake_redis.xrange(settings.alerts_stream)

    entries = client.portal.call(read_stream)
    assert len(entries) == 1
    _, fields = entries[0]
    stored = json.loads(fields["payload"])
    assert stored["labels"]["alertname"] == "KubePodCrashLooping"
    assert stored["groupKey"] == crashloop_payload["groupKey"]


def test_webhook_rejects_invalid_payload(client):
    resp = client.post("/webhook/alertmanager", json={"not": "an alertmanager payload"})
    assert resp.status_code == 422


def test_webhook_queues_every_alert_in_group(client, crashloop_payload):
    second = json.loads(json.dumps(crashloop_payload["alerts"][0]))
    second["labels"]["pod"] = "billing-api-7f9c6d5b8-zzzzz"
    crashloop_payload["alerts"].append(second)

    resp = client.post("/webhook/alertmanager", json=crashloop_payload)
    assert resp.status_code == 202
    assert resp.json() == {"queued": 2}
