"""
Incremental scanner for efficient space recalculation.

Instead of scanning the entire 10TB filesystem every 60 minutes,
this module tracks file changes using stored metadata and only
processes files that have been added, modified, or deleted since
the last scan. This dramatically reduces scan time for large servers.
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from server_space_optimizer.models.database import (
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
)
from server_space_optimizer.scanner.space_calculator import (
    DirectoryScanResult,
    format_size,
    scan_directory_recursive,
    scan_files_since,
)

logger = logging.getLogger(__name__)


class IncrementalScanner:
    """
    Manages incremental scanning of NAS mount directories.

    First scan performs a full directory traversal. Subsequent scans
    only check for changes (new/modified/deleted files) to minimize
    I/O on large filesystems.
    """

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def _get_last_scan_time(
        self, server_name: str, sub_app_name: str
    ) -> Optional[datetime]:
        """Retrieve the timestamp of the last successful scan for a sub-app."""
        last_scan = (
            self.db_session.query(ScanResult)
            .filter(
                ScanResult.server_name == server_name,
                ScanResult.sub_app_name == sub_app_name,
            )
            .order_by(ScanResult.scan_timestamp.desc())
            .first()
        )
        return last_scan.scan_timestamp if last_scan else None

    def _perform_full_scan(
        self,
        server_name: str,
        sub_app_name: str,
        directory_path: str,
    ) -> DirectoryScanResult:
        """
        Execute a full directory scan and store all file metadata.

        Used on the first scan or when a full rescan is explicitly requested.
        """
        logger.info(
            "Performing full scan: server=%s, sub_app=%s, path=%s",
            server_name,
            sub_app_name,
            directory_path,
        )
        start_time = time.time()

        # Scan the entire directory tree
        scan_result = scan_directory_recursive(directory_path, collect_file_info=True)

        # Clear existing file metadata for this sub-app (fresh start)
        self.db_session.query(FileMetadata).filter(
            FileMetadata.server_name == server_name,
            FileMetadata.sub_app_name == sub_app_name,
        ).delete()

        # Store metadata for each discovered file
        now = datetime.utcnow()
        for file_info in scan_result.files:
            file_meta = FileMetadata(
                server_name=server_name,
                sub_app_name=sub_app_name,
                file_path=file_info.path,
                file_size_bytes=file_info.size_bytes,
                last_modified=file_info.last_modified,
                last_accessed=file_info.last_accessed,
                created_at=file_info.created_at,
                last_scanned=now,
                is_deleted=0,
            )
            self.db_session.add(file_meta)

        scan_duration = time.time() - start_time

        # Record the scan result
        scan_record = ScanResult(
            server_name=server_name,
            sub_app_name=sub_app_name,
            scan_timestamp=now,
            total_size_bytes=scan_result.total_size_bytes,
            total_file_count=scan_result.file_count,
            total_dir_count=scan_result.dir_count,
            scan_type="full",
            scan_duration_seconds=scan_duration,
        )
        self.db_session.add(scan_record)

        # Store a space snapshot for growth prediction
        snapshot = SpaceSnapshot(
            server_name=server_name,
            sub_app_name=sub_app_name,
            snapshot_timestamp=now,
            total_size_bytes=scan_result.total_size_bytes,
            total_file_count=scan_result.file_count,
        )
        self.db_session.add(snapshot)

        self.db_session.commit()

        logger.info(
            "Full scan complete: %d files, %s, took %.2fs",
            scan_result.file_count,
            format_size(scan_result.total_size_bytes),
            scan_duration,
        )

        return scan_result

    def _perform_incremental_scan(
        self,
        server_name: str,
        sub_app_name: str,
        directory_path: str,
        last_scan_time: datetime,
    ) -> DirectoryScanResult:
        """
        Execute an incremental scan processing only changes since last scan.

        Steps:
        1. Find files modified since last scan timestamp
        2. Update their metadata in the database
        3. Detect deleted files by checking if stored paths still exist
        4. Recalculate totals from the updated database
        """
        logger.info(
            "Performing incremental scan: server=%s, sub_app=%s, since=%s",
            server_name,
            sub_app_name,
            last_scan_time,
        )
        start_time = time.time()
        now = datetime.utcnow()
        modified_count = 0
        new_count = 0
        deleted_count = 0

        # Step 1: Process files modified since last scan
        for file_info in scan_files_since(directory_path, last_scan_time):
            existing = (
                self.db_session.query(FileMetadata)
                .filter(
                    FileMetadata.server_name == server_name,
                    FileMetadata.sub_app_name == sub_app_name,
                    FileMetadata.file_path == file_info.path,
                )
                .first()
            )

            if existing:
                # Update existing file metadata
                existing.file_size_bytes = file_info.size_bytes
                existing.last_modified = file_info.last_modified
                existing.last_accessed = file_info.last_accessed
                existing.last_scanned = now
                existing.is_deleted = 0
                modified_count += 1
            else:
                # New file discovered
                new_meta = FileMetadata(
                    server_name=server_name,
                    sub_app_name=sub_app_name,
                    file_path=file_info.path,
                    file_size_bytes=file_info.size_bytes,
                    last_modified=file_info.last_modified,
                    last_accessed=file_info.last_accessed,
                    created_at=file_info.created_at,
                    last_scanned=now,
                    is_deleted=0,
                )
                self.db_session.add(new_meta)
                new_count += 1

        # Step 2: Detect deleted files by sampling stored paths
        # For performance on large datasets, check files not scanned recently
        stale_files = (
            self.db_session.query(FileMetadata)
            .filter(
                FileMetadata.server_name == server_name,
                FileMetadata.sub_app_name == sub_app_name,
                FileMetadata.is_deleted == 0,
                FileMetadata.last_scanned < now,
            )
            .all()
        )

        for file_meta in stale_files:
            if not os.path.exists(file_meta.file_path):
                file_meta.is_deleted = 1
                file_meta.last_scanned = now
                deleted_count += 1

        # Step 3: Recalculate totals from database (active files only)
        from sqlalchemy import func

        totals = (
            self.db_session.query(
                func.sum(FileMetadata.file_size_bytes),
                func.count(FileMetadata.id),
            )
            .filter(
                FileMetadata.server_name == server_name,
                FileMetadata.sub_app_name == sub_app_name,
                FileMetadata.is_deleted == 0,
            )
            .first()
        )

        total_size = totals[0] or 0
        total_files = totals[1] or 0

        scan_duration = time.time() - start_time

        # Record the scan result
        scan_record = ScanResult(
            server_name=server_name,
            sub_app_name=sub_app_name,
            scan_timestamp=now,
            total_size_bytes=total_size,
            total_file_count=total_files,
            total_dir_count=0,
            scan_type="incremental",
            scan_duration_seconds=scan_duration,
        )
        self.db_session.add(scan_record)

        # Store a space snapshot for growth prediction
        snapshot = SpaceSnapshot(
            server_name=server_name,
            sub_app_name=sub_app_name,
            snapshot_timestamp=now,
            total_size_bytes=total_size,
            total_file_count=total_files,
        )
        self.db_session.add(snapshot)

        self.db_session.commit()

        logger.info(
            "Incremental scan complete: new=%d, modified=%d, deleted=%d, "
            "total=%s, took %.2fs",
            new_count,
            modified_count,
            deleted_count,
            format_size(total_size),
            scan_duration,
        )

        # Build result object
        result = DirectoryScanResult(directory_path=directory_path)
        result.total_size_bytes = total_size
        result.file_count = total_files
        return result

    def scan_sub_app(
        self,
        server_name: str,
        sub_app_name: str,
        directory_path: str,
        force_full: bool = False,
    ) -> DirectoryScanResult:
        """
        Scan a sub-application directory, using incremental mode when possible.

        Automatically determines whether to do a full or incremental scan
        based on whether a previous scan exists.

        Args:
            server_name: Name of the server being scanned
            sub_app_name: Name of the sub-application
            directory_path: Absolute path to the sub-app directory
            force_full: Force a full scan even if incremental is possible
        """
        last_scan_time = self._get_last_scan_time(server_name, sub_app_name)

        if last_scan_time is None or force_full:
            # No previous scan exists - perform full scan
            return self._perform_full_scan(
                server_name, sub_app_name, directory_path
            )
        else:
            # Previous scan exists - perform incremental scan
            return self._perform_incremental_scan(
                server_name, sub_app_name, directory_path, last_scan_time
            )
