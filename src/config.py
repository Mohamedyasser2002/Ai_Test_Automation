"""
Centralized Application Configuration
"""

from functools import lru_cache
from pathlib import Path
import socket
import warnings

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_available_port(start_port: int = 8080, max_attempts: int = 20) -> int:
    """Return the first free port starting from the requested port."""
    for offset in range(max_attempts):
        candidate = start_port + offset
        if candidate > 65535:
            candidate = 1024 + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError(f"No free port available starting from {start_port}.")


# ============================================================
# LLM Configuration
# ============================================================

class LLMConfig(BaseSettings):
    """OpenRouter-compatible LLM configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(
        default="",
        description="OpenRouter API key",
    )

    api_base: str = Field(
        default="https://openrouter.ai/api/v1",
    )

    model: str = Field(
        default="openai/gpt-4o-mini",
    )

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        supported_aliases = {
            "google/gemini-2.0-flash-exp:free": "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-thinking-exp:free": "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-001": "openai/gpt-4o-mini",
        }
        normalized = value.strip()
        return supported_aliases.get(normalized, normalized)

    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
    )

    max_tokens: int = Field(
        default=8192,
        ge=1,
        le=32768,
    )

    timeout: int = Field(
        default=120,
        ge=10,
        le=300,
    )

    app_name: str = Field(
        default="AI-Test-Automation",
    )

    app_url: str = Field(
        default="https://localhost:8080",
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        return value.strip()

    def check_configured(self) -> None:
        """Call this before using the configured LLM provider."""
        if not self.api_key:
            raise RuntimeError(
                "LLM_API_KEY is not configured. "
                "Set it in your .env file or environment variables."
            )


# ============================================================
# LangSmith Configuration
# ============================================================

class LangSmithConfig(BaseSettings):
    """LangSmith observability configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LANGCHAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tracing_v2: bool = Field(
        default=True,
        validation_alias=AliasChoices("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2"),
    )

    project: str = Field(
        default="ai-test-automation-prod",
        validation_alias=AliasChoices("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"),
    )

    api_key: str = Field(
        default="",
        description="LangSmith API key",
        validation_alias=AliasChoices("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"),
    )

    endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT"),
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        return value.strip()

    def check_configured(self) -> None:
        """Call this before using LangSmith features."""
        if not self.api_key:
            warnings.warn(
                "LANGCHAIN_API_KEY not set. LangSmith tracing will be disabled. "
                "Set it to enable observability.",
                stacklevel=2,
            )


# ============================================================
# Test Execution Configuration
# ============================================================

class TestExecutionConfig(BaseSettings):
    """Test execution parameters."""

    model_config = SettingsConfigDict(
        env_prefix="TEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    timeout_ui: int = Field(
        default=180,
        ge=1,
    )

    timeout_api: int = Field(
        default=60,
        ge=1,
    )

    timeout_db: int = Field(
        default=30,
        ge=1,
    )

    parallel_workers: int = Field(
        default=4,
        ge=1,
        le=16,
    )


# ============================================================
# Dashboard Configuration
# ============================================================

class DashboardConfig(BaseSettings):
    """FastAPI dashboard configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(
        default="127.0.0.1",
    )

    port: int = Field(
        default=8080,
        ge=1024,
        le=65535,
    )

    reload: bool = Field(
        default=False,
    )


# ============================================================
# Application Configuration
# ============================================================

class AppConfig(BaseSettings):
    """Application-wide configuration."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str = Field(
        default="AI-Test-Automation",
    )

    version: str = Field(
        default="1.0.0",
    )

    environment: str = Field(
        default="development",
    )

    log_level: str = Field(
        default="INFO",
    )

    max_healing_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
    )

    confidence_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )


# ============================================================
# Storage Configuration
# ============================================================

class StorageConfig(BaseSettings):
    """Application artifact directories."""

    model_config = SettingsConfigDict(
        env_prefix="STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    screenshots_dir: Path = Field(
        default=Path("artifacts/screenshots"),
    )

    traces_dir: Path = Field(
        default=Path("artifacts/traces"),
    )

    reports_dir: Path = Field(
        default=Path("artifacts/reports"),
    )

    data_dir: Path = Field(
        default=Path("data"),
    )

    @field_validator("screenshots_dir", "traces_dir", "reports_dir", "data_dir")
    @classmethod
    def ensure_dir_exists(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value


# ============================================================
# Database Configuration
# ============================================================

class DatabaseConfig(BaseSettings):
    """PostgreSQL configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(
        default="postgresql+psycopg://testuser:testpass@postgres:5432/testautomation",
    )

    pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    max_overflow: int = Field(
        default=20,
        ge=0,
        le=100,
    )

    pool_timeout: int = Field(
        default=30,
        ge=1,
    )

    pool_recycle: int = Field(
        default=1800,
        ge=60,
    )

    echo: bool = Field(
        default=False,
    )


# ============================================================
# Redis Configuration
# ============================================================

class RedisConfig(BaseSettings):
    """Redis configuration."""

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(
        default="redis://redis:6379/0",
    )

    max_connections: int = Field(
        default=50,
        ge=1,
        le=500,
    )

    socket_timeout: int = Field(
        default=5,
        ge=1,
    )

    socket_connect_timeout: int = Field(
        default=5,
        ge=1,
    )


# ============================================================
# Playwright Configuration
# ============================================================

class PlaywrightConfig(BaseSettings):
    """Playwright browser configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PLAYWRIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    browsers_path: str = Field(
        default="/root/.cache/ms-playwright",
    )

    headless: bool = Field(
        default=True,
    )

    browser: str = Field(
        default="chromium",
    )

    timeout: int = Field(
        default=30000,
        ge=1000,
        le=300000,
    )


# ============================================================
# Prometheus Configuration
# ============================================================

class MetricsConfig(BaseSettings):
    """Prometheus metrics configuration."""

    model_config = SettingsConfigDict(
        env_prefix="METRICS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
    )

    path: str = Field(
        default="/metrics",
    )


# ============================================================
# Master Settings
# ============================================================

class Settings(BaseSettings):
    """
    Master application settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    test_execution: TestExecutionConfig = Field(default_factory=TestExecutionConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


# ============================================================
# Settings Singleton
# ============================================================

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()