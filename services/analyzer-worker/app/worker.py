"""Redis Streams consumer loop.

Reads the alert stream through a consumer group (at-least-once), hands each alert
to the Analyzer, and acknowledges it. A message that cannot be parsed, or that
fails processing more than `max_delivery_attempts` times, is parked in the
dead-letter stream so it can never wedge the loop (ADR-0003). ingest-api is
completely decoupled from all of this: it only appends to the stream.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as redis
from redis.exceptions import ResponseError

from .analyzer import Analyzer
from .config import Settings, settings
from .models import StreamAlert

logger = logging.getLogger("analyzer-worker")


class Worker:
    def __init__(self, redis_client, analyzer: Analyzer, cfg: Settings = settings) -> None:
        self._redis = redis_client
        self._analyzer = analyzer
        self._cfg = cfg

    async def ensure_group(self) -> None:
        """Create the consumer group idempotently (tolerate BUSYGROUP)."""
        try:
            await self._redis.xgroup_create(
                self._cfg.alerts_stream, self._cfg.consumer_group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run_once(self) -> int:
        """Read and process one batch. Returns the number of messages handled."""
        resp = await self._redis.xreadgroup(
            self._cfg.consumer_group,
            self._cfg.consumer_name,
            {self._cfg.alerts_stream: ">"},
            count=self._cfg.read_count,
            block=self._cfg.block_ms,
        )
        handled = 0
        for _stream, messages in resp or []:
            for msg_id, fields in messages:
                try:
                    await self.process(msg_id, fields)
                except Exception:
                    logger.exception("unhandled error processing %s (will redeliver)", msg_id)
                handled += 1
        return handled

    async def process(self, msg_id: str, fields: dict) -> str:
        """Process one message. Returns a status string (used by tests)."""
        try:
            alert = StreamAlert(**json.loads(fields["payload"]))
        except Exception as exc:  # noqa: BLE001 - any malformed payload is a poison message
            logger.warning("dead-lettering unparseable message %s: %s", msg_id, exc)
            await self._dead_letter(fields, reason=f"parse_error: {exc}")
            await self._ack(msg_id)
            return "dead:parse"

        try:
            await self._analyzer.analyze(alert)
        except Exception as exc:  # noqa: BLE001 - infra failure → bounded retry, then dead-letter
            attempts = int(fields.get("_attempts", "0")) + 1
            if attempts >= self._cfg.max_delivery_attempts:
                logger.error("dead-lettering %s after %d attempts: %s", msg_id, attempts, exc)
                await self._dead_letter(fields, reason=f"max_attempts: {exc}")
                await self._ack(msg_id)
                return "dead:attempts"
            # App-level retry: re-enqueue with an incremented attempt counter,
            # then ack the original so it leaves the pending list.
            await self._redis.xadd(
                self._cfg.alerts_stream,
                {**fields, "_attempts": str(attempts)},
                maxlen=None,
            )
            await self._ack(msg_id)
            return "retried"

        await self._ack(msg_id)
        return "analyzed"

    async def _ack(self, msg_id: str) -> None:
        await self._redis.xack(self._cfg.alerts_stream, self._cfg.consumer_group, msg_id)

    async def _dead_letter(self, fields: dict, reason: str) -> None:
        await self._redis.xadd(
            self._cfg.dead_letter_stream,
            {"payload": fields.get("payload", ""), "reason": reason},
        )

    async def run(self) -> None:  # pragma: no cover - exercised by run_once in tests
        await self.ensure_group()
        logger.info(
            "analyzer-worker up: group=%s consumer=%s stream=%s",
            self._cfg.consumer_group,
            self._cfg.consumer_name,
            self._cfg.alerts_stream,
        )
        while True:
            await self.run_once()


def build_worker(cfg: Settings = settings) -> Worker:  # pragma: no cover - wiring
    """Wire the production adapters together from configuration."""
    from .backends import get_backend
    from .budget import get_budget
    from .collectors import get_collector
    from .dedup import get_deduplicator
    from .notifiers import get_notifier
    from .stores import get_store

    redis_client = redis.from_url(cfg.redis_url, decode_responses=True)
    analyzer = Analyzer(
        collector=get_collector(cfg),
        backend=get_backend(cfg),
        notifier=get_notifier(cfg),
        store=get_store(cfg),
        budget=get_budget(redis_client, cfg),
        llm_timeout_seconds=cfg.llm_timeout_seconds,
        deduplicator=get_deduplicator(redis_client, cfg),
    )
    return Worker(redis_client, analyzer, cfg)


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=settings.log_level)
    # httpx logs the full request URL at INFO, which would print the Telegram bot
    # token into the pod logs. Anyone with `kubectl logs` could then take over the
    # bot, so keep this client quiet regardless of our own log level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    asyncio.run(build_worker().run())


if __name__ == "__main__":  # pragma: no cover
    main()
