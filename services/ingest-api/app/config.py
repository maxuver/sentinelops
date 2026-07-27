from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration, read from SENTINELOPS_* environment variables."""

    redis_url: str = "redis://localhost:6379/0"
    alerts_stream: str = "sentinelops:alerts"
    # Cap stream length so a dead worker can't grow Redis unbounded (ADR-0003).
    alerts_stream_maxlen: int = 10_000
    log_level: str = "INFO"

    model_config = {"env_prefix": "SENTINELOPS_"}


settings = Settings()
