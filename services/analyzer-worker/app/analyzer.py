"""The analysis orchestrator: one alert in, one incident out.

The straight-line flow encodes the guarantees from the ADRs:

  collect → REDACT → budget check → ONE llm call → persist → notify

- Redaction happens before the prompt is built, on the only path to the model,
  so there is no branch that could hand raw context to the LLM (ADR-0002).
- Exactly one backend call per alert; no agent loop (ADR-0001).
- The call is wrapped in a hard timeout, and any failure — timeout, backend
  error, bad output — is caught: the incident is still recorded and delivered,
  marked, and never retried into a pile-up (ADR-0003).
- If the day's budget is spent, no call is made at all.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .models import Incident, IncidentStatus, StreamAlert
from .ports import Budget, Collector, IncidentStore, LLMBackend, Notifier
from .prompt import build_prompt
from .redaction import redact_bundle

logger = logging.getLogger("analyzer-worker.analyzer")


class Analyzer:
    def __init__(
        self,
        collector: Collector,
        backend: LLMBackend,
        notifier: Notifier,
        store: IncidentStore,
        budget: Budget,
        llm_timeout_seconds: float = 30.0,
    ) -> None:
        self._collector = collector
        self._backend = backend
        self._notifier = notifier
        self._store = store
        self._budget = budget
        self._timeout = llm_timeout_seconds

    async def analyze(self, alert: StreamAlert) -> Incident:
        incident = Incident(
            fingerprint=alert.fingerprint,
            alertname=alert.alertname,
            namespace=alert.namespace,
            severity=alert.severity,
            alert_summary=alert.summary(),
            backend=self._backend.name,
        )

        # Collect and redact BEFORE anything leaves the process.
        raw_context = await self._collector.collect(alert)
        context = redact_bundle(raw_context)

        if not await self._budget.has_budget():
            incident.status = IncidentStatus.BUDGET_EXCEEDED
            logger.warning("daily budget exhausted; skipping LLM for %s", alert.alertname)
            return await self._finish(incident)

        prompt = build_prompt(alert, context)
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._backend.analyze(prompt), timeout=self._timeout
            )
        except (TimeoutError, Exception) as exc:  # noqa: BLE001 - best-effort by design
            reason = "timeout" if isinstance(exc, TimeoutError) else str(exc)
            incident.status = IncidentStatus.ANALYSIS_FAILED
            incident.failure_reason = reason
            incident.latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("analysis failed for %s: %s", alert.alertname, reason)
            return await self._finish(incident)

        await self._budget.add(result.cost_usd)
        incident.status = IncidentStatus.ANALYZED
        incident.hypothesis = result.hypothesis
        incident.cost_usd = result.cost_usd
        incident.input_tokens = result.input_tokens
        incident.output_tokens = result.output_tokens
        incident.latency_ms = int((time.perf_counter() - started) * 1000)
        return await self._finish(incident)

    async def _finish(self, incident: Incident) -> Incident:
        """Persist and deliver. Always reached, on every status."""
        await self._store.save(incident)
        await self._notifier.notify(incident)
        return incident
