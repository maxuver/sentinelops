"""Correctness checks for the mandatory redactor (ADR-0002).

CC-6  Emails, IPv4, IPv6, bearer tokens, JWTs, AWS keys and secret-shaped
      key=value pairs are all masked.
CC-8  Redaction is idempotent and preserves surrounding structure.
"""

import pytest

from app.models import ContextBundle
from app.redaction import redact, redact_bundle

SECRETS = [
    ("user alice@example.com failed login", "alice@example.com", "[REDACTED_EMAIL]"),
    ("client ip 192.168.10.34 timed out", "192.168.10.34", "[REDACTED_IP]"),
    ("peer 2001:0db8:85a3:0000:0000:8a2e:0370:7334 reset", "2001:0db8", "[REDACTED_IPV6]"),
    ("Authorization: Bearer abcDEF123456ghिJKL", "abcDEF123456", "[REDACTED_TOKEN]"),
    (
        "jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJ",
        "SflKxwRJ",
        "[REDACTED_JWT]",
    ),
    ("key AKIAIOSFODNN7EXAMPLE leaked", "AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_KEY]"),
    ("password=hunter2 in config", "hunter2", "[REDACTED_SECRET]"),
    ("api_key: sk-abc123XYZ mounted", "sk-abc123XYZ", "[REDACTED_SECRET]"),
]


@pytest.mark.parametrize("text,leaked,mask", SECRETS)
def test_secret_is_masked(text, leaked, mask):
    out = redact(text)
    assert leaked not in out, f"raw secret survived redaction: {out!r}"
    assert mask in out


def test_redaction_preserves_surrounding_text():
    out = redact("pod billing-api restarted; contact alice@example.com now")
    assert out.startswith("pod billing-api restarted; contact ")
    assert out.endswith(" now")


def test_redaction_is_idempotent():
    text = "login alice@example.com from 10.0.0.5 token=deadbeefcafe"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_bundle_masks_every_section_and_keeps_source_health():
    bundle = ContextBundle(
        log_lines=["error for bob@corp.io"],
        metrics=["scrape from 10.1.2.3"],
        k8s_events=["pulled by admin@corp.io"],
        sources_ok=["loki"],
        sources_failed=["prometheus"],
    )
    out = redact_bundle(bundle)
    assert "bob@corp.io" not in out.log_lines[0]
    assert "10.1.2.3" not in out.metrics[0]
    assert "admin@corp.io" not in out.k8s_events[0]
    # Source-health metadata names collectors, not payload — passed through as-is.
    assert out.sources_ok == ["loki"]
    assert out.sources_failed == ["prometheus"]
