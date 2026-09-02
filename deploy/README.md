# Deploying SentinelOps to Kubernetes

Helm chart: [`sentinelops/`](sentinelops). The defaults run **fully offline** on a
local kind cluster: the stub LLM backend (no API key), the Kubernetes-events
collector, and a read-only RBAC ServiceAccount.

## Local cluster (kind)

```bash
# 1. build the service images
docker build services/ingest-api      -t sentinelops/ingest-api:dev
docker build services/analyzer-worker -t sentinelops/analyzer-worker:dev

# 2. side-load them into the kind nodes
kind load docker-image sentinelops/ingest-api:dev      --name sentinelops
kind load docker-image sentinelops/analyzer-worker:dev --name sentinelops

# 3. install
helm upgrade --install so deploy/sentinelops -n sentinelops --create-namespace
kubectl -n sentinelops rollout status deploy/so-analyzer-worker
```

## Smoke test (end to end)

```bash
# a failing pod produces real Warning events for the collector to read
kubectl -n sentinelops run billing-api --image=nginx:tag-does-not-exist

# fire an Alertmanager webhook at ingest-api and watch the worker
kubectl -n sentinelops run alert-sender --image=curlimages/curl --restart=Never --rm -i --command -- \
  curl -s -X POST http://so-ingest-api:8080/webhook/alertmanager -H 'content-type: application/json' \
  -d '{"version":"4","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"KubePodCrashLooping","namespace":"sentinelops","pod":"billing-api","severity":"warning"},"annotations":{"description":"crash looping"},"fingerprint":"deadbeef01"}]}'

kubectl -n sentinelops logs deploy/so-analyzer-worker | tail
# -> incident alert=KubePodCrashLooping status=analyzed backend=stub ...
```

## RBAC (least privilege)

The analyzer's ServiceAccount can only read events, nothing else:

```bash
sa=system:serviceaccount:sentinelops:so-analyzer
kubectl auth can-i list events   --as=$sa -A   # yes
kubectl auth can-i create events --as=$sa -A   # no  (read-only)
kubectl auth can-i list pods     --as=$sa -A   # no  (events only)
```

Set `rbac.clusterWide=false` to restrict reads to the release namespace instead
of cluster-wide.

## Full observability stack (real Prometheus + Loki)

The k8s-events collector needs only the cluster API. To enrich with real metrics
and logs, install a monitoring stack and point the analyzer at it:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f kind/values-monitoring.yaml
helm upgrade --install loki grafana/loki-stack -n monitoring \
  --set promtail.enabled=true

# switch the analyzer to all three collectors, wired to the in-cluster services
helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.collectors='k8s-events\,prometheus\,loki' \
  --set config.prometheusUrl=http://kps-kube-prometheus-stack-prometheus.monitoring:9090 \
  --set config.lokiUrl=http://loki.monitoring:3100
kubectl -n sentinelops rollout restart deploy/so-analyzer-worker
```

Validated on kind: a crash-looping pod produced real BackOff events, real
`kube_pod_container_status_restarts_total` / `container_memory_working_set_bytes`
metrics, and real log lines shipped by Promtail, all collected by the three
collectors and fed to the analyzer.

## Autonomous loop (Alertmanager fires the pipeline)

With the monitoring stack installed, SentinelOps runs with no manual step. A
Prometheus rule fires on a crash-looping pod, Alertmanager routes it to the
ingest-api webhook (routing is in `kind/values-monitoring.yaml`), and the
analyzer produces an incident.

```bash
kubectl apply -f kind/sentinelops-demo-rule.yaml       # fast crash-loop alert
kubectl -n sentinelops run billing-api --image=busybox --command -- \
  sh -c "echo boom; sleep 2; exit 1"

# ~90s later, with no manual curl:
kubectl -n sentinelops logs deploy/so-ingest-api      | grep queued
kubectl -n sentinelops logs deploy/so-analyzer-worker | grep 'incident alert'
```

Validated on kind: pod restarts -> KubePodCrashLoopingFast fires -> Alertmanager
webhook -> `{"queued":1}` -> analyzer incident, end to end.

## Delivery: Slack or Telegram

Both channels render the same content: cause, evidence, the cheapest way to
disprove it, blast radius and next steps.

**Slack** uses an Incoming Webhook, so the only thing to set up is one URL
(api.slack.com → your app → Incoming Webhooks → Add New Webhook to Workspace).
No OAuth app to install, no scopes for a security team to review.

```bash
kubectl -n sentinelops create secret generic so-slack \
  --from-literal=webhook-url='https://hooks.slack.com/services/T.../B.../...'

helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.notifier=slack
```

**Telegram** needs a bot token from @BotFather and the target chat id:

```bash
kubectl -n sentinelops create secret generic so-telegram \
  --from-literal=bot-token='123456:ABC...'

helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.notifier=telegram --set config.telegramChatId=123456789
```

Neither credential ever goes into `values.yaml` or the ConfigMap. A Slack
webhook URL *is* the credential — anyone holding it can post to the channel.

## Real LLM backend

```bash
kubectl -n sentinelops create secret generic so-llm \
  --from-literal=anthropic-api-key=sk-ant-...
helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.llmProvider=anthropic \
  --set config.collectors=k8s-events\,prometheus\,loki
```
