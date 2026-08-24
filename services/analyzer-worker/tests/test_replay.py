"""Correctness checks for the replay / benchmark harness (VISION §6).

CC-26 Every shipped scenario file is well-formed and loads into an alert+context.
CC-27 Replaying a scenario runs the full pipeline and records a timing + cost.
CC-28 The benchmark runs all scenarios and stays within the budget accounting.
"""

from app.config import Settings
from app.models import IncidentStatus
from app.replay import SCENARIOS_DIR, load_scenario, run_all


def test_scenarios_exist_and_load():  # CC-26
    files = sorted(SCENARIOS_DIR.glob("*.json"))
    assert len(files) >= 5
    for path in files:
        name, alert, context = load_scenario(path)
        assert name
        assert alert.alertname
        # each scenario carries at least some context to reason over
        assert context.k8s_events or context.metrics or context.log_lines


async def test_replay_runs_full_pipeline_with_stub():  # CC-27
    incidents = await run_all(SCENARIOS_DIR, Settings(llm_provider="stub"))
    assert len(incidents) >= 5
    for inc in incidents:
        assert inc.status is IncidentStatus.ANALYZED
        assert inc.hypothesis is not None
        assert inc.latency_ms >= 0  # time-to-first-hypothesis recorded
        assert inc.cost_usd == 0.0  # stub backend is free


async def test_replay_respects_budget():  # CC-28
    # With zero budget, every scenario degrades instead of calling the model.
    incidents = await run_all(SCENARIOS_DIR, Settings(llm_provider="stub", daily_budget_usd=0.0))
    assert all(inc.status is IncidentStatus.BUDGET_EXCEEDED for inc in incidents)
