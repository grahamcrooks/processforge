from pathlib import Path
from pydantic_settings import BaseSettings

_here = Path(__file__).parent
_root = _here.parent

# Build ordered list of env files — later files override earlier ones.
# .env holds secrets (API key); .env.local holds mode overrides (DEV_MODE, API_MODEL).
_env_files = []
for candidate in [_here / ".env", _root / ".env", _root / ".env.local"]:
    if candidate.exists():
        _env_files.append(str(candidate))


class Settings(BaseSettings):
    anthropic_api_key: str = "not-set"
    claude_model: str = "claude-sonnet-4-6"   # overridden by API_MODEL in env
    api_model: str = ""                         # if set, takes priority over claude_model
    dev_mode: bool = False
    max_image_size_mb: int = 10
    mode_pin: str ="2000"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5176"]

    class Config:
        env_file = _env_files if _env_files else None

    @property
    def effective_model(self) -> str:
        """api_model (from .env.local) takes priority; falls back to claude_model."""
        return self.api_model if self.api_model else self.claude_model


settings = Settings()
