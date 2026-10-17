from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Broker: alpaca (default) or ibkr
    broker: str = "alpaca"
    execution_mode: Literal["research", "paper"] = "paper"
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True  # Legacy input; trading transport is always paper.
    alpaca_data_feed: str = "iex"  # iex (free) or sip (paid subscription)

    # IBKR (only when BROKER=ibkr)
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497  # paper by default
    ibkr_client_id: int = 17

    # Scan data (Finnhub earnings today + Alpaca movers)
    finnhub_api_key: str = ""
    alpaca_movers_top: int = 25

    # Data / AI (legacy — scanner no longer uses FMP)
    fmp_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    state_db_path: str = "data/paper.sqlite3"

    # Trading rules (runtime-editable via the dashboard; these are startup defaults)
    auto_trade_enabled: bool = True  # Paper-only experiment; research mode always overrides this.
    auto_trade_threshold: float = 90.0
    max_trades_per_day: int = 2
    max_daily_loss: float = 100.0
    risk_per_trade: float = 25.0
    max_position_size: float = 1000.0

    # Candidate filters
    min_gap_pct: float = 8.0
    min_relative_volume: float = 3.0
    min_price: float = 0.0  # legacy setting, no longer used for qualification
    min_dollar_volume_5m: float = Field(default=250_000, ge=0)
    max_spread_pct: float = Field(default=1.0, gt=0)
    max_spread_risk_pct: float = Field(default=20.0, gt=0)
    max_volume_participation_pct: float = Field(default=1.0, gt=0, le=100)
    max_quote_age_seconds: int = Field(default=15, gt=0)
    min_active_minutes: int = Field(default=4, ge=1, le=5)

    # Signal engine tuning
    detector_warmup_bars: int = 5
    shakeout_recovery_bars: int = 10      # bars allowed between low break and recovery
    short_extension_pct: float = 1.0      # HOD must be >= this % above VWAP before a short
    min_reward_risk: float = 1.5          # skip signals with worse reward:risk
    signal_ttl_seconds: int = 600         # auto-expire pending signals after 10 min
    scan_interval_seconds: int = Field(default=60, ge=15)
    bar_poll_interval_seconds: int = Field(default=10, ge=5)
    max_signal_bar_age_seconds: int = Field(default=90, ge=0)
    morning_only: bool = True
    setup_low_lookback_bars: int = Field(default=5, ge=3)
    max_active_symbols: int = Field(default=100, ge=12, le=200)

    # Dashboard (Railway sets PORT; bind 0.0.0.0 in production)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, validation_alias=AliasChoices("API_PORT", "PORT"))


settings = Settings()
