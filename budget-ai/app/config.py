from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:devpass@localhost:5432/recon"

    # Security
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # LLM
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"

    # Reconciliation thresholds (RFP FR-06)
    auto_match_confidence_threshold: float = 0.90   # above → auto-reconciled
    review_confidence_threshold: float = 0.70        # below → exception queue
    batch_timeout_seconds: int = 600                 # 10-min SLA per RFP TR-14

    # App
    app_name: str = "Reconciliation AI Agent"
    debug: bool = False


settings = Settings()
