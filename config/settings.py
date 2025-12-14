"""Configuration settings for the trading system."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    kalshi_api_key: str = ""
    kalshi_api_secret: str = ""
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    kelly_fraction: float = 0.25
    max_position_per_market: float = 0.05
    max_cluster_allocation: float = 0.10
    min_edge_threshold: float = 0.01
    safety_margin: float = 0.005

    max_drawdown_warning: float = 0.10
    max_drawdown_reduce: float = 0.20
    max_drawdown_stop: float = 0.30

    scan_interval_seconds: float = 2.0
    cache_ttl_seconds: int = 30

    # Profit-taking settings
    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.10
    trailing_stop_pct: float = 0.05
    use_trailing_stop: bool = True
    min_hold_seconds: int = 60

    # Daemon settings
    daemon_max_restarts: int = 10
    daemon_restart_delay: float = 30.0

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_prefix = "KALSHI_"


settings = Settings()
