"""Delivery of a processed incident.

Every incident produces a message, including when analysis failed or the budget
was exhausted — the engineer must always receive the alert essentials, with the
hypothesis as an overlay when present (ADR-0003). Raw-alert-first-on-ingest is a
separate ingest-api responsibility; this notifier guarantees the worker never
swallows an alert even when the model is unavailable.

Messages are formatted as Telegram HTML rather than MarkdownV2: MarkdownV2 needs
a dozen characters escaped, and log lines and model output are full of them.
HTML needs only &, < and >, so it is far harder to break with real content.
"""

from __future__ import annotations

from html import escape

from .config import Settings, settings
from .models import Incident, IncidentStatus

_SEVERITY_ICON = {"critical": "🔴", "warning": "🟡", "info": "🔵"}


def _icon(severity: str) -> str:
    return _SEVERITY_ICON.get(severity.lower(), "⚪")


def format_message(incident: Incident) -> str:
    """Render the incident as Telegram-flavoured HTML."""
    head = f"{_icon(incident.severity)} <b>{escape(incident.alertname or 'Alert')}</b>"

    where = " · ".join(
        escape(p)
        for p in (incident.namespace, incident.severity)
        if p and p != "unknown"
    )
    lines = [head]
    if where:
        lines.append(f"<i>{where}</i>")

    if incident.status is IncidentStatus.ANALYZED and incident.hypothesis:
        h = incident.hypothesis
        lines.append("")
        lines.append(f"🤖 <b>Likely cause</b> <i>({escape(h.confidence)} confidence)</i>")
        lines.append(escape(h.root_cause))

        if h.blast_radius and h.blast_radius != "unknown":
            lines.append("")
            lines.append(f"💥 <b>Blast radius:</b> <code>{escape(h.blast_radius)}</code>")

        if h.evidence:
            lines.append("")
            lines.append("📋 <b>Evidence</b>")
            lines.extend(f"• <code>{escape(e)}</code>" for e in h.evidence)

        if h.disproof:
            lines.append("")
            lines.append("🎯 <b>Cheapest way to disprove</b>")
            lines.append(f"<i>{escape(h.disproof)}</i>")

        if h.next_steps:
            lines.append("")
            lines.append("✅ <b>Next steps</b>")
            lines.extend(
                f"{i}. {escape(s)}" for i, s in enumerate(h.next_steps, 1)
            )

        lines.append("")
        lines.append(
            f"<i>⏱ {escape(incident.backend)} · {incident.latency_ms} ms · "
            f"${incident.cost_usd:.4f}</i>"
        )

    elif incident.status is IncidentStatus.BUDGET_EXCEEDED:
        lines.append("")
        lines.append("⚠️ <b>AI analysis skipped</b> — daily budget reached.")
        lines.append("<i>Raw alert delivered as usual.</i>")

    else:
        lines.append("")
        lines.append("⚠️ <b>AI analysis unavailable</b>")
        if incident.failure_reason:
            lines.append(f"<code>{escape(incident.failure_reason[:200])}</code>")
        lines.append("<i>Raw alert delivered as usual.</i>")

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
                json={
                    "chat_id": self._cfg.telegram_chat_id,
                    "text": format_message(incident),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
        finally:
            if self._client is None:
                await client.aclose()


def get_notifier(cfg: Settings = settings):
    if cfg.notifier.lower() == "telegram":
        return TelegramNotifier(cfg)
    return StubNotifier()
