# SentinelOps

**An alert tells you *what* broke. It never tells you *why*.**

SentinelOps automates the first twenty minutes of every Kubernetes incident. It
reacts to an Alertmanager webhook, collects the context an engineer would gather
by hand — Kubernetes events, Prometheus metrics, Loki logs — and returns a ranked
root-cause hypothesis with the evidence behind it, in seconds.

It never acts on your cluster. It recommends; the engineer decides.

---

## What you get

Every incident arrives in Slack or Telegram with:

- **The likely cause**, with a confidence level
- **The evidence** it is based on, so you can check the reasoning in seconds
- **The cheapest observation that would disprove it** — a hypothesis is cheap,
  knowing how to kill it fast is what saves the night
- **Blast radius**, tracked separately so a rare-but-catastrophic cause is never
  buried under a common one
- **Next steps**, and the backend, latency and cost of the analysis

---

## Quickstart

### Option A — Kubernetes (kind), the full pipeline

Needs Docker, `kind`, `kubectl` and `helm`.

```bash
# 1. cluster
kind create cluster --config kind/cluster.yaml

# 2. build and side-load the images
docker build services/ingest-api      -t sentinelops/ingest-api:dev
docker build services/analyzer-worker -t sentinelops/analyzer-worker:dev
kind load docker-image sentinelops/ingest-api:dev      --name sentinelops
kind load docker-image sentinelops/analyzer-worker:dev --name sentinelops

# 3. install (offline defaults: no API key needed)
helm upgrade --install so deploy/sentinelops -n sentinelops --create-namespace
kubectl -n sentinelops rollout status deploy/so-analyzer-worker
```

Break something on purpose and watch it work:

```bash
kubectl -n sentinelops run billing-api --image=busybox --command -- \
  sh -c "echo 'ERROR could not connect to postgres:5432'; sleep 2; exit 1"

kubectl -n sentinelops logs -f deploy/so-analyzer-worker
```

Full deployment guide, including the monitoring stack and the autonomous
Alertmanager loop: [`deploy/README.md`](deploy/README.md).

### Option B — docker compose, no cluster

```bash
docker compose up --build
curl -X POST http://localhost:8080/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d @services/ingest-api/tests/fixtures/crashloop.json
```

### Try it without a cluster at all

Six recorded fault-injection scenarios replay through the real pipeline and
print time-to-first-hypothesis and cost per alert:

```bash
cd services/analyzer-worker
pip install -r requirements-dev.txt
python -m app.replay
```

---

## What you need to provide

| Thing | Why | Required? |
|---|---|---|
| Kubernetes cluster with Alertmanager | the alerts to triage | yes |
| Slack Incoming Webhook **or** Telegram bot token | delivery | yes |
| Prometheus URL | metric context | optional |
| Loki URL | log context | optional |
| An LLM backend | the hypothesis | see below |

**The LLM is your choice, and one option costs nothing.** Run a local model
through Ollama and no data leaves your network — no API key, no per-alert cost.
Point it at Anthropic instead if you prefer cloud quality. Selecting a backend is
one environment variable, never a code change.

```bash
helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.llmProvider=ollama \
  --set config.collectors='k8s-events\,prometheus\,loki' \
  --set config.notifier=slack
```

---

## Design principles

1. **The AI is an overlay, never a dependency.** Ingestion is decoupled behind a
   length-capped Redis Stream, analysis has a hard timeout and a daily budget cap,
   and the raw alert is delivered even when the model is down. Switch SentinelOps
   off and you are back to exactly what you had before.
   ([ADR-0003](docs/adr/0003-graceful-degradation.md))
2. **Your logs never leave without permission.** Non-bypassable PII redaction
   runs before any model call, and a fully local backend means zero egress.
   ([ADR-0002](docs/adr/0002-llm-privacy-and-pluggable-backends.md))
3. **Cost is a line item, not a surprise.** A deterministic pipeline makes exactly
   one structured LLM call per alert, so the price is known before you switch it
   on. ([ADR-0001](docs/adr/0001-event-driven-pipeline-over-agent-loop.md))
4. **It cannot touch production.** The model holds no write-capable tool, every
   integration uses read-only credentials, and model output is never executed —
   so a prompt injection hidden in a log line yields a wrong suggestion in chat,
   not an action in your cluster.
5. **A hypothesis carries its own disproof.**
   ([ADR-0004](docs/adr/0004-hypothesis-evidence-and-blast-radius.md))

---

## Status

| Area | State |
|---|---|
| `ingest-api` — Alertmanager webhook → Redis Streams | ✅ |
| `analyzer-worker` — collectors, redaction, budget, dedup, graceful degradation | ✅ |
| Collectors — Kubernetes events, Prometheus, Loki | ✅ |
| LLM backends — local Ollama, Anthropic, offline stub | ✅ |
| Delivery — Slack, Telegram | ✅ |
| Incident history — Postgres | ✅ |
| Helm chart with least-privilege RBAC, validated end-to-end on kind | ✅ |
| Fault-injection scenarios + replay benchmark | ✅ |
| CI — lint, tests, container build, helm lint, SAST + dependency scan | ✅ |
| Terraform for AWS EKS | ⚠️ `init` and `validate` pass; never applied to real AWS |

### Known limitations

Stated plainly, because you will find them anyway:

- **No web UI.** Incidents arrive in Slack or Telegram and land in Postgres.
- **No authentication or multi-tenancy.** Single team, single cluster.
- **Hypothesis quality is not yet measured on real incidents.** The six shipped
  scenarios are synthetic and their signals are deliberately clear, so they prove
  the pipeline works — they are not an accuracy benchmark.
- **Kubernetes only.** No other alert sources yet.

---

## Repository layout

```
services/
  ingest-api/        FastAPI webhook receiver → Redis Streams
  analyzer-worker/   collectors, redaction, LLM backends, delivery, replay
    scenarios/       recorded fault-injection scenarios
deploy/
  sentinelops/       Helm chart (services, RBAC, Postgres)
infra/terraform/     AWS VPC + EKS (validated, not applied)
kind/                local cluster and monitoring stack config
docs/
  VISION.md          why this project exists, in depth
  adr/               architecture decision records
```

## Development

```bash
cd services/analyzer-worker
pip install -r requirements-dev.txt
ruff check app tests && pytest
```

## License

[MIT](LICENSE)
