# SentinelOps

> AI-assisted incident triage for Kubernetes — turns raw alerts into pre-investigated incidents.

[![CI](https://github.com/maxuver/sentinelops/actions/workflows/ci.yml/badge.svg)](https://github.com/maxuver/sentinelops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## The problem

An on-call engineer gets paged at 3 AM with `KubePodCrashLooping`. The alert says **what**
broke — never **why**. The next 10–30 minutes are always the same manual ritual:
`kubectl describe`, pod logs, neighbour logs, metrics for the last hour, cluster events,
"what was deployed yesterday?". That first half-hour of not-knowing is the most expensive
part of every incident: it is pure toil, it scales with the number of alerts (not the
number of real problems), and it burns out the people who carry the pager.

## What SentinelOps does

SentinelOps automates those first minutes. It is an event-driven pipeline that reacts to
every Alertmanager notification, gathers the context an engineer would gather by hand,
and attaches an LLM-generated root-cause hypothesis before a human even opens a laptop.

```
Alertmanager ──webhook──▶ ingest-api ──▶ Redis Stream ──▶ analyzer-worker
                                                              │
                                        ┌─────────────────────┤
                                        ▼                     ▼
                              context collectors        LLM analysis
                            (Loki logs, Prometheus     (root-cause hypothesis,
                             metrics, K8s events)       severity, next steps)
                                        │                     │
                                        └──────────┬──────────┘
                                                   ▼
                                     Postgres (incident history)
                                                   +
                                     Telegram (raw alert instantly,
                                               analysis as follow-up)
```

The engineer receives a **pre-investigated incident** instead of a bare alert.

## Design principles

1. **Human-in-the-loop.** The system recommends; the engineer decides. No
   auto-remediation, ever. The agent prepares context and a hypothesis — the decision
   (and the accountability) stays with a human.
2. **AI is an overlay, not a point of failure.** The raw alert is delivered immediately,
   before any analysis starts. If the LLM is down, slow, or over budget, alert delivery
   is never delayed or dropped. See [ADR-0003](docs/adr/0003-graceful-degradation.md).
3. **Privacy by design.** Logs contain other people's data. Everything is redacted and
   minimized before it reaches an LLM, and a fully local backend (Ollama) is a
   first-class option for data-sovereign setups.
   See [ADR-0002](docs/adr/0002-llm-privacy-and-pluggable-backends.md).
4. **Predictable cost and behaviour.** A deterministic pipeline with one structured LLM
   call per alert — not an open-ended agent loop. Cost per alert is measured in cents
   and known in advance. See [ADR-0001](docs/adr/0001-event-driven-pipeline-over-agent-loop.md).
5. **Everything as code.** Infrastructure (Terraform/EKS), delivery (GitOps/ArgoCD),
   observability (kube-prometheus-stack, Loki) and the services themselves live in this
   repository, with decisions documented as ADRs.

## Status

Early development. Roadmap:

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | `ingest-api`: Alertmanager webhook → Redis Streams | 🚧 in progress |
| 2 | `analyzer-worker`: context collectors + LLM analysis + Telegram | ⬜ |
| 3 | Local platform: kind + kube-prometheus-stack + Loki + fault injection | ⬜ |
| 4 | Terraform: AWS VPC + EKS, ephemeral environments | ⬜ |
| 5 | GitOps: ArgoCD, Helm charts, GitHub Actions CI/CD | ⬜ |
| 6 | Benchmarks: fault-injection library, time-to-first-hypothesis, cost per alert | ⬜ |

## Repository layout

```
services/
  ingest-api/        # FastAPI webhook receiver → Redis Streams
docs/
  VISION.md          # why this project exists, in depth
  adr/               # architecture decision records
docker-compose.yml   # local dev stack
```

## Local development

```bash
docker compose up --build   # redis + ingest-api on :8080
```

Run tests:

```bash
cd services/ingest-api
pip install -r requirements-dev.txt
ruff check app tests && pytest
```

Send a test alert:

```bash
curl -X POST http://localhost:8080/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d @services/ingest-api/tests/fixtures/crashloop.json
```

## License

[MIT](LICENSE)
