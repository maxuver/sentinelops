"""Delivery of a processed incident.

Every incident produces a message, including when analysis failed or the budget
was exhausted — the engineer must always receive the alert essentials, with the
hypothesis as an overlay when present (ADR-0003). Raw-alert-first-on-ingest is a
separate ingest-api responsibility; this notifier guarantees the worker never
swallows an alert even when the model is unavailable.
"""

from __future__ import annotations

from .config import Settings, settings
from .models import Incident, IncidentStatus


def format_message(incident: Incident) -> str:
    lines = [f"🛎  {incident.alert_summary or incident.alertname}"]
    if incident.status is IncidentStatus.ANALYZED and incident.hypothesis:
        h = incident.hypothesis
        lines.append("")
        lines.append(f"🤖 Likely cause ({h.confidence} confidence): {h.root_cause}")
        if h.blast_radius and h.blast_radius != "unknown":
            lines.append(f"Blast radius: {h.blast_radius}")
        if h.evidence:
            lines.append("Evidence:")
            lines.extend(f"  - {e}" for e in h.evidence)
        if h.disproof:
            lines.append(f"Cheapest way to disprove: {h.disproof}")
        if h.next_steps:
            lines.append("Next steps:")
            lines.extend(f"  {i}. {s}" for i, s in enumerate(h.next_steps, 1))
        lines.append(f"— {incident.backend}, {incident.latency_ms} ms, ${incident.cost_usd:.4f}")
    elif incident.status is IncidentStatus.BUDGET_EXCEEDED:
        lines.append("⚠️ AI analysis skipped: daily budget reached. Raw alert only.")
    else:
        lines.append(f"⚠️ AI analysis unavailable ({incident.failure_reason}). Raw alert only.")
    return "\n".join(lines)


class StubNotifier:
    """Records deliveries in memory for tests and offline runs."""

    name = "stub"

    def __init__(self) -> None:
        self.sent: list[Incident] = []

    async def notify(self, incident: Incident) -> None:
        self.sent.append(incident)


class TelegramNotifier:
    """Sends the incident message to a Telegram chat."""

    name = "telegram"

    def __init__(self, cfg: Settings = settings, client=None) -> None:
        self._cfg = cfg
        self._client = client  # inject an httpx.AsyncClient in tests

    async def notify(self, incident: Incident) -> None:
        import httpx

        url = f"https://api.telegram.org/bot{self._cfg.telegram_bot_token}/sendMessage"
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            resp = await client.post(
                url,
                json={"chat_id": self._cfg.telegram_chat_id, "text": format_message(incident)},
            )
            resp.raise_for_status()
        finally:
            if self._client is None:
                await client.aclose()


def get_notifier(cfg: Settings = settings):
    if cfg.notifier.lower() == "telegram":
        return TelegramNotifier(cfg)
    return StubNotifier()
