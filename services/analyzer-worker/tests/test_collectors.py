"""Correctness checks for context collectors (ADR-0001 fixed collectors).

CC-20 The K8s-events collector scopes to the involved pod when known.
CC-21 Warning events are surfaced before Normal ones, and output is capped.
CC-22 One dead collector degrades context instead of failing the analysis.
CC-23 Collectors are selected by config, not code.
CC-24 The Prometheus collector runs its fixed queries and formats the series.
CC-25 The Loki collector builds a pod-scoped selector and extracts log lines.
"""

from types import SimpleNamespace

import httpx
import pytest

from app.collectors import (
    AggregateCollector,
    K8sEventsCollector,
    LokiCollector,
    PrometheusCollector,
    StubCollector,
    get_collector,
)
from app.config import Settings
from app.models import StreamAlert


def _event(etype, reason, name, message, count=1, kind="Pod"):
    return SimpleNamespace(
        type=etype,
        reason=reason,
        message=message,
        count=count,
        involved_object=SimpleNamespace(kind=kind, name=name),
    )


class FakeCoreV1:
    def __init__(self, events):
        self._events = events
        self.namespaces_queried = []

    async def list_namespaced_event(self, namespace, **kwargs):
        self.namespaces_queried.append(namespace)
        return SimpleNamespace(items=self._events)


async def test_scopes_to_involved_pod():  # CC-20
    events = [
        _event("Warning", "BackOff", "billing-api-x2j4q", "Back-off restarting"),
        _event("Normal", "Scheduled", "other-pod-abc", "Successfully assigned"),
    ]
    api = FakeCoreV1(events)
    collector = K8sEventsCollector(api=api)
    alert = StreamAlert(labels={"namespace": "demo", "pod": "billing-api-x2j4q"})

    bundle = await collector.collect(alert)

    assert api.namespaces_queried == ["demo"]
    assert len(bundle.k8s_events) == 1
    assert "billing-api-x2j4q" in bundle.k8s_events[0]
    assert "other-pod-abc" not in "".join(bundle.k8s_events)


async def test_warnings_first_and_capped():  # CC-21
    events = [
        _event("Normal", "Pulled", "p", "pulled image"),
        _event("Warning", "OOMKilling", "p", "Killed process", count=3),
        _event("Normal", "Created", "p", "created container"),
    ]
    collector = K8sEventsCollector(api=FakeCoreV1(events), max_events=2)
    bundle = await collector.collect(StreamAlert(labels={"namespace": "demo", "pod": "p"}))

    assert len(bundle.k8s_events) == 2
    assert bundle.k8s_events[0].startswith("Warning OOMKilling")
    assert "x3" in bundle.k8s_events[0]  # repeat count rendered


async def test_namespace_fallback_when_pod_has_no_events():
    events = [_event("Warning", "FailedScheduling", "some-other-pod", "no nodes")]
    collector = K8sEventsCollector(api=FakeCoreV1(events))
    # alert pod has no matching events → fall back to namespace-wide context
    bundle = await collector.collect(StreamAlert(labels={"namespace": "demo", "pod": "ghost"}))
    assert len(bundle.k8s_events) == 1


class BrokenCollector:
    name = "broken"

    async def collect(self, alert):
        raise RuntimeError("datasource unreachable")


async def test_aggregate_tolerates_a_failing_collector():  # CC-22
    agg = AggregateCollector([BrokenCollector(), StubCollector()])
    bundle = await agg.collect(StreamAlert(labels={"alertname": "X", "pod": "p"}))

    assert "broken" in bundle.sources_failed
    assert "stub" in bundle.sources_ok
    assert bundle.k8s_events  # stub still contributed context


def test_get_collector_selects_by_config():  # CC-23
    agg = get_collector(Settings(collectors="stub,k8s-events,prometheus,loki"))
    assert isinstance(agg, AggregateCollector)
    assert len(agg._collectors) == 4
    assert isinstance(agg._collectors[1], K8sEventsCollector)
    assert isinstance(agg._collectors[2], PrometheusCollector)
    assert isinstance(agg._collectors[3], LokiCollector)


def test_get_collector_rejects_unknown():
    with pytest.raises(ValueError):
        get_collector(Settings(collectors="stub,mystery"))


async def test_prometheus_collector_formats_series():  # CC-24
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["query"])
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {
                                "__name__": "kube_pod_container_status_restarts_total",
                                "pod": "billing-api-x2j4q",
                            },
                            "value": [1690000000, "7"],
                        }
                    ],
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://prom")
    collector = PrometheusCollector("http://prom", client=client, queries=('up{pod="%(pod)s"}',))
    bundle = await collector.collect(
        StreamAlert(labels={"namespace": "demo", "pod": "billing-api-x2j4q"})
    )

    assert bundle.metrics == [
        'kube_pod_container_status_restarts_total{pod="billing-api-x2j4q"} = 7'
    ]
    assert seen == ['up{pod="billing-api-x2j4q"}']  # template substituted with the pod
    await client.aclose()


async def test_loki_collector_extracts_lines_and_scopes_to_pod():  # CC-25
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params["query"]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {"pod": "billing-api-x2j4q"},
                            "values": [
                                ["1690000000000000000", "ERROR out of memory: Killed process 1"],
                                ["1690000000000000001", "FATAL restarting"],
                            ],
                        }
                    ],
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://loki")
    collector = LokiCollector("http://loki", client=client, max_lines=10)
    bundle = await collector.collect(
        StreamAlert(labels={"namespace": "demo", "pod": "billing-api-x2j4q"})
    )

    assert "ERROR out of memory: Killed process 1" in bundle.log_lines
    assert len(bundle.log_lines) == 2
    assert 'pod="billing-api-x2j4q"' in captured["query"]  # pod-scoped selector
    assert 'namespace="demo"' in captured["query"]
    await client.aclose()


async def test_loki_respects_line_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        vals = [[str(i), f"line {i}"] for i in range(100)]
        return httpx.Response(
            200, json={"data": {"result": [{"stream": {}, "values": vals}]}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://loki")
    collector = LokiCollector("http://loki", client=client, max_lines=5)
    bundle = await collector.collect(StreamAlert(labels={"namespace": "demo"}))
    assert len(bundle.log_lines) == 5
    await client.aclose()
