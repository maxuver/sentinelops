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

    # --- context collectors (comma-separated: stub, k8s-events, prometheus, loki) ---
    # Fixed in config, not chosen by the model at runtime (ADR-0001).
    collectors: str = "stub"
    k8s_max_events: int = 20
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    loki_max_lines: int = 50
    loki_window_minutes: int = 15

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

    # --- deduplication ---
    # Alertmanager re-sends a firing alert every repeat_interval. Analysing the
    # same fingerprint again costs money and spams the engineer, so suppress
    # repeats inside this window (default 1h, matching a typical repeat_interval).
    dedup_window_seconds: int = 3600

    # --- persistence (ADR-0002: only post-redaction data is stored) ---
    store: str = "memory"  # "memory" | "postgres"
    postgres_dsn: str = "postgresql://sentinel:sentinel@localhost:5432/sentinelops"

    # --- delivery ---
    notifier: str = "stub"  # "telegram" | "slack" | "stub"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Slack Incoming Webhook URL. One pasted URL is all a customer needs:
    # no OAuth app, no bot token, no scopes to review.
    slack_webhook_url: str = ""

    log_level: str = "INFO"

    model_config = {"env_prefix": "SENTINELOPS_"}


settings = Settings()
