from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # IBKR
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497  # paper by default
    ibkr_client_id: int = 17

    # Data / AI
    fmp_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Trading rules (runtime-editable via the dashboard; these are startup defaults)
    auto_trade_enabled: bool = False
    auto_trade_threshold: float = 90.0
    max_trades_per_day: int = 2
    max_daily_loss: float = 100.0
    risk_per_trade: float = 25.0
    max_position_size: float = 1000.0

    # Candidate filters
    min_gap_pct: float = 8.0
    min_relative_volume: float = 3.0
    min_price: float = 5.0

    # Signal engine tuning
    detector_warmup_bars: int = 5
    shakeout_recovery_bars: int = 10      # bars allowed between low break and recovery
    short_extension_pct: float = 1.0      # HOD must be >= this % above VWAP before a short
    min_reward_risk: float = 1.5          # skip signals with worse reward:risk

    # Dashboard (Railway sets PORT; bind 0.0.0.0 in production)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, validation_alias=AliasChoices("API_PORT", "PORT"))


settings = Settings()
