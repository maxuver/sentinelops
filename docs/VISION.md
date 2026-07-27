# SentinelOps — Vision

## 1. The pain

The most expensive part of an incident is not the fix — it is the first 20–30 minutes of
not knowing what is going on. An alert fires; the notification contains a bare
Alertmanager template. The on-call engineer manually assembles context from metrics,
pod/node status, events and recent releases. While that search is running, nobody can
tell the business what happened. Understanding arrives in 10–20 minutes; ten minutes
later the incident is often already fixed — but for the business it looked like 30 lost
minutes. This window is what MTTA (mean time to acknowledge/assess) measures, and it is
the window SentinelOps attacks.

The dashboards are usually excellent. Grafana, runbooks, on-call rotation — all
exemplary. But dashboards help *after* the incident, not *during* it: monitoring knows
**what** is burning; **what it means** is still figured out by a human, by hand, every
single time. That work is repetitive, pattern-shaped, and largely automatable.

There is a second pain: the asymmetry of knowledge. Seniors know how to investigate.
A junior on call either drowns or escalates everything, waking up expensive people.
Bus factor, burnout, churn.

## 2. The solution

SentinelOps automates the first minutes of every incident with an event-driven pipeline:

1. **Alertmanager** fires a webhook on every alert.
2. **ingest-api** validates it and publishes it to a Redis Stream. The raw alert is
   forwarded to Telegram *immediately* — analysis must never delay delivery.
3. **analyzer-worker** consumes the stream and gathers the context an engineer would
   gather by hand: relevant Loki logs, Prometheus metrics around the alert timestamp,
   Kubernetes events and object status.
4. The context bundle is **redacted and minimized**, then sent to an LLM with a
   structured prompt. The output: probable root cause, severity assessment,
   recommended next steps.
5. The hypothesis lands in **Postgres** (incident history — a growing dataset) and in
   **Telegram** as a follow-up to the raw alert.

The engineer receives a pre-investigated incident. What used to take 30 minutes by hand
takes the pipeline seconds.

**Human-in-the-loop by design.** The agent prepares context and a hypothesis; the
decision is made by the engineer — who is also the one held accountable. The system
recommends, never remediates.

## 3. Why now, and industry validation

- LLMs in the Haiku class became cheap enough that analysing *every* alert costs cents.
  A year earlier the economics did not work.
- The pattern is validated by the ecosystem: **k8sgpt** and **HolmesGPT** are CNCF
  Sandbox projects in exactly this niche; cloud providers are embedding alert-triage
  copilots into their own consoles.
- The same architecture is being built in production teams: a July 2026 community talk
  ("teaching AI to dig through metrics while the on-call finishes their tea")
  demonstrated a production deployment of this exact shape — enricher + AI worker on
  top of Alertmanager, Telegram delivery, human decision-making — and its author's
  conclusion was that what took him six months to build is now a matter of days with
  current tooling. The value is in the approach: hand the *confirmation routine* to an
  agent, keep the *decision* with the engineer.

We are not guessing at a trend; we are entering a confirmed one.

## 4. Positioning against prior art

|                        | k8sgpt                  | HolmesGPT                     | SentinelOps                             |
|------------------------|-------------------------|-------------------------------|-----------------------------------------|
| Model of operation     | on-demand cluster scan  | autonomous agent loop         | event-driven: reacts to each alert      |
| Context                | K8s resources           | many toolsets                 | logs + metrics + events around the alert |
| History                | no                      | partially (SaaS)              | Postgres — incident dataset             |
| Cost per alert         | —                       | unpredictable (agent iterates) | deterministic pipeline → predictable    |
| Scope                  | CLI tool                | agent                         | full platform: IaC → GitOps → observability → AI |

The choice of a deterministic pipeline over an agent loop is a deliberate trade-off:
predictable cost, bounded latency, auditable behaviour
([ADR-0001](adr/0001-event-driven-pipeline-over-agent-loop.md)).

## 5. Data privacy (a first-class requirement)

Alert context contains **other people's data**: logs carry emails, IPs, tokens, request
bodies. Shipping that to a third-party cloud API is a data-governance decision, not a
technical detail — under GDPR it can make the LLM vendor a data processor.
SentinelOps treats this as a design constraint, not an afterthought:

- **Redaction before any LLM call** — emails, IP addresses, bearer/JWT tokens, cloud
  credentials and secret-shaped strings are masked in the collector output.
- **Data minimization** — hard caps on log lines and context size; only the window
  around the alert timestamp is collected.
- **Pluggable LLM backend** — `anthropic` (cloud) or `ollama` (fully local). A
  data-sovereign deployment sends nothing outside the cluster and costs $0 per alert.
- **Redacted-only persistence** with a configurable retention TTL.

Details: [ADR-0002](adr/0002-llm-privacy-and-pluggable-backends.md).

## 6. What we measure (success criteria)

A library of fault-injection scenarios (CrashLoopBackOff, OOMKill, DNS failure,
ImagePullBackOff, full PVC, dead dependency) is part of the project. Against it we
measure, reproducibly:

- **Time-to-first-hypothesis** — target < 60 s, vs ~10–30 min of manual triage.
- **Hypothesis quality** per scenario (correct / partially correct / wrong).
- **Cost per analysed alert** in cents, per backend.
- **Degradation behaviour** — raw alert delivery latency with the LLM backend down.

These numbers are the project's résumé: each one can be demonstrated live.

## 7. Non-goals

- **No auto-remediation.** Recommendations only. (The talk cited above put it best:
  the agent drafts, the engineer decides, the engineer gets the reprimand.)
- **Not a k8sgpt/HolmesGPT replacement** — this is an end-to-end platform built to be
  understood and operated by its author, layer by layer, not a product competing for
  installs.
- **No multi-cluster federation** in scope for v1.
