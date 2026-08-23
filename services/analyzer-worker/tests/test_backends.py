"""Correctness checks for the pluggable LLM backends (ADR-0002).

CC-16  LLM_PROVIDER selects the backend by configuration, not code.
CC-17  The Ollama (local) backend reports $0 cost per call.
CC-19  Cost is computed from token usage and recorded (Anthropic path).
Plus:  defensive parsing turns bad model output into a BackendError so the
       pipeline can degrade instead of delivering garbage.
"""

from types import SimpleNamespace

import httpx
import pytest

from app.backends import (
    AnthropicBackend,
    OllamaBackend,
    StubBackend,
    get_backend,
    parse_hypothesis,
)
from app.config import Settings
from app.ports import BackendError

GOOD_JSON = (
    '{"root_cause": "container OOMKilled", "severity": "critical", '
    '"confidence": "high", "next_steps": ["raise memory limit", "check for a leak"]}'
)


# ---- factory (CC-16) --------------------------------------------------------

@pytest.mark.parametrize(
    "provider,cls",
    [("stub", StubBackend), ("anthropic", AnthropicBackend), ("ollama", OllamaBackend)],
)
def test_get_backend_selects_by_config(provider, cls):
    backend = get_backend(Settings(llm_provider=provider))
    assert isinstance(backend, cls)
    assert backend.name == provider


def test_get_backend_rejects_unknown_provider():
    with pytest.raises(ValueError):
        get_backend(Settings(llm_provider="gpt"))


# ---- defensive parsing ------------------------------------------------------

def test_parse_hypothesis_handles_code_fences_and_prose():
    text = "Here is my answer:\n```json\n" + GOOD_JSON + "\n```\nHope that helps."
    h = parse_hypothesis(text)
    assert h.root_cause == "container OOMKilled"
    assert h.next_steps == ["raise memory limit", "check for a leak"]


@pytest.mark.parametrize("bad", ["not json at all", "{}", '{"severity": "critical"}'])
def test_parse_hypothesis_rejects_bad_output(bad):
    with pytest.raises(BackendError):
        parse_hypothesis(bad)


# ---- Anthropic backend via an injected fake client (CC-19) ------------------

def _fake_anthropic(text: str, in_tok: int, out_tok: int, stop_reason="end_turn"):
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason=stop_reason,
    )
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return resp

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client, calls


async def test_anthropic_backend_parses_and_prices():
    client, calls = _fake_anthropic(GOOD_JSON, in_tok=4000, out_tok=400)
    cfg = Settings(price_in_per_mtok=1.0, price_out_per_mtok=5.0)
    backend = AnthropicBackend(cfg, client=client)

    result = await backend.analyze("prompt goes here")

    assert result.hypothesis.root_cause == "container OOMKilled"
    # 4000/1e6*1.0 + 400/1e6*5.0 = 0.004 + 0.002 = 0.006  (~the whitepaper number)
    assert result.cost_usd == pytest.approx(0.006)
    assert len(calls) == 1  # exactly one call
    assert calls[0]["temperature"] == 0  # reproducibility


async def test_anthropic_backend_raises_on_refusal():
    client, _ = _fake_anthropic(GOOD_JSON, 10, 10, stop_reason="refusal")
    backend = AnthropicBackend(Settings(), client=client)
    with pytest.raises(BackendError):
        await backend.analyze("prompt")


# ---- Ollama backend via httpx MockTransport (CC-17) -------------------------

async def test_ollama_backend_is_local_and_free():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "message": {"content": GOOD_JSON},
                "prompt_eval_count": 1234,
                "eval_count": 56,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    backend = OllamaBackend(Settings(), client=client)

    result = await backend.analyze("prompt")

    assert result.cost_usd == 0.0  # zero egress, zero cost
    assert result.input_tokens == 1234
    assert result.hypothesis.severity == "critical"
    await client.aclose()


async def test_stub_backend_is_deterministic_and_free():
    r1 = await StubBackend().analyze("same prompt")
    r2 = await StubBackend().analyze("same prompt")
    assert r1.cost_usd == 0.0
    assert r1.hypothesis == r2.hypothesis
    assert r1.hypothesis.root_cause  # non-empty
