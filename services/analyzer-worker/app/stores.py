"""Incident persistence (ADR-0002: redacted-only, retention-bounded).

This iteration ships an in-memory store used by tests and the offline demo. A
Postgres adapter implements the same `save()` port and drops in behind
`get_store()` without touching the pipeline. Only post-redaction data ever
reaches a store, because the Analyzer redacts before building the incident.
"""

from __future__ import annotations

from .config import Settings, settings
from .models import Incident


class InMemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self.saved: list[Incident] = []

    async def save(self, incident: Incident) -> None:
        self.saved.append(incident)


def get_store(cfg: Settings = settings):
    return InMemoryStore()
