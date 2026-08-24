"""Replay a library of fault-injection scenarios through the real pipeline and
report the benchmark VISION §6 asks for: time-to-first-hypothesis, cost per
alert and the produced root cause — per scenario, reproducibly.

Each scenario file carries the alert plus the exact context bundle a live
cluster would have produced, so a run is deterministic and needs no cluster,
Loki or Prometheus. Only the LLM backend is a live variable — with the stub
backend the harness is offline and free (it proves the harness); point it at a
real backend and the numbers become real.

    python -m app.replay [scenarios_dir]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .analyzer import Analyzer
from .backends import get_backend
from .budget import InMemoryBudget
from .config import Settings, settings
from .models import ContextBundle, Incident, StreamAlert
from .notifiers import StubNotifier
from .stores import InMemoryStore

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class ReplayCollector:
    """Serves the context recorded in a scenario file instead of a live source."""

    name = "replay"

    def __init__(self, context: ContextBundle) -> None:
        self._context = context

    async def collect(self, alert: StreamAlert) -> ContextBundle:
        return self._context


def load_scenario(path: Path) -> tuple[str, StreamAlert, ContextBundle]:
    data = json.loads(path.read_text(encoding="utf-8"))
    alert = StreamAlert(**data["alert"])
    context = ContextBundle(**data.get("context", {}))
    return data.get("name", path.stem), alert, context


async def run_scenario(
    alert: StreamAlert, context: ContextBundle, backend, budget
) -> Incident:
    analyzer = Analyzer(
        collector=ReplayCollector(context),
        backend=backend,
        notifier=StubNotifier(),
        store=InMemoryStore(),
        budget=budget,
        llm_timeout_seconds=settings.llm_timeout_seconds,
    )
    return await analyzer.analyze(alert)


async def run_all(scenarios_dir: Path = SCENARIOS_DIR, cfg: Settings = settings) -> list[Incident]:
    backend = get_backend(cfg)
    budget = InMemoryBudget(cfg.daily_budget_usd)
    results: list[Incident] = []
    for path in sorted(scenarios_dir.glob("*.json")):
        _name, alert, context = load_scenario(path)
        results.append(await run_scenario(alert, context, backend, budget))
    return results


def _print_report(incidents: list[Incident]) -> None:
    header = f"{'scenario':<26} {'status':<16} {'ttfh(ms)':>9} {'cost($)':>10}  root cause"
    print(header)
    print("-" * len(header))
    total_ms = 0
    total_cost = 0.0
    for inc in incidents:
        total_ms += inc.latency_ms
        total_cost += inc.cost_usd
        rc = (inc.hypothesis.root_cause if inc.hypothesis else inc.failure_reason) or ""
        name = inc.alertname[:24]
        print(
            f"{name:<26} {inc.status.value:<16} {inc.latency_ms:>9} "
            f"{inc.cost_usd:>10.6f}  {rc[:60]}"
        )
    n = len(incidents) or 1
    print("-" * len(header))
    print(
        f"{'TOTAL/AVG':<26} {f'{len(incidents)} scenarios':<16} "
        f"{total_ms // n:>9} {total_cost:>10.6f}  backend={settings.llm_provider}"
    )


def main() -> None:  # pragma: no cover - CLI entrypoint
    scenarios_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SCENARIOS_DIR
    incidents = asyncio.run(run_all(scenarios_dir))
    _print_report(incidents)


if __name__ == "__main__":  # pragma: no cover
    main()
