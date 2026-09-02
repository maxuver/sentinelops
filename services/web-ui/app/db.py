"""Read side of the incident history.

Read-only by construction: this service issues SELECTs and nothing else. The
analyzer-worker owns the schema and is the only writer.
"""

from __future__ import annotations

from .config import Settings, settings

# Every statement here is a literal string. Filters arrive as bound parameters
# ($1, $2, $3), never interpolated, so a namespace value from the query string
# cannot alter the statement. Written out in full rather than composed from a
# column constant, so no SQL in this file is built at runtime at all.
_LIST = """
SELECT id, alertname, namespace, severity, status, root_cause, confidence,
       blast_radius, evidence, disproof, next_steps, backend, cost_usd,
       latency_ms, failure_reason, created_at
FROM incidents
WHERE ($1::text IS NULL OR namespace = $1)
  AND ($2::text IS NULL OR status = $2)
ORDER BY created_at DESC
LIMIT $3
"""

_NAMESPACES = "SELECT DISTINCT namespace FROM incidents WHERE namespace <> '' ORDER BY 1"

_SUMMARY = """
SELECT status, count(*) AS n, coalesce(sum(cost_usd), 0) AS cost
FROM incidents GROUP BY status
"""


class IncidentReader:
    """Queries the incident history. Inject a pool in tests."""

    def __init__(self, cfg: Settings = settings, pool=None) -> None:
        self._cfg = cfg
        self._pool = pool

    async def _get_pool(self):
        if self._pool is None:  # pragma: no cover - real DB path
            import asyncpg

            self._pool = await asyncpg.create_pool(self._cfg.postgres_dsn)
        return self._pool

    async def list_incidents(
        self, namespace: str | None = None, status: str | None = None
    ) -> list[dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_LIST, namespace or None, status or None, self._cfg.page_size)
        return [dict(r) for r in rows]

    async def namespaces(self) -> list[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_NAMESPACES)
        return [r["namespace"] for r in rows]

    async def summary(self) -> dict:
        """Counts per status plus total spend, for the header strip."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SUMMARY)
        by_status = {r["status"]: r["n"] for r in rows}
        return {
            "by_status": by_status,
            "total": sum(by_status.values()),
            "cost": sum(float(r["cost"]) for r in rows),
        }
