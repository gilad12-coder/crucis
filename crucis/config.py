"""Environment-based configuration using pydantic-settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings

_DEFAULT_AGENT = "claude"
_DEFAULT_MODEL = "claude-opus-4-6"


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    generation_agent: str = _DEFAULT_AGENT
    generation_model: str = _DEFAULT_MODEL
    critic_agent: str = _DEFAULT_AGENT
    critic_model: str = _DEFAULT_MODEL
    implementation_agent: str = _DEFAULT_AGENT
    implementation_model: str = _DEFAULT_MODEL
    max_iterations: int = 10
    max_budget_usd: float = 5.0
    optimizer_eval_timeout_sec: int = 180
