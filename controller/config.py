"""Controller configuration model."""

import os
from pydantic import BaseModel, Field


class ControllerConfig(BaseModel):
    app_env: str = Field(default="production", description="Application environment (production, staging, development, local)")
    host: str = "127.0.0.1"
    port: int = 61003
    api_prefix: str = "/api/v1"
    monitor_interval_seconds: int = 10
    api_token: str | None = Field(default=None, description="Bearer token for API auth; None disables auth, empty string rejects all")
    log_level: str = "INFO"
    log_file: str | None = Field(default=None, description="Path to log file; None disables file logging")
    redis_url: str = "redis://localhost:61004/0"
    max_concurrent_tasks: int = 5
    max_concurrent_analysis: int = 100
    allowed_host_paths: str = "/home,/mnt,/opt,/data,/tmp"
    auto_analysis: bool = True

    @classmethod
    def from_env(cls) -> "ControllerConfig":
        """Build config from CONTROLLER_* environment variables."""
        data: dict = {}
        env_mapping = {
            "CONTROLLER_APP_ENV": ("app_env", str),
            "CONTROLLER_HOST": ("host", str),
            "CONTROLLER_PORT": ("port", int),
            "CONTROLLER_API_TOKEN": ("api_token", str),
            "CONTROLLER_LOG_LEVEL": ("log_level", str),
            "CONTROLLER_LOG_FILE": ("log_file", str),
            "CONTROLLER_MONITOR_INTERVAL": ("monitor_interval_seconds", int),
            "CONTROLLER_REDIS_URL": ("redis_url", str),
            "CONTROLLER_MAX_CONCURRENT_TASKS": ("max_concurrent_tasks", int),
            "CONTROLLER_MAX_CONCURRENT_ANALYSIS": ("max_concurrent_analysis", int),
            "CONTROLLER_ALLOWED_PATHS": ("allowed_host_paths", str),
            "CONTROLLER_AUTO_ANALYSIS": ("auto_analysis", bool),
        }
        for env_key, (field_name, field_type) in env_mapping.items():
            val = os.environ.get(env_key)
            if val is not None:
                data[field_name] = field_type(val)
        return cls(**data)

    def get_allowed_paths(self) -> list[str]:
        return [p.strip() for p in self.allowed_host_paths.split(",") if p.strip()]
