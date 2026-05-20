from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config").is_dir() and (parent / "backend").is_dir():
            return parent
    return current.parents[3]


@dataclass(frozen=True)
class RuntimeConfig:
    project_root: Path
    platform: str
    profile: str
    ai_provider: str
    daily_token_hard_cap: bool
    local_only: bool

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"


def get_runtime_config() -> RuntimeConfig:
    project_root = Path(
        env_str("SITY_PROJECT_ROOT", str(_find_project_root()))
    ).expanduser().resolve()

    return RuntimeConfig(
        project_root=project_root,
        platform=env_str("SITY_PLATFORM", "raspberrypi"),
        profile=env_str("SITY_PROFILE", "repo-only"),
        ai_provider=env_str("SITY_AI_PROVIDER", "anthropic"),
        daily_token_hard_cap=env_bool("SITY_DAILY_TOKEN_HARD_CAP", False),
        local_only=env_bool("SITY_LOCAL_ONLY", False),
    )
