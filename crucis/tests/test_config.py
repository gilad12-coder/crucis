from crucis.config import Config


class TestConfig:
    """Tests for Config."""

    def test_config_defaults(self):
        """Test that Config has sensible default values."""
        config = Config(
            anthropic_api_key="sk-test",  # type: ignore[arg-type]
            openai_api_key="sk-test",  # type: ignore[arg-type]
        )
        assert config.generation_agent == "claude"
        assert config.generation_model == "claude-opus-4-6"
        assert config.critic_agent == "claude"
        assert config.critic_model == "claude-opus-4-6"
        assert config.max_iterations == 10
        assert config.max_budget_usd == 5.0
        assert config.optimizer_eval_timeout_sec == 180

    def test_config_from_env(self, monkeypatch):
        """Test that Config reads API keys from environment variables.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test-456")
        config = Config()  # type: ignore[call-arg]
        assert config.anthropic_api_key.get_secret_value() == "sk-ant-test-123"
        assert config.openai_api_key.get_secret_value() == "sk-oai-test-456"

    def test_config_missing_keys_still_loads(self, monkeypatch):
        """Test that Config loads even with empty API keys.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = Config(
            anthropic_api_key="",  # type: ignore[arg-type]
            openai_api_key="",  # type: ignore[arg-type]
        )
        assert config.generation_agent == "claude"

    def test_config_secret_str_no_leak(self):
        """Test that Config does not leak secret keys in repr or str."""
        config = Config(
            anthropic_api_key="sk-ant-secret-key-12345",  # type: ignore[arg-type]
            openai_api_key="sk-oai-secret-key-67890",  # type: ignore[arg-type]
        )
        config_repr = repr(config)
        config_str = str(config)
        assert "sk-ant-secret-key-12345" not in config_repr
        assert "sk-oai-secret-key-67890" not in config_repr
        assert "sk-ant-secret-key-12345" not in config_str
        assert "sk-oai-secret-key-67890" not in config_str

    def test_config_generation_agent_choices(self):
        """Test that Config accepts both claude and codex as generation agents."""
        config_claude = Config(
            anthropic_api_key="sk-test",  # type: ignore[arg-type]
            openai_api_key="sk-test",  # type: ignore[arg-type]
            generation_agent="claude",
        )
        assert config_claude.generation_agent == "claude"

        config_codex = Config(
            anthropic_api_key="sk-test",  # type: ignore[arg-type]
            openai_api_key="sk-test",  # type: ignore[arg-type]
            generation_agent="codex",
        )
        assert config_codex.generation_agent == "codex"

    def test_config_critic_agent_and_model(self):
        """Test that Config stores critic agent and model settings."""
        config = Config(
            anthropic_api_key="sk-test",  # type: ignore[arg-type]
            openai_api_key="sk-test",  # type: ignore[arg-type]
            critic_agent="codex",
            critic_model="gpt-4o",
        )
        assert config.critic_agent == "codex"
        assert config.critic_model == "gpt-4o"
