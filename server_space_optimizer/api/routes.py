"""
REST API routes for the Server Space Optimizer web interface.

Provides endpoints for dashboard data, server/sub-app space details,
purge eligibility reports, growth predictions, and scan management.
All endpoints return JSON for consumption by the frontend dashboard.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from server_space_optimizer.models.database import (
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    get_session,
)
from server_space_optimizer.models.schemas import (
    DashboardSummary,
    ScanStatusResponse,
    ServerGrowthReport,
    ServerSpaceInfo,
    SubAppSpaceInfo,
)
from server_space_optimizer.predictor.growth_predictor import GrowthPredictor
from server_space_optimizer.scanner.purge_analyzer import PurgeAnalyzer
from server_space_optimizer.scanner.space_calculator import format_size

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["space-optimizer"])

# These will be set by the main app module during startup
_session_factory = None
_scan_scheduler = None
_app_config = None


def set_dependencies(session_factory, scan_scheduler, app_config):
    """Inject dependencies from the main application module."""
    global _session_factory, _scan_scheduler, _app_config
    _session_factory = session_factory
    _scan_scheduler = scan_scheduler
    _app_config = app_config


def get_db() -> Session:
    """Get a database session for request handling."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    session = get_session(_session_factory)
    try:
        yield session
    finally:
        session.close()


@router.get("/dashboard", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Get the main dashboard summary with all servers and sub-apps.

    Returns aggregate space usage across all configured servers,
    broken down by sub-application.
    """
    servers = []
    total_size = 0
    total_files = 0
    total_sub_apps = 0
    latest_scan_time = None

    if _app_config is None:
        return DashboardSummary(
            total_servers=0,
            total_sub_apps=0,
            total_size_bytes=0,
            total_size_human="0 B",
            total_file_count=0,
            servers=[],
        )

    for server_config in _app_config.servers:
        server_size = 0
        server_files = 0
        sub_app_infos = []

        for sub_app in server_config.sub_apps:
            # Get the latest scan result for this sub-app
            latest_scan = (
                db.query(ScanResult)
                .filter(
                    ScanResult.server_name == server_config.server_name,
                    ScanResult.sub_app_name == sub_app.name,
                )
                .order_by(ScanResult.scan_timestamp.desc())
                .first()
            )

            if latest_scan:
                sub_app_info = SubAppSpaceInfo(
                    sub_app_name=sub_app.name,
                    total_size_bytes=latest_scan.total_size_bytes,
                    total_size_human=format_size(latest_scan.total_size_bytes),
                    file_count=latest_scan.total_file_count,
                    dir_count=latest_scan.total_dir_count,
                    last_scan_time=latest_scan.scan_timestamp,
                )
                server_size += latest_scan.total_size_bytes
                server_files += latest_scan.total_file_count

                # Track the most recent scan time globally
                if (
                    latest_scan_time is None
                    or latest_scan.scan_timestamp > latest_scan_time
                ):
                    latest_scan_time = latest_scan.scan_timestamp
            else:
                sub_app_info = SubAppSpaceInfo(
                    sub_app_name=sub_app.name,
                    total_size_bytes=0,
                    total_size_human="0 B",
                    file_count=0,
                    dir_count=0,
                )

            sub_app_infos.append(sub_app_info)
            total_sub_apps += 1

        # Get the latest scan type for this server
        latest_server_scan = (
            db.query(ScanResult)
            .filter(ScanResult.server_name == server_config.server_name)
            .order_by(ScanResult.scan_timestamp.desc())
            .first()
        )

        server_info = ServerSpaceInfo(
            server_name=server_config.server_name,
            server_host=server_config.server_host,
            nas_mount_path=server_config.nas_mount_path,
            total_size_bytes=server_size,
            total_size_human=format_size(server_size),
            total_file_count=server_files,
            sub_apps=sub_app_infos,
            last_scan_time=(
                latest_server_scan.scan_timestamp if latest_server_scan else None
            ),
            scan_type=(
                latest_server_scan.scan_type if latest_server_scan else "unknown"
            ),
        )
        servers.append(server_info)

        total_size += server_size
        total_files += server_files

    return DashboardSummary(
        total_servers=len(_app_config.servers),
        total_sub_apps=total_sub_apps,
        total_size_bytes=total_size,
        total_size_human=format_size(total_size),
        total_file_count=total_files,
        servers=servers,
        last_scan_time=latest_scan_time,
    )


@router.get("/servers/{server_name}/space")
def get_server_space(server_name: str, db: Session = Depends(get_db)):
    """Get detailed space breakdown for a specific server."""
    # Get latest scan results grouped by sub-app
    sub_apps = (
        db.query(
            ScanResult.sub_app_name,
            func.max(ScanResult.scan_timestamp).label("latest"),
        )
        .filter(ScanResult.server_name == server_name)
        .group_by(ScanResult.sub_app_name)
        .all()
    )

    results = []
    for sub_app_name, latest_ts in sub_apps:
        scan = (
            db.query(ScanResult)
            .filter(
                ScanResult.server_name == server_name,
                ScanResult.sub_app_name == sub_app_name,
                ScanResult.scan_timestamp == latest_ts,
            )
            .first()
        )
        if scan:
            results.append(
                SubAppSpaceInfo(
                    sub_app_name=scan.sub_app_name,
                    total_size_bytes=scan.total_size_bytes,
                    total_size_human=format_size(scan.total_size_bytes),
                    file_count=scan.total_file_count,
                    dir_count=scan.total_dir_count,
                    last_scan_time=scan.scan_timestamp,
                )
            )

    return {"server_name": server_name, "sub_apps": results}


@router.get("/servers/{server_name}/purge")
def get_purge_report(
    server_name: str,
    sub_app_name: Optional[str] = Query(None),
    threshold_days: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get purge eligibility report for files on a server.

    Returns files eligible for cleanup based on age thresholds,
    providing a holistic view of old files that can be safely purged.
    """
    analyzer = PurgeAnalyzer(db)

    if threshold_days is not None:
        # Single threshold report
        report = analyzer.analyze_purge_candidates(
            server_name=server_name,
            sub_app_name=sub_app_name,
            threshold_days=threshold_days,
        )
        return report
    else:
        # Multi-threshold summary using configured thresholds
        thresholds = (
            _app_config.purge_thresholds_days if _app_config else [90, 180, 365]
        )
        reports = analyzer.get_purge_summary(
            server_name=server_name,
            thresholds=thresholds,
        )
        return {"server_name": server_name, "purge_reports": reports}


@router.get("/servers/{server_name}/predictions")
def get_growth_predictions(
    server_name: str,
    sub_app_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get volume growth predictions for a server's sub-applications.

    Returns weekly, monthly, and yearly growth predictions based on
    historical usage data analyzed via linear regression.
    """
    predictor = GrowthPredictor(db)

    if sub_app_name:
        report = predictor.predict_growth(server_name, sub_app_name)
        return report
    else:
        reports = predictor.predict_all_sub_apps(server_name)
        return {"server_name": server_name, "predictions": reports}


@router.get("/scan/status", response_model=ScanStatusResponse)
def get_scan_status():
    """Get the current scan status and schedule information."""
    return ScanStatusResponse(
        is_scanning=_scan_scheduler.is_scanning if _scan_scheduler else False,
        last_scan_time=(
            _scan_scheduler.last_scan_time if _scan_scheduler else None
        ),
        next_scan_time=(
            _scan_scheduler.next_scan_time if _scan_scheduler else None
        ),
        scan_interval_minutes=(
            _app_config.scan_interval_minutes if _app_config else 60
        ),
        servers_configured=len(_app_config.servers) if _app_config else 0,
    )


@router.post("/scan/trigger")
def trigger_scan(
    force_full: bool = Query(False),
    background_tasks: BackgroundTasks = None,
):
    """
    Manually trigger a scan outside the normal schedule.

    Runs the scan in a background task so the HTTP response returns
    immediately, allowing the frontend to poll for status updates.
    Set force_full=true to perform a complete rescan instead of
    incremental mode.
    """
    if _scan_scheduler is None:
        return {"status": "error", "message": "Scheduler not initialized"}

    if _scan_scheduler.is_scanning:
        return {"status": "busy", "message": "A scan is already in progress"}

    # Run scan in background so the response returns immediately
    background_tasks.add_task(_scan_scheduler.trigger_scan_now, force_full=force_full)
    return {
        "status": "started",
        "scan_type": "full" if force_full else "incremental",
        "message": "Scan triggered successfully",
    }


@router.get("/servers/{server_name}/history")
def get_space_history(
    server_name: str,
    sub_app_name: Optional[str] = Query(None),
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    """
    Get historical space usage data for charts and trend analysis.

    Returns time-series data of space snapshots for the specified period.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(SpaceSnapshot).filter(
        SpaceSnapshot.server_name == server_name,
        SpaceSnapshot.snapshot_timestamp >= cutoff,
    )

    if sub_app_name:
        query = query.filter(SpaceSnapshot.sub_app_name == sub_app_name)

    snapshots = query.order_by(SpaceSnapshot.snapshot_timestamp.asc()).all()

    return {
        "server_name": server_name,
        "sub_app_name": sub_app_name,
        "history": [
            {
                "timestamp": snap.snapshot_timestamp.isoformat(),
                "size_bytes": snap.total_size_bytes,
                "size_human": format_size(snap.total_size_bytes),
                "file_count": snap.total_file_count,
                "sub_app_name": snap.sub_app_name,
            }
            for snap in snapshots
        ],
    }
