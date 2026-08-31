"""Correctness checks for alert deduplication.

CC-31 The first alert of a fingerprint is analysed; repeats inside the window
      are suppressed.
CC-32 Different fingerprints are never confused with each other.
CC-33 An alert without a fingerprint still deduplicates, via its labels.
CC-34 Redis suppression is atomic, so only one replica analyses a given alert.
CC-35 A suppressed duplicate costs nothing: no collector call, no LLM call, and
      the engineer is not messaged again.
"""

import fakeredis.aioredis

from app.analyzer import Analyzer
from app.budget import InMemoryBudget
from app.config import Settings
from app.dedup import InMemoryDeduplicator, RedisDeduplicator, alert_key, get_deduplicator
from app.models import IncidentStatus, StreamAlert
from app.notifiers import StubNotifier
from app.stores import InMemoryStore


def _alert(fp="fp-1", pod="billing-api"):
    return StreamAlert(
        fingerprint=fp,
        labels={"alertname": "KubePodCrashLooping", "namespace": "demo", "pod": pod},
    )


async def test_first_seen_then_suppressed():  # CC-31
    d = InMemoryDeduplicator(window_seconds=3600)
    assert await d.is_duplicate(_alert()) is False  # first wins
    assert await d.is_duplicate(_alert()) is True  # repeat suppressed
    assert await d.is_duplicate(_alert()) is True


async def test_different_fingerprints_are_independent():  # CC-32
    d = InMemoryDeduplicator(window_seconds=3600)
    assert await d.is_duplicate(_alert(fp="fp-a")) is False
    assert await d.is_duplicate(_alert(fp="fp-b")) is False  # not confused with fp-a


async def test_window_expiry_allows_reanalysis():
    d = InMemoryDeduplicator(window_seconds=0)  # window already elapsed
    assert await d.is_duplicate(_alert()) is False
    assert await d.is_duplicate(_alert()) is False  # eligible again


async def test_missing_fingerprint_falls_back_to_labels():  # CC-33
    d = InMemoryDeduplicator(window_seconds=3600)
    assert await d.is_duplicate(_alert(fp="")) is False
    assert await d.is_duplicate(_alert(fp="")) is True  # same labels -> duplicate
    assert await d.is_duplicate(_alert(fp="", pod="other-pod")) is False  # different pod


def test_fallback_key_is_distinct_from_fingerprint_key():
    assert alert_key(_alert(fp="")) != alert_key(_alert(fp="fp-1"))
    assert "fallback" in alert_key(_alert(fp=""))


async def test_redis_dedup_is_atomic_across_replicas():  # CC-34
    rds = fakeredis.aioredis.FakeRedis(decode_responses=True)
    replica_a = RedisDeduplicator(rds, window_seconds=3600)
    replica_b = RedisDeduplicator(rds, window_seconds=3600)

    assert await replica_a.is_duplicate(_alert()) is False  # A wins the race
    assert await replica_b.is_duplicate(_alert()) is True  # B must stand down


def test_factory_picks_redis_when_available():
    rds = fakeredis.aioredis.FakeRedis(decode_responses=True)
    assert isinstance(get_deduplicator(rds, Settings()), RedisDeduplicator)
    assert isinstance(get_deduplicator(None, Settings()), InMemoryDeduplicator)


class CountingCollector:
    name = "counting"

    def __init__(self):
        self.calls = 0

    async def collect(self, alert):
        from app.models import ContextBundle

        self.calls += 1
        return ContextBundle(k8s_events=["something happened"])


class CountingBackend:
    name = "counting"

    def __init__(self):
        self.calls = 0

    async def analyze(self, prompt):
        from app.models import Hypothesis, LLMResult

        self.calls += 1
        return LLMResult(hypothesis=Hypothesis(root_cause="x"), cost_usd=0.006)


async def test_duplicate_costs_nothing_and_does_not_renotify():  # CC-35
    collector, backend, notifier = CountingCollector(), CountingBackend(), StubNotifier()
    az = Analyzer(
        collector=collector,
        backend=backend,
        notifier=notifier,
        store=InMemoryStore(),
        budget=InMemoryBudget(cap_usd=100.0),
        deduplicator=InMemoryDeduplicator(window_seconds=3600),
    )

    first = await az.analyze(_alert())
    second = await az.analyze(_alert())

    assert first.status is IncidentStatus.ANALYZED
    assert second.status is IncidentStatus.DUPLICATE_SUPPRESSED
    assert collector.calls == 1  # no context gathered for the duplicate
    assert backend.calls == 1  # no second LLM call, so no second charge
    assert len(notifier.sent) == 1  # engineer messaged once, not twice


async def test_analyzer_without_deduplicator_still_works():
    """Deduplication is optional; omitting it must not change behaviour."""
    az = Analyzer(
        collector=CountingCollector(),
        backend=CountingBackend(),
        notifier=StubNotifier(),
        store=InMemoryStore(),
        budget=InMemoryBudget(cap_usd=100.0),
    )
    assert (await az.analyze(_alert())).status is IncidentStatus.ANALYZED
    assert (await az.analyze(_alert())).status is IncidentStatus.ANALYZED
