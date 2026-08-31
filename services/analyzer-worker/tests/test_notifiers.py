"""Correctness checks for incident delivery (ADR-0003).

CC-36 An analysed incident renders cause, evidence, disproof, blast radius and
      next steps.
CC-37 Content is HTML-escaped, so a log line or model output containing angle
      brackets cannot break Telegram parsing (or inject markup).
CC-38 Failed and budget-exceeded incidents still produce a message — the
      engineer is never left with nothing.
CC-39 The Telegram call sends parse_mode=HTML to the right chat.
"""

import httpx

from app.config import Settings
from app.models import Hypothesis, Incident, IncidentStatus
from app.notifiers import TelegramNotifier, format_message


def _analyzed():
    return Incident(
        alertname="KubePodCrashLooping",
        namespace="demo",
        severity="critical",
        status=IncidentStatus.ANALYZED,
        hypothesis=Hypothesis(
            root_cause="Container OOMKilled: memory limit reached",
            confidence="high",
            blast_radius="single-pod",
            evidence=["OOMKilling event x3", "memory at limit 512Mi"],
            disproof="Check if memory usage was below the limit at alert time",
            next_steps=["Raise the memory limit", "Check for a leak"],
        ),
        backend="ollama",
        latency_ms=1420,
        cost_usd=0.0,
    )


def test_analyzed_message_has_every_section():  # CC-36
    msg = format_message(_analyzed())
    assert "KubePodCrashLooping" in msg
    assert "Container OOMKilled" in msg
    assert "Blast radius" in msg and "single-pod" in msg
    assert "Evidence" in msg and "OOMKilling event x3" in msg
    assert "Cheapest way to disprove" in msg
    assert "Next steps" in msg and "1. Raise the memory limit" in msg
    assert "ollama" in msg and "1420 ms" in msg
    assert "🔴" in msg  # critical severity icon


def test_content_is_html_escaped():  # CC-37
    inc = _analyzed()
    inc.hypothesis.root_cause = 'crash in <script>alert("x")</script> & handler'
    inc.hypothesis.evidence = ["value < 5 && flag > 2"]
    msg = format_message(inc)

    assert "<script>" not in msg  # raw tag must not survive
    assert "&lt;script&gt;" in msg
    assert "&amp;" in msg
    # our own formatting tags are still present and intact
    assert "<b>" in msg and "<code>" in msg


def test_failed_incident_still_messages_the_engineer():  # CC-38
    inc = Incident(
        alertname="KubePodCrashLooping",
        status=IncidentStatus.ANALYSIS_FAILED,
        failure_reason="timeout",
    )
    msg = format_message(inc)
    assert "KubePodCrashLooping" in msg
    assert "AI analysis unavailable" in msg
    assert "timeout" in msg
    assert "Raw alert delivered" in msg


def test_budget_exceeded_incident_still_messages_the_engineer():  # CC-38
    inc = Incident(alertname="HighErrorRate", status=IncidentStatus.BUDGET_EXCEEDED)
    msg = format_message(inc)
    assert "HighErrorRate" in msg
    assert "budget" in msg.lower()
    assert "Raw alert delivered" in msg


async def test_telegram_sends_html_to_the_configured_chat():  # CC-39
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        assert "/bot" in request.url.path and request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = Settings(telegram_bot_token="123:ABC", telegram_chat_id="999")
    await TelegramNotifier(cfg, client=client).notify(_analyzed())

    assert captured["chat_id"] == "999"
    assert captured["parse_mode"] == "HTML"
    assert "KubePodCrashLooping" in captured["text"]
    await client.aclose()
