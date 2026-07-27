# ADR-0002: Log privacy and pluggable LLM backends

- Status: accepted
- Date: 2026-07-28

## Context

The analyzer sends alert context to an LLM. That context includes application logs,
which routinely contain personal and sensitive data: emails, IP addresses, auth
tokens, request payloads. Sending it to a third-party API is a data-governance
decision — under GDPR the LLM vendor may become a data processor, which many
EU organisations cannot or will not accept.

## Decision

1. **Mandatory redaction layer.** Every context bundle passes through a redactor
   before any LLM call — no bypass path exists in code. Masked: email addresses,
   IPv4/IPv6, bearer/JWT tokens, cloud credential patterns (AWS keys etc.),
   secret-shaped key=value pairs. The redactor is a pure function with its own
   test suite.
2. **Data minimization.** Hard caps on log lines, label sizes and total context
   bytes; only the time window around the alert is collected.
3. **Pluggable backend behind one interface.** `LLM_PROVIDER=anthropic` (cloud,
   best quality) or `LLM_PROVIDER=ollama` (local model in-cluster, zero egress,
   $0 per alert). Selecting a backend is configuration, not code.
4. **Redacted-only persistence.** Postgres stores only what the model saw
   (post-redaction), with a configurable retention TTL.

## Consequences

- A data-sovereign deployment is a first-class configuration, not a fork — a strong
  fit for EU/GDPR environments.
- Redaction slightly degrades context fidelity (a masked token can occasionally be
  the clue). Accepted: triage hypotheses rarely depend on secret values themselves.
- The redactor becomes security-critical code and is tested and benchmarked
  separately.
