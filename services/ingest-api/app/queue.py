import json

import redis.asyncio as redis

from .config import settings


class AlertQueue:
    """Thin wrapper over a Redis Stream used as the alert queue.

    ingest-api only appends (XADD); consumers are the analyzer-worker's
    consumer group. Approximate MAXLEN trimming keeps memory bounded even
    if every consumer is down (ADR-0003).
    """

    def __init__(self, client: redis.Redis | None = None) -> None:
        self._redis = client or redis.from_url(settings.redis_url, decode_responses=True)

    async def publish(self, alert: dict) -> str:
        return await self._redis.xadd(
            settings.alerts_stream,
            {"payload": json.dumps(alert, default=str)},
            maxlen=settings.alerts_stream_maxlen,
            approximate=True,
        )

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def close(self) -> None:
        await self._redis.aclose()
