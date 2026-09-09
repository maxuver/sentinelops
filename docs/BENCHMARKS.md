# Benchmarks

Measured, reproducible, and reported whether or not the number flatters the
project. A tool that tells you what broke at 3 AM has to be honest about how
often it is wrong.

Last run: 2026-09-09 · model `qwen2.5:7b` via Ollama, CPU only (no GPU) ·
cost $0.00 per alert.

## Method

`python -m app.replay <dir>` replays recorded scenarios through the real
pipeline. Each scenario carries the alert plus the exact context a live cluster
would have produced, so a run is deterministic and needs no cluster.

Grading is by declared keywords, checked **against the stated root cause only**.
Not an LLM judge, so the score is reproducible and anyone can see what counted.

Grading deliberately ignores the evidence list. An earlier version accepted a
keyword appearing anywhere in the hypothesis, and it scored a pass for an answer
whose root cause was the misleading one the scenario was built to punish — the
right word merely appeared in a cited log line. That inflated the hard-set score
from 2/5 to 3/5. The engineer acts on the cause that is stated; if that is wrong,
they go the wrong way regardless of what the evidence contains.

## Results

| Set | Scenarios | Correct | Avg time to hypothesis | Cost |
|---|---|---|---|---|
| Easy — signal stated plainly in the context | 6 | **6/6** | 31.5 s | $0.00 |
| Hard — the obvious signal points the wrong way | 5 | **2/5** | 30.3 s | $0.00 |

### Hard set, case by case

| Scenario | The model said | Verdict |
|---|---|---|
| OOM caused by a sidecar | "Memory pressure due to log-shipper container consuming excessive memory" | ✅ found the real culprit |
| Volume full from an unrotated log | "Log files are filling up the PersistentVolume" | ✅ not fooled by "data grew" |
| CrashLoop from a missing Secret | "failed database connection attempts" | ❌ took the bait |
| DNS failing because of a NetworkPolicy | "DNS resolution failure" | ❌ blamed DNS, missed the policy |
| 5xx caused by a rollout | "Database timeout causing high 5xx error rate" | ❌ blamed the database, missed the deploy |

## What the pattern says

The two passes and the three failures split cleanly:

- **It succeeds when the answer is present in the context as text.** `log-shipper`
  appears in the metrics; `app.log is 8.4GiB` appears in the logs. The model
  reads it and names it.
- **It fails when the answer requires reasoning by elimination.** "The database
  is answering normally, *therefore* the database is not the cause." "CoreDNS is
  healthy, *therefore* something else is blocking resolution." In all three
  failures the disproving evidence was in the context and was not used.

This is a limit of a 7B model on CPU, not of the pipeline. It also says where
the effort belongs next: prompt and context design — asking the model to rule out
the obvious explanation first — rather than more plumbing.

## How to read these numbers

- Real incidents are mostly the easy kind: the signal is there and the cost is
  the twenty minutes of assembling it. That is what this automates.
- On genuinely misleading incidents it is right about half the time, so it is an
  assistant, not an oracle. That is why every hypothesis ships with its evidence
  and the cheapest way to disprove it: checking a wrong answer takes seconds.
- Nothing here has been measured against real production incidents. These
  scenarios were authored for this benchmark, and an author writing their own
  exam is a real limitation.

## Reproduce

```bash
cd services/analyzer-worker
pip install -r requirements-dev.txt

SENTINELOPS_LLM_PROVIDER=ollama \
SENTINELOPS_OLLAMA_MODEL=qwen2.5:7b \
SENTINELOPS_LLM_TIMEOUT_SECONDS=300 \
python -m app.replay scenarios/hard
```

Swap `scenarios/hard` for the default directory to run the easy set. Point
`SENTINELOPS_LLM_PROVIDER` at `anthropic` to compare a cloud model.
