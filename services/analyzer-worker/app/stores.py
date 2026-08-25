"""Incident persistence (ADR-0002: redacted-only, retention-bounded).

Two adapters behind the same `save()` port:

- InMemoryStore: for tests and the offline demo.
- PostgresStore: the incident-history dataset. Only post-redaction data ever
  reaches it, because the Analyzer redacts before it builds the incident.

Selecting one is configuration (SENTINELOPS_STORE), never code.
"""

from __future__ import annotations

from .config import Settings, settings
from .models import Incident

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id             TEXT PRIMARY KEY,
    fingerprint    TEXT,
    alertname      TEXT,
    namespace      TEXT,
    severity       TEXT,
    status         TEXT,
    root_cause     TEXT,
    confidence     TEXT,
    blast_radius   TEXT,
    backend        TEXT,
    cost_usd       DOUBLE PRECISION,
    latency_ms     INTEGER,
    failure_reason TEXT,
    created_at     TIMESTAMPTZ
)
"""

_INSERT = """
INSERT INTO incidents (
    id, fingerprint, alertname, namespace, severity, status,
    root_cause, confidence, blast_radius, backend, cost_usd,
    latency_ms, failure_reason, created_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
ON CONFLICT (id) DO NOTHING
"""


class InMemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self.saved: list[Incident] = []

    async def save(self, incident: Incident) -> None:
        self.saved.append(incident)


class PostgresStore:
    """Persists the redacted incident record to Postgres via asyncpg."""

    name = "postgres"

    def __init__(self, dsn: str, pool=None) -> None:
        self._dsn = dsn
        self._pool = pool  # inject a fake pool in tests
        self._schema_ready = False

    async def _get_pool(self):
        if self._pool is None:  # pragma: no cover - real DB path
            import asyncpg

            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool

    async def save(self, incident: Incident) -> None:
        pool = await self._get_pool()
        h = incident.hypothesis
        async with pool.acquire() as conn:
            if not self._schema_ready:
                await conn.execute(_SCHEMA)
                self._schema_ready = True
            await conn.execute(
                _INSERT,
                incident.id,
                incident.fingerprint,
                incident.alertname,
                incident.namespace,
                incident.severity,
                incident.status.value,
                h.root_cause if h else None,
                h.confidence if h else None,
                h.blast_radius if h else None,
                incident.backend,
                incident.cost_usd,
                incident.latency_ms,
                incident.failure_reason,
                incident.created_at,
            )


def get_store(cfg: Settings = settings):
    if cfg.store.lower() == "postgres":
        return PostgresStore(cfg.postgres_dsn)
    return InMemoryStore()
