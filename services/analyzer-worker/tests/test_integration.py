"""End-to-end: an alert on the stream becomes a delivered incident.

Wires the real Worker and real Analyzer (with stub adapters) through fakeredis,
publishes an alert exactly as ingest-api does, and drives one loop iteration.
This is the whole pipeline in one test:

    stream → consumer group → collect → redact → analyze → persist → deliver → ack
"""

import json

import fakeredis.aioredis
import pytest

from app.analyzer import Analyzer
from app.backends import StubBackend
from app.budget import InMemoryBudget
from app.collectors import get_collector
from app.config import Settings
from app.models import IncidentStatus
from app.notifiers import StubNotifier, format_message
from app.stores import InMemoryStore
from app.worker import Worker


@pytest.fixture
def cfg():
    return Settings(block_ms=50)


def _wire(cfg, budget):
    notifier, store = StubNotifier(), InMemoryStore()
    analyzer = Analyzer(
        collector=get_collector(),
        backend=StubBackend(),
        notifier=notifier,
        store=store,
        budget=budget,
        llm_timeout_seconds=cfg.llm_timeout_seconds,
    )
    return analyzer, notifier, store


async def test_full_pipeline_delivers_hypothesis(cfg, raw_payload):
    rds = fakeredis.aioredis.FakeRedis(decode_responses=True)
    analyzer, notifier, store = _wire(cfg, InMemoryBudget(100.0))
    worker = Worker(rds, analyzer, cfg)

    await worker.ensure_group()
    # exactly what ingest-api enqueues: the alert dict as a JSON "payload" field
    await rds.xadd(cfg.alerts_stream, {"payload": json.dumps(raw_payload)})

    await worker.run_once()

    assert len(store.saved) == 1
    assert len(notifier.sent) == 1
    incident = notifier.sent[0]
    assert incident.status is IncidentStatus.ANALYZED
    assert incident.alertname == "KubePodCrashLooping"
    assert incident.hypothesis is not None
    msg = format_message(incident)
    assert "KubePodCrashLooping" in msg
    assert "Likely cause" in msg
    # message acknowledged — nothing left pending
    pending = await rds.xpending(cfg.alerts_stream, cfg.consumer_group)
    assert pending["pending"] == 0


async def test_full_pipeline_degrades_when_budget_gone(cfg, raw_payload):
    rds = fakeredis.aioredis.FakeRedis(decode_responses=True)
    analyzer, notifier, _ = _wire(cfg, InMemoryBudget(0.0))  # no budget
    worker = Worker(rds, analyzer, cfg)

    await worker.ensure_group()
    await rds.xadd(cfg.alerts_stream, {"payload": json.dumps(raw_payload)})
    await worker.run_once()

    incident = notifier.sent[0]
    assert incident.status is IncidentStatus.BUDGET_EXCEEDED
    # The engineer still gets the raw alert — analysis is an overlay, not a gate.
    msg = format_message(incident)
    assert "KubePodCrashLooping" in msg
    assert "Raw alert only" in msg
