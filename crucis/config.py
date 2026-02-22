"""Environment-based configuration using pydantic-settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    generation_agent: str = "claude"
    generation_model: str = "claude-opus-4-6"
    critic_agent: str = "claude"
    critic_model: str = "claude-opus-4-6"
    implementation_agent: str = "codex"
    implementation_model: str = "gpt-5.3-codex"
    max_iterations: int = 10
    max_budget_usd: float = 5.0
    optimizer_eval_timeout_sec: int = 180
