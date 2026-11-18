from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    app_name: str = "rompetr-crm"
    app_base_url: str = "http://127.0.0.1:8000"
    app_secret_key: SecretStr = SecretStr("dev-only-change-me")
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_tz: str = "Asia/Irkutsk"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://rompetr_app:change-me@127.0.0.1:5432/rompetr"
    db_pool_size: int = 5
    db_echo: bool = False

    session_cookie_name: str = "crm_session"
    session_ttl_days: int = 14
    session_absolute_days: int = 30
    cookie_secure: bool = False

    admin_login: str = "admin"
    admin_email: str = ""
    adm_passw: SecretStr = SecretStr("")
    admin_bootstrap: bool = True

    email_mode: str = "dev"
    mail_from: str = "crm@rompetr.ru"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_tls: bool = True

    media_root: str = "var/media"
    posts_root: str = "posts"
    max_upload_mb: int = 10

    rate_limit_login: str = "5/min"
    rate_limit_register: str = "3/hour"
    rate_limit_reset: str = "3/hour"

    proxyapi_key: SecretStr = SecretStr("")
    proxyapi_key_secondary: SecretStr = SecretStr("")
    proxyapi_base_url: str = "https://api.proxyapi.ru"
    image_model: str = "black-forest-labs/flux.2-pro"
    image_fallback_model: str = "gpt-image-1-mini"

    vk_access_token: SecretStr = SecretStr("")
    vk_group_id: str = ""

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""

    x_mode: str = "manual"

    claude_bin: str = "claude"
    claude_code_oauth_token: SecretStr = SecretStr("")
    anthropic_auth_token: SecretStr = SecretStr("")
    anthropic_base_url: str = ""
    claude_config_dir: str = ""
    claude_http_proxy: str = ""
    claude_model: str = "sonnet"
    claude_fallback_model: str = ""
    claude_timeout_sec: int = 900
    claude_max_concurrency: int = 1
    claude_max_turns: int = 20
    claude_max_budget_usd: float = 2.0
    claude_compose_max_turns: int = 30
    claude_compose_budget_usd: float = 6.0

    worker_poll_sec: int = 2
    worker_id: str = "local-1"
    worker_inprocess: bool = False

    guest_compose_limit: int = 1
    guest_image_limit: int = 2

    feature_ai_check: bool = True
    feature_compose: bool = False

    @field_validator("app_env")
    @classmethod
    def _known_env(cls, value: str) -> str:
        allowed = {"dev", "test", "prod"}
        if value not in allowed:
            raise ValueError(f"APP_ENV должен быть одним из {sorted(allowed)}")
        return value

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def media_path(self) -> Path:
        path = Path(self.media_root)
        return path if path.is_absolute() else ROOT / path

    @property
    def posts_path(self) -> Path:
        path = Path(self.posts_root)
        return path if path.is_absolute() else ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
