"""
Path resolver for sub-application directory resolution.

Handles three modes of sub-app path configuration:
1. Dedicated mount: Absolute path to a dedicated NAS mount
2. Relative subfolder: Path relative to the server's nas_mount_path
3. Pattern-based: Glob patterns matching subfolders in a shared NAS

This ensures sub-apps with dedicated paths, specific subfolders,
or naming convention patterns in a common/shared NAS are all resolved
correctly before scanning.
"""

import glob
import logging
import os

from server_space_optimizer.config import ServerConfig, SubAppConfig

logger = logging.getLogger(__name__)


def resolve_sub_app_paths(
    server_config: ServerConfig,
    sub_app: SubAppConfig,
) -> list[str]:
    """
    Resolve the actual filesystem paths for a sub-application.

    Depending on the sub-app config mode, returns one or more paths:
    - Dedicated mount: returns the single absolute path from sub_app.path
    - Relative subfolder: joins nas_mount_path + sub_app.path
    - Pattern-based: expands glob patterns under nas_mount_path and
      returns all matching directory paths

    Args:
        server_config: The parent server configuration with nas_mount_path
        sub_app: The sub-application configuration to resolve

    Returns:
        List of absolute directory paths to scan for this sub-app
    """
    resolved_paths = []

    # Mode 1: Dedicated mount - sub-app has its own absolute mount point
    if sub_app.is_dedicated_mount and sub_app.path:
        if os.path.isdir(sub_app.path):
            resolved_paths.append(sub_app.path)
        else:
            logger.warning(
                "Dedicated mount path does not exist: %s (sub-app: %s)",
                sub_app.path,
                sub_app.name,
            )
        return resolved_paths

    # Mode 3: Pattern-based - glob patterns matching subfolders in shared NAS
    if sub_app.patterns:
        nas_root = server_config.nas_mount_path
        for pattern in sub_app.patterns:
            # Build the full glob pattern under the NAS mount
            full_pattern = os.path.join(nas_root, pattern)
            matches = glob.glob(full_pattern)
            for match in sorted(matches):
                if os.path.isdir(match):
                    resolved_paths.append(match)
                    logger.debug(
                        "Pattern '%s' matched directory: %s",
                        pattern,
                        match,
                    )
        if not resolved_paths:
            logger.warning(
                "No directories matched patterns %s under %s (sub-app: %s)",
                sub_app.patterns,
                nas_root,
                sub_app.name,
            )
        return resolved_paths

    # Mode 2: Relative subfolder - path is relative to nas_mount_path
    if sub_app.path:
        full_path = os.path.join(server_config.nas_mount_path, sub_app.path)
        if os.path.isdir(full_path):
            resolved_paths.append(full_path)
        else:
            logger.warning(
                "Relative sub-app path does not exist: %s (sub-app: %s)",
                full_path,
                sub_app.name,
            )
        return resolved_paths

    # Fallback: no path or patterns configured, log a warning
    logger.warning(
        "Sub-app '%s' has no path or patterns configured", sub_app.name
    )
    return resolved_paths
