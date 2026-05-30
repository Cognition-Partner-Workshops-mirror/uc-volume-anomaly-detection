"""
Space calculator for Linux NAS mount directories.

Uses os.scandir() for high-performance directory traversal,
collecting file sizes, modification times, and access times.
Designed for large filesystems (~10TB) with efficient memory usage.
"""

import calendar
import os
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Metadata for a single file discovered during scanning."""
    path: str
    size_bytes: float
    last_modified: datetime
    last_accessed: datetime
    created_at: datetime


@dataclass
class DirectoryScanResult:
    """Aggregate scan result for a directory (sub-app)."""
    directory_path: str
    total_size_bytes: float = 0
    file_count: int = 0
    dir_count: int = 0
    files: list[FileInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _timestamp_to_datetime(ts: float) -> datetime:
    """Convert a Unix timestamp to a UTC datetime object safely."""
    try:
        # Use utcfromtimestamp to keep all timestamps in UTC consistently
        return datetime.utcfromtimestamp(ts)
    except (OSError, ValueError):
        return datetime.utcfromtimestamp(0)


def scan_directory_recursive(
    root_path: str,
    collect_file_info: bool = True
) -> DirectoryScanResult:
    """
    Recursively scan a directory and calculate total space usage.

    Uses os.scandir() for better performance than os.walk() on large
    directories, as it avoids redundant stat() calls by using
    DirEntry.stat() which caches results.

    Args:
        root_path: Absolute path to the directory to scan
        collect_file_info: If True, collect individual file metadata
                          (set False for faster aggregate-only scans)

    Returns:
        DirectoryScanResult with aggregate sizes and optional file details
    """
    result = DirectoryScanResult(directory_path=root_path)

    if not os.path.exists(root_path):
        result.errors.append(f"Directory does not exist: {root_path}")
        logger.warning("Directory does not exist: %s", root_path)
        return result

    if not os.path.isdir(root_path):
        result.errors.append(f"Path is not a directory: {root_path}")
        logger.warning("Path is not a directory: %s", root_path)
        return result

    # Use a stack-based approach instead of recursion for large directory trees
    dir_stack = [root_path]

    while dir_stack:
        current_dir = dir_stack.pop()
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            # Count subdirectory and add to stack for traversal
                            result.dir_count += 1
                            dir_stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            # Get file stats (cached by DirEntry)
                            stat_result = entry.stat(follow_symlinks=False)
                            file_size = stat_result.st_size
                            result.total_size_bytes += file_size
                            result.file_count += 1

                            if collect_file_info:
                                file_info = FileInfo(
                                    path=entry.path,
                                    size_bytes=file_size,
                                    last_modified=_timestamp_to_datetime(
                                        stat_result.st_mtime
                                    ),
                                    last_accessed=_timestamp_to_datetime(
                                        stat_result.st_atime
                                    ),
                                    created_at=_timestamp_to_datetime(
                                        stat_result.st_ctime
                                    ),
                                )
                                result.files.append(file_info)
                    except (PermissionError, OSError) as e:
                        # Log but continue scanning other files
                        error_msg = f"Error accessing {entry.path}: {e}"
                        result.errors.append(error_msg)
                        logger.debug(error_msg)
        except (PermissionError, OSError) as e:
            error_msg = f"Error scanning directory {current_dir}: {e}"
            result.errors.append(error_msg)
            logger.debug(error_msg)

    return result


def scan_files_since(
    root_path: str,
    since_timestamp: datetime
) -> Generator[FileInfo, None, None]:
    """
    Yield only files modified since the given timestamp.

    Used for incremental scanning to avoid re-processing the entire
    directory tree on each 60-minute refresh cycle. This is critical
    for performance on ~10TB servers.

    Args:
        root_path: Absolute path to the directory to scan
        since_timestamp: Only yield files modified after this time

    Yields:
        FileInfo for each file modified since the given timestamp
    """
    # Use calendar.timegm to correctly interpret naive UTC datetime as UTC
    since_ts = calendar.timegm(since_timestamp.timetuple())
    dir_stack = [root_path]

    while dir_stack:
        current_dir = dir_stack.pop()
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dir_stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            stat_result = entry.stat(follow_symlinks=False)
                            # Only process files modified since last scan
                            if stat_result.st_mtime > since_ts:
                                yield FileInfo(
                                    path=entry.path,
                                    size_bytes=stat_result.st_size,
                                    last_modified=_timestamp_to_datetime(
                                        stat_result.st_mtime
                                    ),
                                    last_accessed=_timestamp_to_datetime(
                                        stat_result.st_atime
                                    ),
                                    created_at=_timestamp_to_datetime(
                                        stat_result.st_ctime
                                    ),
                                )
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError):
            continue


def format_size(size_bytes: float) -> str:
    """
    Convert bytes to human-readable size string.

    Examples: 1024 -> '1.00 KB', 1073741824 -> '1.00 GB'
    """
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"
