from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    buffer_api_key: SecretStr
    chatgpt_action_secret: SecretStr
    buffer_api_url: str = "https://api.buffer.com"
    buffer_bridge_url: str = (
        "https://buffer-gpt-action-api-thread-test.onrender.com"
    )
    mcp_auth_token: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
