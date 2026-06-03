"""
Configuration management for Server Space Optimizer.

Loads server configuration from YAML files and environment variables.
Supports multiple servers with their NAS mount points and sub-applications.

Sub-apps can be configured with:
  - Dedicated absolute paths or mounts (e.g., /mnt/nas1/app-billing)
  - Glob patterns for matching subfolders (e.g., logs_*, data_202*)
  - Subfolder paths within a shared/common NAS mount
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class SubAppConfig(BaseModel):
    """
    Configuration for a sub-application directory.

    Supports three modes of path resolution:
    1. Dedicated mount: Set 'is_dedicated_mount' to True and 'path' to an
       absolute path (e.g., /mnt/nas_billing/data)
    2. Relative subfolder: Set 'path' relative to the server's nas_mount_path
       (e.g., billing/transactions)
    3. Pattern-based: Set 'patterns' to glob patterns that match subfolders
       within the NAS mount, useful for shared NAS with naming conventions
       (e.g., ["logs_*", "archive_2024*"])
    """
    name: str = Field(..., description="Sub-application display name")
    path: str = Field(
        default="",
        description=(
            "Path to the sub-app directory. Can be an absolute path "
            "(dedicated mount) or a relative path under the NAS mount"
        ),
    )
    # Glob patterns for matching subfolders within a shared NAS
    patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Glob patterns to match subfolders in the NAS mount. "
            "Useful when sub-apps are identified by naming conventions "
            "in a shared NAS (e.g., ['logs_*', 'data_202*'])"
        ),
    )
    # Whether this sub-app has a dedicated mount point (absolute path)
    is_dedicated_mount: bool = Field(
        default=False,
        description=(
            "If True, 'path' is treated as an absolute path to a "
            "dedicated NAS mount rather than relative to nas_mount_path"
        ),
    )


class ServerConfig(BaseModel):
    """
    Configuration for a single server's NAS mounts.

    A server can have a shared NAS mount path where sub-apps live as
    subfolders or patterns, plus sub-apps with their own dedicated mounts.
    """
    server_name: str = Field(..., description="Display name for the server")
    server_host: str = Field(..., description="Hostname or IP of the server")
    nas_mount_path: str = Field(
        ..., description="Root shared NAS mount path on the server"
    )
    sub_apps: list[SubAppConfig] = Field(
        default_factory=list,
        description="List of sub-applications under the NAS mount",
    )


class AppConfig(BaseModel):
    """Top-level application configuration."""
    # Scan settings
    scan_interval_minutes: int = Field(
        default=60,
        description="Interval between incremental scans in minutes"
    )
    # Purge settings - files older than these thresholds are flagged
    purge_thresholds_days: list[int] = Field(
        default=[90, 180, 365],
        description="Age thresholds (days) for purge eligibility"
    )
    # Database path for storing scan history
    database_path: str = Field(
        default="space_optimizer.db",
        description="SQLite database file path"
    )
    # Server configurations
    servers: list[ServerConfig] = Field(
        default_factory=list,
        description="List of server configurations"
    )
    # Web UI settings
    host: str = Field(default="0.0.0.0", description="Host to bind the web server")
    port: int = Field(default=8080, description="Port for the web server")
    # System mount paths to exclude from scanning (never scan these)
    excluded_mounts: list[str] = Field(
        default=[
            "/var", "/opt", "/home", "/optware", "/tmp",
            "/etc", "/boot", "/proc", "/sys", "/dev", "/run",
        ],
        description=(
            "System mount paths to exclude from scanning. "
            "Only user-defined data mounts will be scanned."
        ),
    )
    # Cost estimation: dollars per GB per month
    cost_per_gb_month: float = Field(
        default=0.023,
        description="Storage cost in dollars per GB per month"
    )
    # Secret key for session cookies — read from SECRET_KEY env var in production
    secret_key: str = Field(
        default_factory=lambda: os.environ.get(
            "SECRET_KEY", "space-optimizer-dev-key"
        ),
        description="Secret key for session management (set SECRET_KEY env var in production)",
    )


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from a YAML file.

    Falls back to environment variable CONFIG_PATH or default path
    if no config_path is provided.
    """
    if config_path is None:
        config_path = os.environ.get(
            "CONFIG_PATH",
            str(Path(__file__).parent.parent / "server_config" / "servers.yaml")
        )

    config_file = Path(config_path)
    if not config_file.exists():
        # Return default config if no file found
        return AppConfig()

    with open(config_file, "r") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        return AppConfig()

    return AppConfig(**raw_config)
