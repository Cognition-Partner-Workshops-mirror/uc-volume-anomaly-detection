"""
Purge eligibility analyzer for identifying old files.

Analyzes stored file metadata to identify files that haven't been
accessed or modified beyond configurable age thresholds, providing
a holistic view of files eligible for cleanup to reclaim disk space.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from server_space_optimizer.models.database import FileMetadata
from server_space_optimizer.models.schemas import PurgeCandidate, PurgeReport
from server_space_optimizer.scanner.space_calculator import format_size

logger = logging.getLogger(__name__)


class PurgeAnalyzer:
    """
    Identifies files eligible for purging based on age thresholds.

    Files are ranked by size (largest first) within each threshold
    to prioritize the most impactful cleanups.
    """

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def analyze_purge_candidates(
        self,
        server_name: str,
        sub_app_name: str | None = None,
        threshold_days: int = 90,
        limit: int = 500,
    ) -> PurgeReport:
        """
        Find files eligible for purging based on last modification date.

        Args:
            server_name: Server to analyze
            sub_app_name: Optional sub-app filter (None = all sub-apps)
            threshold_days: Files older than this many days are flagged
            limit: Maximum number of candidates to return

        Returns:
            PurgeReport with candidates sorted by file size (largest first)
        """
        now = datetime.utcnow()
        cutoff_date = now - timedelta(days=threshold_days)

        # Build the query for files older than the threshold
        query = self.db_session.query(FileMetadata).filter(
            FileMetadata.server_name == server_name,
            FileMetadata.is_deleted == 0,
            FileMetadata.last_modified < cutoff_date,
        )

        if sub_app_name:
            query = query.filter(FileMetadata.sub_app_name == sub_app_name)

        # Sort by size descending (largest files first for max impact)
        query = query.order_by(FileMetadata.file_size_bytes.desc())

        # Get total count and reclaimable space before applying limit
        total_query = self.db_session.query(
            func.count(FileMetadata.id),
            func.sum(FileMetadata.file_size_bytes),
        ).filter(
            FileMetadata.server_name == server_name,
            FileMetadata.is_deleted == 0,
            FileMetadata.last_modified < cutoff_date,
        )

        if sub_app_name:
            total_query = total_query.filter(
                FileMetadata.sub_app_name == sub_app_name
            )

        totals = total_query.first()
        total_candidates = totals[0] or 0
        total_reclaimable = totals[1] or 0

        # Fetch the top candidates
        candidates = []
        for file_meta in query.limit(limit).all():
            days_since_modified = (now - file_meta.last_modified).days
            days_since_accessed = (now - file_meta.last_accessed).days
            candidate = PurgeCandidate(
                file_path=file_meta.file_path,
                file_size_bytes=file_meta.file_size_bytes,
                file_size_human=format_size(file_meta.file_size_bytes),
                last_modified=file_meta.last_modified,
                last_accessed=file_meta.last_accessed,
                days_since_modified=days_since_modified,
                days_since_accessed=days_since_accessed,
                sub_app_name=file_meta.sub_app_name,
                server_name=file_meta.server_name,
            )
            candidates.append(candidate)

        logger.info(
            "Purge analysis: server=%s, threshold=%d days, "
            "candidates=%d, reclaimable=%s",
            server_name,
            threshold_days,
            total_candidates,
            format_size(total_reclaimable),
        )

        return PurgeReport(
            threshold_days=threshold_days,
            total_candidates=total_candidates,
            total_reclaimable_bytes=total_reclaimable,
            total_reclaimable_human=format_size(total_reclaimable),
            candidates=candidates,
        )

    def get_purge_summary(
        self,
        server_name: str,
        thresholds: list[int] | None = None,
    ) -> list[PurgeReport]:
        """
        Generate purge reports for multiple age thresholds.

        Provides a holistic view of files eligible for cleanup at
        different age brackets (e.g., 90 days, 180 days, 365 days).

        Args:
            server_name: Server to analyze
            thresholds: List of day thresholds (default: [90, 180, 365])

        Returns:
            List of PurgeReport objects, one per threshold
        """
        if thresholds is None:
            thresholds = [90, 180, 365]

        reports = []
        for threshold in sorted(thresholds):
            report = self.analyze_purge_candidates(
                server_name=server_name,
                threshold_days=threshold,
            )
            reports.append(report)

        return reports
