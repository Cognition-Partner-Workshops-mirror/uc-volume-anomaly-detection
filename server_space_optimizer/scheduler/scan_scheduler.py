"""
Scan scheduler for periodic 60-minute space recalculation.

Uses APScheduler to execute incremental scans at configurable intervals.
Each scan cycle processes all configured servers and their sub-applications,
using incremental mode to only detect changes since the last scan.
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from server_space_optimizer.config import AppConfig
from server_space_optimizer.models.database import get_session, init_database
from server_space_optimizer.scanner.incremental_scanner import IncrementalScanner
from server_space_optimizer.scanner.path_resolver import resolve_sub_app_paths

logger = logging.getLogger(__name__)


class ScanScheduler:
    """
    Manages periodic scanning of all configured servers and sub-apps.

    Runs scans at the configured interval (default: 60 minutes) using
    incremental mode for efficiency on large (10TB+) filesystems.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.scheduler = BackgroundScheduler()
        self.session_factory = init_database(config.database_path)
        self._is_scanning = False
        self._last_scan_time: Optional[datetime] = None
        self._next_scan_time: Optional[datetime] = None

    @property
    def is_scanning(self) -> bool:
        """Whether a scan is currently in progress."""
        return self._is_scanning

    @property
    def last_scan_time(self) -> Optional[datetime]:
        """Timestamp of the last completed scan."""
        return self._last_scan_time

    @property
    def next_scan_time(self) -> Optional[datetime]:
        """Estimated time of the next scheduled scan."""
        return self._next_scan_time

    def _run_scan_cycle(self) -> None:
        """
        Execute one full scan cycle across all servers and sub-apps.

        This is the main job function called by the scheduler every
        60 minutes. Uses incremental scanning for efficiency.
        """
        if self._is_scanning:
            logger.warning("Scan already in progress, skipping this cycle")
            return

        self._is_scanning = True
        logger.info("Starting scheduled scan cycle")

        try:
            db_session = get_session(self.session_factory)
            scanner = IncrementalScanner(db_session)

            for server_config in self.config.servers:
                logger.info(
                    "Scanning server: %s (%s)",
                    server_config.server_name,
                    server_config.server_host,
                )
                for sub_app in server_config.sub_apps:
                    # Resolve paths using dedicated mount, relative, or pattern mode
                    resolved_paths = resolve_sub_app_paths(
                        server_config, sub_app
                    )
                    for full_path in resolved_paths:
                        try:
                            scanner.scan_sub_app(
                                server_name=server_config.server_name,
                                sub_app_name=sub_app.name,
                                directory_path=full_path,
                            )
                        except Exception as e:
                            logger.error(
                                "Error scanning sub-app %s on %s: %s",
                                sub_app.name,
                                server_config.server_name,
                                e,
                            )

            db_session.close()
            self._last_scan_time = datetime.utcnow()
            logger.info("Scheduled scan cycle complete")

        except Exception as e:
            logger.error("Scan cycle failed: %s", e)
        finally:
            self._is_scanning = False

    def start(self) -> None:
        """
        Start the scheduler with the configured interval.

        Runs an initial scan immediately, then schedules periodic scans.
        """
        interval_minutes = self.config.scan_interval_minutes

        # Add the recurring job
        self.scheduler.add_job(
            self._run_scan_cycle,
            "interval",
            minutes=interval_minutes,
            id="space_scan",
            name="NAS Space Scan",
            max_instances=1,
        )

        self.scheduler.start()
        logger.info(
            "Scan scheduler started with %d-minute interval",
            interval_minutes,
        )

        # Run the initial scan immediately
        self._run_scan_cycle()

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scan scheduler stopped")

    def trigger_scan_now(self, force_full: bool = False) -> None:
        """
        Trigger an immediate scan outside the normal schedule.

        Args:
            force_full: If True, force a full rescan instead of incremental
        """
        if self._is_scanning:
            logger.warning("Scan already in progress")
            return

        if force_full:
            # For forced full scan, use full scan mode
            self._is_scanning = True
            try:
                db_session = get_session(self.session_factory)
                scanner = IncrementalScanner(db_session)

                for server_config in self.config.servers:
                    for sub_app in server_config.sub_apps:
                        # Resolve paths using dedicated mount, relative, or pattern mode
                        resolved_paths = resolve_sub_app_paths(
                            server_config, sub_app
                        )
                        for full_path in resolved_paths:
                            try:
                                scanner.scan_sub_app(
                                    server_name=server_config.server_name,
                                    sub_app_name=sub_app.name,
                                    directory_path=full_path,
                                    force_full=True,
                                )
                            except Exception as e:
                                logger.error(
                                    "Error in forced full scan for %s: %s",
                                    sub_app.name,
                                    e,
                                )
                db_session.close()
                self._last_scan_time = datetime.utcnow()
            finally:
                self._is_scanning = False
        else:
            self._run_scan_cycle()
