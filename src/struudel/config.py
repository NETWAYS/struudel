from functools import cached_property

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    secret_key: str = "dev-only-change-for-production"

    db_host: str = "postgres"
    db_name: str = "struudel"
    db_user: str = ""
    db_pass: str = ""

    @computed_field
    @cached_property
    def database_url(self) -> str:
        return f"postgresql+psycopg://{self.db_user}:{self.db_pass}@{self.db_host}/{self.db_name}"

    huey_redis_url: str = "redis://redis:6379/0"

    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    oidc_provider_name: str = "SSO"

    scim_token: str = ""

    poll_retention_days: int = 30

    app_timezone: str = "Europe/Berlin"

    session_redis_url: str = "redis://redis:6379/1"
    app_state_redis_url: str = "redis://redis:6379/2"
    session_lifetime_hours: int = 12
    session_cookie_name: str = "struudel"
    session_cookie_secure: bool = False
    session_cookie_httponly: bool = True
    session_cookie_samesite: str = "Lax"

    app_base_url: str = "http://localhost:5009"

    mail_enabled: bool = True
    mail_host: str = "mailpit"
    mail_port: int = 1025
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = "no-reply@struudel.local"
    mail_from_name: str = "Struudel"
    mail_starttls: bool = False
    mail_ssl: bool = False
    mail_timeout_seconds: int = 10

    @model_validator(mode="after")
    def _require_settings(self) -> "Settings":
        missing = [
            name
            for name, value in (
                ("DB_HOST", self.db_host),
                ("DB_NAME", self.db_name),
                ("DB_USER", self.db_user),
                ("DB_PASS", self.db_pass),
                ("OIDC_DISCOVERY_URL", self.oidc_discovery_url),
                ("OIDC_CLIENT_ID", self.oidc_client_id),
                ("OIDC_CLIENT_SECRET", self.oidc_client_secret),
                ("SCIM_TOKEN", self.scim_token),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return self


settings = Settings()
