"""Context collectors — gather what an engineer would gather by hand.

The set of collectors is fixed in code (ADR-0001): the model does not choose what
to fetch at runtime, which is what keeps cost and latency per alert predictable.

This iteration ships:
- StubCollector — deterministic synthetic context, used for tests, replay and the
  offline demo.
- AggregateCollector — runs several collectors, tolerating per-source failure so
  one dead datasource degrades context rather than failing the whole analysis.

Real Loki / Prometheus / Kubernetes-events collectors implement the same
`collect()` port and drop in without touching the pipeline (see ports.Collector).
"""

from __future__ import annotations

import logging

from .models import ContextBundle, StreamAlert
from .ports import Collector

logger = logging.getLogger("analyzer-worker.collectors")


class StubCollector:
    """Deterministic context derived from the alert itself."""

    name = "stub"

    async def collect(self, alert: StreamAlert) -> ContextBundle:
        pod = alert.labels.get("pod", "unknown-pod")
        ns = alert.namespace or "default"
        reason = alert.annotations.get("description", alert.alertname)
        return ContextBundle(
            k8s_events=[
                f"{ns}/{pod}: {reason}",
                f"{ns}/{pod}: Back-off restarting failed container",
            ],
            metrics=[f'container_restarts{{pod="{pod}"}} = 7 over last 10m'],
            log_lines=[
                "ERROR unable to connect to upstream dependency",
                "traceback (most recent call last): ...",
            ],
            sources_ok=[self.name],
        )


class AggregateCollector:
    """Fan out to several collectors; never let one failure sink the rest."""

    def __init__(self, collectors: list[Collector]) -> None:
        self._collectors = collectors

    async def collect(self, alert: StreamAlert) -> ContextBundle:
        merged = ContextBundle()
        for collector in self._collectors:
            name = getattr(collector, "name", collector.__class__.__name__)
            try:
                part = await collector.collect(alert)
            except Exception as exc:  # noqa: BLE001 - one bad source must not fail the analysis
                logger.warning("collector %s failed: %s", name, exc)
                merged.sources_failed.append(name)
                continue
            merged.log_lines.extend(part.log_lines)
            merged.metrics.extend(part.metrics)
            merged.k8s_events.extend(part.k8s_events)
            merged.sources_ok.extend(part.sources_ok or [name])
            merged.sources_failed.extend(part.sources_failed)
        return merged


def get_collector() -> Collector:
    """Default collector for this iteration.

    Wrapped in AggregateCollector so real datasource collectors can be appended
    later without changing the Analyzer.
    """
    return AggregateCollector([StubCollector()])
