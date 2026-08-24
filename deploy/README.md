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

## Real LLM backend

```bash
kubectl -n sentinelops create secret generic so-llm \
  --from-literal=anthropic-api-key=sk-ant-...
helm upgrade --install so deploy/sentinelops -n sentinelops \
  --set config.llmProvider=anthropic \
  --set config.collectors=k8s-events\,prometheus\,loki
```
