from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration, read from SENTINELOPS_* environment variables.

    Shares the alert-stream settings with ingest-api by convention (same
    SENTINELOPS_ prefix, same defaults) so the two services agree on the queue.
    """

    # --- queue (must match ingest-api) ---
    redis_url: str = "redis://localhost:6379/0"
    alerts_stream: str = "sentinelops:alerts"
    dead_letter_stream: str = "sentinelops:alerts:dead"
    consumer_group: str = "analyzers"
    consumer_name: str = "analyzer-1"
    # XREADGROUP tuning: how many messages to pull and how long to block (ms).
    read_count: int = 10
    block_ms: int = 5_000
    # A message that keeps failing is parked in the dead-letter stream after this
    # many delivery attempts, so a poison message can never wedge the loop (ADR-0003).
    max_delivery_attempts: int = 5

    # --- LLM backend (ADR-0002: selecting a backend is configuration, not code) ---
    llm_provider: str = "stub"  # "anthropic" | "ollama" | "stub"
    # Fast path defaults to Haiku: analysing *every* alert then costs cents
    # (VISION §3, ADR-0001). Override per deployment.
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_max_tokens: int = 512
    # Pricing in USD per 1M tokens, used only to record cost per incident.
    price_in_per_mtok: float = 1.00
    price_out_per_mtok: float = 5.00
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    # Hard ceiling on a single analysis call — analysis must never hang the loop.
    llm_timeout_seconds: float = 30.0
    # Per-UTC-day spend cap; on exhaustion the pipeline degrades to raw delivery.
    daily_budget_usd: float = 5.00

    # --- delivery ---
    notifier: str = "stub"  # "telegram" | "stub"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    log_level: str = "INFO"

    model_config = {"env_prefix": "SENTINELOPS_"}


settings = Settings()
