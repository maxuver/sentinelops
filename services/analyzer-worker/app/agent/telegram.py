"""The Telegram front of the agent: long polling, an allow-list, a few commands.

Raw Bot API over httpx, like the notifier, rather than a framework: the
surface is small and it keeps the image's dependency set unchanged.

Only chats listed in SENTINELOPS_TELEGRAM_CHAT_ID are served. Anyone else who
finds the bot gets silence, not cluster events: the tools are read-only, but
read-only on someone else's cluster is still a leak.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from html import escape
from typing import Any

from ..config import Settings
from . import report
from .chat import ChatBackend
from .loop import Agent
from .memory import Memory

logger = logging.getLogger("sentinelops.agent.telegram")

HELP = (
    "I am the SentinelOps agent for this cluster. I only observe; I cannot change anything.\n\n"
    "Ask me in plain words, for example:\n"
    "  why did billing-api crash?\n"
    "  what changed in payments in the last 6 hours?\n"
    "  has this happened before?\n\n"
    "Commands:\n"
    "  /report [days]        incident review for the last N days (default 7)\n"
    "  /ok <id> [note]       the hypothesis for incident #id was right\n"
    "  /wrong <id> <cause>   it was wrong; record the real cause so I remember\n"
    "  /index                re-index runbooks and incidents into memory\n"
    "  /status               what I can reach right now\n"
    "  /help                 this text"
)

MAX_MESSAGE = 3_900  # Telegram caps at 4096; leave room for tags
HISTORY_TURNS = 3  # user+assistant pairs kept per chat for follow-up questions


@dataclass
class Reply:
    text: str
    mono: bool = False  # render in <pre>: reports have aligned columns and a sparkline


class TelegramBot:
    def __init__(
        self,
        cfg: Settings,
        agent: Agent,
        chat_backend: ChatBackend,
        memory: Memory | None,
        pool: Any,
        client=None,
        runbooks_dir: str = "",
    ) -> None:
        self._cfg = cfg
        self._agent = agent
        self._chat = chat_backend
        self._memory = memory
        self._pool = pool
        self._client = client
        self._runbooks_dir = runbooks_dir
        self._allowed = {c.strip() for c in cfg.telegram_chat_id.split(",") if c.strip()}
        self._history: dict[str, list[dict]] = {}
        self._offset = 0

    # --- transport -----------------------------------------------------------

    def _api(self):
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"https://api.telegram.org/bot{self._cfg.telegram_bot_token}",
                timeout=60.0,
            )
        return self._client

    async def _send(self, chat_id: str, reply: Reply) -> None:
        api = self._api()
        text = reply.text
        for i in range(0, max(1, len(text)), MAX_MESSAGE):
            chunk = text[i : i + MAX_MESSAGE]
            html = f"<pre>{escape(chunk)}</pre>" if reply.mono else escape(chunk)
            resp = await api.post(
                "/sendMessage",
                json={"chat_id": chat_id, "text": html, "parse_mode": "HTML"},
            )
            if resp.status_code != 200:  # fall back to plain text rather than lose the answer
                await api.post("/sendMessage", json={"chat_id": chat_id, "text": chunk})

    async def _typing(self, chat_id: str) -> None:
        try:
            await self._api().post("/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
        except Exception as exc:  # noqa: BLE001 - cosmetic; the answer still arrives
            logger.debug("typing indicator failed: %s", exc)

    async def run(self) -> None:
        """Long-poll forever. Each update is handled in turn; errors are logged, never fatal."""
        logger.info("agent bot polling; allowed chats: %s", sorted(self._allowed) or "NONE")
        api = self._api()
        while True:
            try:
                resp = await api.get(
                    "/getUpdates",
                    params={"offset": self._offset, "timeout": 30, "allowed_updates": '["message"]'},
                )
                resp.raise_for_status()
                for update in resp.json().get("result", []):
                    self._offset = int(update["update_id"]) + 1
                    await self.handle(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep polling through transient failures
                logger.warning("polling error: %s", exc)
                await asyncio.sleep(3)

    # --- dispatch ------------------------------------------------------------

    async def handle(self, update: dict) -> Reply | None:
        """Handle one update; returns the reply (also sent), for tests."""
        msg = update.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return None
        if chat_id not in self._allowed:
            logger.info("ignored message from chat %s (not allow-listed)", chat_id)
            return None
        await self._typing(chat_id)
        try:
            reply = await self.dispatch(chat_id, text)
        except Exception as exc:
            logger.exception("handling failed")
            reply = Reply(f"Something went wrong: {exc}")
        await self._send(chat_id, reply)
        return reply

    async def dispatch(self, chat_id: str, text: str) -> Reply:
        cmd, _, rest = text.partition(" ")
        cmd = cmd.split("@", 1)[0].lower()  # "/report@MyBot" in groups
        rest = rest.strip()

        if cmd in ("/start", "/help"):
            return Reply(HELP)
        if cmd == "/status":
            return Reply(self._status())
        if cmd == "/report":
            return Reply(await self._report(rest), mono=True)
        if cmd in ("/ok", "/wrong"):
            return Reply(await self._feedback(cmd, rest))
        if cmd == "/index":
            return Reply(await self._index())
        if cmd.startswith("/"):
            return Reply(f"Unknown command {cmd}. /help lists what I can do.")
        return Reply(await self._ask(chat_id, text))

    # --- handlers ------------------------------------------------------------

    def _status(self) -> str:
        mem = "on" if self._memory and self._memory.available else "off"
        return (
            f"model: {self._chat.name} "
            f"({self._cfg.openai_model if self._chat.name == 'openai' else self._cfg.ollama_model})\n"
            f"incident history: {'on' if self._pool is not None else 'off (store is not postgres)'}\n"
            f"memory (pgvector): {mem}\n"
            f"tools: read-only only; max {self._cfg.agent_max_tool_calls} calls, "
            f"{self._cfg.agent_timeout_seconds:.0f}s per question"
        )

    async def _ask(self, chat_id: str, question: str) -> str:
        if self._memory and self._memory.available:
            try:
                await self._memory.index_incidents()  # pick up anything new since last time
            except Exception as exc:  # noqa: BLE001 - memory is optional
                logger.warning("index before ask failed: %s", exc)
        history = self._history.setdefault(chat_id, [])
        answer = await self._agent.ask(question, history)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer.text})
        del history[: -2 * HISTORY_TURNS]
        footer = f"{answer.latency_ms / 1000:.1f}s"
        if answer.tool_calls:
            footer += " · " + ", ".join(answer.tool_calls)
        if answer.cost_usd:
            footer += f" · ${answer.cost_usd:.4f}"
        if answer.truncated:
            footer += " · stopped at the tool-call limit"
        return f"{answer.text}\n\n— {footer}"

    async def _report(self, arg: str) -> str:
        if self._pool is None:
            return "No incident history: the store is not postgres."
        days = int(arg) if arg.isdigit() else 7
        data = await report.collect(self._pool, days=days)
        body = report.render(data)
        closing = await report.narrative(self._chat, data)
        return f"{body}\n\n{closing}" if closing else body

    async def _feedback(self, cmd: str, rest: str) -> str:
        if self._memory is None:
            return "No incident history: the store is not postgres."
        incident_id, _, note = rest.partition(" ")
        if not incident_id:
            return f"Usage: {cmd} <id> {'[note]' if cmd == '/ok' else '<real cause>'}"
        verdict = "correct" if cmd == "/ok" else "wrong"
        if verdict == "wrong" and not note.strip():
            return "Tell me the real cause so I can remember it: /wrong <id> <cause>"
        full = await self._memory.record_feedback(incident_id, verdict, note.strip())
        if full is None:
            return f"No incident starting with #{incident_id}."
        if verdict == "correct":
            return f"Recorded: #{full[:8]} confirmed. Thanks."
        return f"Recorded: #{full[:8]} was wrong, real cause: {note.strip()}. I will remember it."

    async def _index(self) -> str:
        if self._memory is None or not self._memory.available:
            return "Memory is off (needs the pgvector Postgres image and an embedding model)."
        docs = await self._memory.index_documents(self._runbooks_dir)
        incidents = await self._memory.index_incidents()
        return f"Indexed {docs} runbook chunks and {incidents} incidents."
