"""
REST API routes for Volume Anomaly Detection & Storage Forecaster.

Provides endpoints for dashboard data, server/sub-app space details,
purge eligibility reports, growth predictions, scan management,
file extension analytics, dynamic sub-app config CRUD, cost estimation,
and mount path configuration.
"""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from server_space_optimizer.models.database import (
    AlertLog,
    AppSettings,
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    SubAppCapacityPlan,
    SubAppConfigDB,
    get_session,
    init_database,
)
from server_space_optimizer.models.schemas import (
    DashboardSummary,
    ScanStatusResponse,
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
    broken down by sub-application. Merges servers from both the
    YAML config file AND the database (SubAppConfigDB) so that
    servers added via the Settings UI are visible on all pages.
    """
    servers = []
    total_size = 0
    total_files = 0
    total_sub_apps = 0
    latest_scan_time = None
    # Track which server+sub-app combos we've already added from YAML
    seen_server_subapps = set()
    seen_servers = set()

    if _app_config is not None:
        for server_config in _app_config.servers:
            server_size = 0
            server_files = 0
            sub_app_infos = []
            seen_servers.add(server_config.server_name)

            for sub_app in server_config.sub_apps:
                seen_server_subapps.add(
                    (server_config.server_name, sub_app.name)
                )
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

    # ---- Merge in DB-added servers/sub-apps not already in YAML config ----
    # This ensures servers added via Settings UI appear on the dashboard.
    db_configs = (
        db.query(SubAppConfigDB)
        .order_by(SubAppConfigDB.server_name, SubAppConfigDB.sub_app_name)
        .all()
    )
    # Group DB configs by server
    db_server_map = {}
    for cfg in db_configs:
        key = (cfg.server_name, cfg.sub_app_name)
        if key not in seen_server_subapps:
            db_server_map.setdefault(cfg.server_name, []).append(cfg)

    for srv_name, cfg_list in db_server_map.items():
        if srv_name in seen_servers:
            # Server exists from YAML — append missing sub-apps to it
            existing_srv = next(
                (s for s in servers if s.server_name == srv_name), None
            )
            if existing_srv:
                for cfg in cfg_list:
                    latest_scan = (
                        db.query(ScanResult)
                        .filter(
                            ScanResult.server_name == srv_name,
                            ScanResult.sub_app_name == cfg.sub_app_name,
                        )
                        .order_by(ScanResult.scan_timestamp.desc())
                        .first()
                    )
                    if latest_scan:
                        sa_info = SubAppSpaceInfo(
                            sub_app_name=cfg.sub_app_name,
                            total_size_bytes=latest_scan.total_size_bytes,
                            total_size_human=format_size(latest_scan.total_size_bytes),
                            file_count=latest_scan.total_file_count,
                            dir_count=latest_scan.total_dir_count,
                            last_scan_time=latest_scan.scan_timestamp,
                        )
                        existing_srv.total_size_bytes += latest_scan.total_size_bytes
                        existing_srv.total_size_human = format_size(
                            existing_srv.total_size_bytes
                        )
                        existing_srv.total_file_count += latest_scan.total_file_count
                        total_size += latest_scan.total_size_bytes
                        total_files += latest_scan.total_file_count
                    else:
                        sa_info = SubAppSpaceInfo(
                            sub_app_name=cfg.sub_app_name,
                            total_size_bytes=0,
                            total_size_human="0 B",
                            file_count=0,
                            dir_count=0,
                        )
                    existing_srv.sub_apps.append(sa_info)
                    total_sub_apps += 1
        else:
            # Entirely new server from DB — create a new server entry
            srv_size = 0
            srv_files = 0
            sub_app_infos = []
            # Derive host/mount from the first config's path
            srv_host = cfg_list[0].server_name
            srv_mount = cfg_list[0].path or ""

            for cfg in cfg_list:
                latest_scan = (
                    db.query(ScanResult)
                    .filter(
                        ScanResult.server_name == srv_name,
                        ScanResult.sub_app_name == cfg.sub_app_name,
                    )
                    .order_by(ScanResult.scan_timestamp.desc())
                    .first()
                )
                if latest_scan:
                    sa_info = SubAppSpaceInfo(
                        sub_app_name=cfg.sub_app_name,
                        total_size_bytes=latest_scan.total_size_bytes,
                        total_size_human=format_size(latest_scan.total_size_bytes),
                        file_count=latest_scan.total_file_count,
                        dir_count=latest_scan.total_dir_count,
                        last_scan_time=latest_scan.scan_timestamp,
                    )
                    srv_size += latest_scan.total_size_bytes
                    srv_files += latest_scan.total_file_count
                    if (
                        latest_scan_time is None
                        or latest_scan.scan_timestamp > latest_scan_time
                    ):
                        latest_scan_time = latest_scan.scan_timestamp
                else:
                    sa_info = SubAppSpaceInfo(
                        sub_app_name=cfg.sub_app_name,
                        total_size_bytes=0,
                        total_size_human="0 B",
                        file_count=0,
                        dir_count=0,
                    )
                sub_app_infos.append(sa_info)
                total_sub_apps += 1

            latest_server_scan = (
                db.query(ScanResult)
                .filter(ScanResult.server_name == srv_name)
                .order_by(ScanResult.scan_timestamp.desc())
                .first()
            )

            server_info = ServerSpaceInfo(
                server_name=srv_name,
                server_host=srv_host,
                nas_mount_path=srv_mount,
                total_size_bytes=srv_size,
                total_size_human=format_size(srv_size),
                total_file_count=srv_files,
                sub_apps=sub_app_infos,
                last_scan_time=(
                    latest_server_scan.scan_timestamp
                    if latest_server_scan else None
                ),
                scan_type=(
                    latest_server_scan.scan_type
                    if latest_server_scan else "unknown"
                ),
            )
            servers.append(server_info)
            total_size += srv_size
            total_files += srv_files

    return DashboardSummary(
        total_servers=len(servers),
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
    limit: int = Query(50, description="Max candidates to return, default top 50"),
    db: Session = Depends(get_db),
):
    """
    Get purge eligibility report for files on a server.

    Returns files eligible for cleanup based on age thresholds,
    providing a holistic view of old files that can be safely purged.
    Supports limit parameter to cap the number of candidates shown
    (default 50), with full CSV export available on the frontend.
    """
    analyzer = PurgeAnalyzer(db)

    if threshold_days is not None:
        # Single threshold report with configurable limit
        report = analyzer.analyze_purge_candidates(
            server_name=server_name,
            sub_app_name=sub_app_name,
            threshold_days=threshold_days,
            limit=limit,
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

    Returns weekly, monthly, yearly, and 5-year growth predictions based
    on historical usage data analyzed via linear regression.
    """
    predictor = GrowthPredictor(db)

    if sub_app_name:
        report = predictor.predict_growth(server_name, sub_app_name)
        return report
    else:
        reports = predictor.predict_all_sub_apps(server_name)
        return {"server_name": server_name, "predictions": reports}


@router.get("/servers/{server_name}/purge-rate")
def get_purge_rate(
    server_name: str,
    sub_app_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Calculate the purge rate (space freed per day) based on file aging.

    Uses the difference between files entering purge eligibility
    thresholds over recent snapshots to estimate daily purgeable volume.
    Also returns net space forecasts (growth minus purge potential) for
    1 week, 1 month, 1 year, and 5 years.
    """
    analyzer = PurgeAnalyzer(db)
    predictor = GrowthPredictor(db)

    # Get purge data at multiple thresholds
    thresholds = _app_config.purge_thresholds_days if _app_config else [90, 180, 365]
    purge_reports = analyzer.get_purge_summary(
        server_name=server_name, thresholds=thresholds
    )

    # Estimate daily purge rate from the oldest threshold bucket
    total_purgeable = 0
    oldest_threshold = max(thresholds) if thresholds else 365
    for report in purge_reports:
        if report.threshold_days == oldest_threshold:
            total_purgeable = report.total_reclaimable_bytes

    # Daily purge rate: purgeable bytes divided by threshold period
    daily_purge_rate = total_purgeable / oldest_threshold if oldest_threshold > 0 else 0
    monthly_purge_rate = daily_purge_rate * 30

    # Get growth predictions for net forecast
    if sub_app_name:
        growth_report = predictor.predict_growth(server_name, sub_app_name)
        predictions = growth_report.predictions
        current_size = growth_report.current_size_bytes
    else:
        # Aggregate across all sub-apps
        all_reports = predictor.predict_all_sub_apps(server_name)
        current_size = sum(r.current_size_bytes for r in all_reports)
        # Aggregate predictions by period
        predictions = []
        periods = ["weekly", "monthly", "yearly", "five_year"]
        for period in periods:
            total_growth = sum(
                next(
                    (
                        p.predicted_growth_bytes
                        for p in r.predictions
                        if p.period == period
                    ),
                    0,
                )
                for r in all_reports
            )
            predictions.append(type("Pred", (), {
                "period": period,
                "predicted_growth_bytes": total_growth,
            }))

    # Calculate net forecasts: growth minus purge potential per period
    net_forecasts = {}
    period_days = {"weekly": 7, "monthly": 30, "yearly": 365, "five_year": 1825}
    for pred in predictions:
        days = period_days.get(pred.period, 0)
        purge_in_period = daily_purge_rate * days
        net_change = pred.predicted_growth_bytes - purge_in_period
        net_total = current_size + net_change
        net_forecasts[pred.period] = {
            "net_change_bytes": net_change,
            "net_change_human": format_size(abs(net_change)),
            "net_change_direction": "increase" if net_change > 0 else "decrease",
            "net_total_bytes": max(0, net_total),
            "net_total_human": format_size(max(0, net_total)),
        }

    return {
        "server_name": server_name,
        "current_size_bytes": current_size,
        "current_size_human": format_size(current_size),
        "daily_purge_rate_bytes": daily_purge_rate,
        "daily_purge_rate_human": format_size(daily_purge_rate),
        "monthly_purge_rate_bytes": monthly_purge_rate,
        "monthly_purge_rate_human": format_size(monthly_purge_rate),
        "total_purgeable_bytes": total_purgeable,
        "total_purgeable_human": format_size(total_purgeable),
        "net_forecasts": net_forecasts,
    }


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


@router.post("/agent/report")
def receive_agent_report(
    report: dict,
    db: Session = Depends(get_db),
):
    """
    Receive scan metrics from a remote Linux agent (shell or Python).

    Agents running on Linux servers POST their scan results here as JSON.
    Compatible with any client: curl from shell scripts, httpx from Python,
    or Java HttpClient from Tomcat/Spring servlets.
    The data is stored in the same database tables as local scans,
    making remote agents transparent to the dashboard and prediction engine.
    """
    from datetime import datetime

    # Extract fields from the agent report payload
    server_name = report.get("server_name", "unknown")
    sub_app_name = report.get("sub_app_name", "unknown")
    total_size = report.get("total_size_bytes", 0)
    file_count = report.get("file_count", 0)
    dir_count = report.get("dir_count", 0)
    scan_ts = report.get("scan_timestamp")
    now = datetime.fromisoformat(scan_ts) if scan_ts else datetime.utcnow()

    # Store scan result record for dashboard display
    scan_record = ScanResult(
        server_name=server_name,
        sub_app_name=sub_app_name,
        scan_timestamp=now,
        total_size_bytes=total_size,
        total_file_count=file_count,
        total_dir_count=dir_count,
        scan_type=report.get("scan_type", "agent"),
        scan_duration_seconds=0,
    )
    db.add(scan_record)

    # Store space snapshot for growth prediction regression
    snapshot = SpaceSnapshot(
        server_name=server_name,
        sub_app_name=sub_app_name,
        snapshot_timestamp=now,
        total_size_bytes=total_size,
        total_file_count=file_count,
    )
    db.add(snapshot)

    # Store file metadata if the agent included per-file details
    # Extract file extension from path for file extension analytics
    files_data = report.get("files", [])
    for fdata in files_data:
        fpath = fdata.get("path", "")
        _, ext = os.path.splitext(fpath)
        file_meta = FileMetadata(
            server_name=server_name,
            sub_app_name=sub_app_name,
            file_path=fpath,
            file_size_bytes=fdata.get("size_bytes", 0),
            file_extension=ext.lower() if ext else "",
            last_modified=datetime.fromisoformat(fdata["last_modified"]),
            last_accessed=datetime.fromisoformat(fdata["last_accessed"]),
            created_at=datetime.fromisoformat(fdata["created_at"]),
            last_scanned=now,
            is_deleted=0,
        )
        db.add(file_meta)

    db.commit()

    logger.info(
        "Agent report received: server=%s, sub_app=%s, size=%s, files=%d",
        server_name, sub_app_name, format_size(total_size), file_count,
    )

    return {
        "status": "accepted",
        "server_name": server_name,
        "sub_app_name": sub_app_name,
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
    from datetime import timedelta

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


# ========================================================================
# File Extension Analytics API
# ========================================================================

# Map of file extensions to human-readable format descriptions
EXTENSION_FORMATS = {
    ".log": "Log File",
    ".txt": "Plain Text",
    ".csv": "Comma-Separated Values",
    ".json": "JSON Data",
    ".xml": "XML Markup",
    ".yaml": "YAML Config",
    ".yml": "YAML Config",
    ".conf": "Configuration File",
    ".cfg": "Configuration File",
    ".ini": "INI Config",
    ".properties": "Java Properties",
    ".gz": "Gzip Compressed",
    ".tar": "Tar Archive",
    ".tar.gz": "Tar+Gzip Archive",
    ".zip": "ZIP Archive",
    ".bz2": "Bzip2 Compressed",
    ".xz": "XZ Compressed",
    ".7z": "7-Zip Archive",
    ".rar": "RAR Archive",
    ".pdf": "PDF Document",
    ".doc": "MS Word Document",
    ".docx": "MS Word Document (XML)",
    ".xls": "MS Excel Spreadsheet",
    ".xlsx": "MS Excel Spreadsheet (XML)",
    ".ppt": "MS PowerPoint",
    ".pptx": "MS PowerPoint (XML)",
    ".png": "PNG Image",
    ".jpg": "JPEG Image",
    ".jpeg": "JPEG Image",
    ".gif": "GIF Image",
    ".svg": "SVG Vector Image",
    ".bmp": "Bitmap Image",
    ".mp4": "MPEG-4 Video",
    ".avi": "AVI Video",
    ".wav": "WAV Audio",
    ".mp3": "MP3 Audio",
    ".dat": "Data File",
    ".bin": "Binary File",
    ".bak": "Backup File",
    ".tmp": "Temporary File",
    ".db": "Database File",
    ".sql": "SQL Script",
    ".py": "Python Script",
    ".java": "Java Source",
    ".class": "Java Bytecode",
    ".jar": "Java Archive",
    ".war": "Web App Archive",
    ".sh": "Shell Script",
    ".bat": "Batch Script",
    ".exe": "Windows Executable",
    ".dll": "Dynamic Link Library",
    ".so": "Shared Object",
    ".o": "Object File",
    ".parquet": "Parquet Columnar",
    ".avro": "Avro Serialized",
    ".orc": "ORC Columnar",
}

# Optimization recommendations keyed by extension or category
OPTIMIZATION_RULES = [
    {
        "extensions": [".log", ".txt", ".csv", ".json", ".xml", ".sql"],
        "condition": "uncompressed, older than 30 days, and larger than 100 MB",
        "recommendation": (
            "Compress with gzip/bzip2 to save 60-90% space. "
            "Example: gzip -9 filename.log"
        ),
        "severity": "high",
    },
    {
        "extensions": [".bak", ".tmp"],
        "condition": "backup/temp files older than 7 days",
        "recommendation": (
            "Remove old backup and temporary files. "
            "These are usually safe to delete after verification."
        ),
        "severity": "high",
    },
    {
        "extensions": [".log"],
        "condition": "log files older than 90 days",
        "recommendation": (
            "Implement log rotation and archival. "
            "Consider logrotate for automatic management."
        ),
        "severity": "medium",
    },
    {
        "extensions": [".dat", ".bin"],
        "condition": "large binary files with no recent access",
        "recommendation": (
            "Move to cold/archive storage if not accessed recently. "
            "Consider data lifecycle policies."
        ),
        "severity": "medium",
    },
    {
        "extensions": [".bmp", ".wav"],
        "condition": "uncompressed media formats",
        "recommendation": (
            "Convert BMP to PNG/JPEG, WAV to MP3/FLAC for significant "
            "space savings without quality loss."
        ),
        "severity": "low",
    },
    {
        "extensions": [".parquet", ".avro", ".orc"],
        "condition": "columnar data files",
        "recommendation": (
            "These are already optimized formats. Consider partitioning "
            "and lifecycle policies for old partitions."
        ),
        "severity": "info",
    },
]


@router.get("/extensions")
def get_file_extensions(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get unique file extensions with counts, sizes, and format descriptions.

    Queries file_metadata to aggregate by extension, then enriches with
    format descriptions and optimization recommendations.
    """
    query = db.query(
        FileMetadata.file_extension,
        func.count(FileMetadata.id).label("file_count"),
        func.sum(FileMetadata.file_size_bytes).label("total_size"),
        func.avg(FileMetadata.file_size_bytes).label("avg_size"),
        func.min(FileMetadata.last_modified).label("oldest_file"),
        func.max(FileMetadata.last_modified).label("newest_file"),
    ).filter(
        FileMetadata.is_deleted == 0,
    )

    if server_name:
        query = query.filter(FileMetadata.server_name == server_name)

    results = query.group_by(FileMetadata.file_extension).order_by(
        func.sum(FileMetadata.file_size_bytes).desc()
    ).all()

    extensions = []
    for row in results:
        ext = row.file_extension or "(no extension)"
        ext_lower = ext.lower()
        format_desc = EXTENSION_FORMATS.get(ext_lower, "Unknown Format")

        # Find applicable optimization recommendations
        recommendations = []
        for rule in OPTIMIZATION_RULES:
            if ext_lower in rule["extensions"]:
                recommendations.append({
                    "condition": rule["condition"],
                    "recommendation": rule["recommendation"],
                    "severity": rule["severity"],
                })

        extensions.append({
            "extension": ext,
            "format": format_desc,
            "file_count": row.file_count,
            "total_size_bytes": row.total_size or 0,
            "total_size_human": format_size(row.total_size or 0),
            "avg_size_bytes": row.avg_size or 0,
            "avg_size_human": format_size(row.avg_size or 0),
            "oldest_file": (
                row.oldest_file.isoformat() if row.oldest_file else None
            ),
            "newest_file": (
                row.newest_file.isoformat() if row.newest_file else None
            ),
            "recommendations": recommendations,
        })

    return {"extensions": extensions, "total_types": len(extensions)}


# ========================================================================
# Dynamic Sub-App Configuration CRUD API
# ========================================================================

class SubAppConfigRequest(BaseModel):
    """Request body for creating/updating a sub-app configuration."""
    server_name: str
    sub_app_name: str
    path: str = ""
    patterns: str = ""
    is_dedicated_mount: bool = False


@router.get("/config/sub-apps")
def list_sub_app_configs(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List all sub-app configurations stored in the database."""
    query = db.query(SubAppConfigDB)
    if server_name:
        query = query.filter(SubAppConfigDB.server_name == server_name)

    configs = query.order_by(
        SubAppConfigDB.server_name, SubAppConfigDB.sub_app_name
    ).all()

    return {
        "configs": [
            {
                "id": c.id,
                "server_name": c.server_name,
                "sub_app_name": c.sub_app_name,
                "path": c.path,
                "patterns": c.patterns,
                "is_dedicated_mount": bool(c.is_dedicated_mount),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in configs
        ]
    }


@router.post("/config/sub-apps")
def create_sub_app_config(
    config: SubAppConfigRequest,
    db: Session = Depends(get_db),
):
    """Create a new sub-app configuration entry in the database."""
    new_config = SubAppConfigDB(
        server_name=config.server_name,
        sub_app_name=config.sub_app_name,
        path=config.path,
        patterns=config.patterns,
        is_dedicated_mount=1 if config.is_dedicated_mount else 0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(new_config)
    db.commit()
    db.refresh(new_config)

    logger.info(
        "Sub-app config created: server=%s, sub_app=%s",
        config.server_name,
        config.sub_app_name,
    )

    return {
        "status": "created",
        "id": new_config.id,
        "server_name": new_config.server_name,
        "sub_app_name": new_config.sub_app_name,
    }


@router.put("/config/sub-apps/{config_id}")
def update_sub_app_config(
    config_id: int,
    config: SubAppConfigRequest,
    db: Session = Depends(get_db),
):
    """Update an existing sub-app configuration entry."""
    existing = db.query(SubAppConfigDB).filter(
        SubAppConfigDB.id == config_id
    ).first()

    if not existing:
        return {"status": "error", "message": "Configuration not found"}

    existing.server_name = config.server_name
    existing.sub_app_name = config.sub_app_name
    existing.path = config.path
    existing.patterns = config.patterns
    existing.is_dedicated_mount = 1 if config.is_dedicated_mount else 0
    existing.updated_at = datetime.utcnow()
    db.commit()

    logger.info("Sub-app config updated: id=%d", config_id)

    return {"status": "updated", "id": config_id}


@router.delete("/config/sub-apps/{config_id}")
def delete_sub_app_config(
    config_id: int,
    db: Session = Depends(get_db),
):
    """Delete a sub-app configuration entry."""
    existing = db.query(SubAppConfigDB).filter(
        SubAppConfigDB.id == config_id
    ).first()

    if not existing:
        return {"status": "error", "message": "Configuration not found"}

    db.delete(existing)
    db.commit()

    logger.info("Sub-app config deleted: id=%d", config_id)

    return {"status": "deleted", "id": config_id}


# ========================================================================
# Cost Estimation API
# ========================================================================

@router.get("/cost-estimation")
def get_cost_estimation(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get storage cost estimations based on configured dollar rate.

    Multiplies current and predicted space by cost_per_gb_month to
    produce financial forecasts for 1 week, 1 month, 1 year, 5 years.
    """
    # Read cost rate from DB settings or fall back to config
    cost_rate = _app_config.cost_per_gb_month if _app_config else 0.023
    rate_setting = db.query(AppSettings).filter(
        AppSettings.setting_key == "cost_per_gb_month"
    ).first()
    if rate_setting:
        try:
            cost_rate = float(rate_setting.setting_value)
        except ValueError:
            pass

    # Get current total size across all or specific server
    if server_name:
        size_result = db.query(
            func.sum(ScanResult.total_size_bytes)
        ).filter(
            ScanResult.server_name == server_name,
        ).scalar() or 0
    else:
        size_result = db.query(
            func.sum(ScanResult.total_size_bytes)
        ).scalar() or 0

    current_gb = size_result / (1024 ** 3)
    monthly_cost = current_gb * cost_rate

    # Get growth predictions for cost projection
    period_months = {
        "weekly": 7 / 30,
        "monthly": 1,
        "yearly": 12,
        "five_year": 60,
    }

    cost_forecasts = {}
    for period, months in period_months.items():
        projected_cost = monthly_cost * months
        cost_forecasts[period] = {
            "months": months,
            "estimated_cost": round(projected_cost, 2),
            "formatted": f"${projected_cost:,.2f}",
        }

    return {
        "cost_per_gb_month": cost_rate,
        "current_size_bytes": size_result,
        "current_size_gb": round(current_gb, 2),
        "current_size_human": format_size(size_result),
        "current_monthly_cost": round(monthly_cost, 2),
        "current_monthly_cost_formatted": f"${monthly_cost:,.2f}",
        "forecasts": cost_forecasts,
    }


# ========================================================================
# Application Settings API (cost rate, excluded mounts)
# ========================================================================

class SettingUpdate(BaseModel):
    """Request body for updating a setting."""
    value: str


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    """Get all application settings."""
    settings = db.query(AppSettings).all()
    result = {}
    for s in settings:
        result[s.setting_key] = s.setting_value

    # Include config defaults if not overridden in DB
    if "cost_per_gb_month" not in result:
        result["cost_per_gb_month"] = str(
            _app_config.cost_per_gb_month if _app_config else 0.023
        )
    if "excluded_mounts" not in result:
        result["excluded_mounts"] = ",".join(
            _app_config.excluded_mounts if _app_config else []
        )

    return {"settings": result}


@router.put("/settings/{key}")
def update_setting(
    key: str,
    update: SettingUpdate,
    db: Session = Depends(get_db),
):
    """Update a single application setting."""
    existing = db.query(AppSettings).filter(
        AppSettings.setting_key == key
    ).first()

    if existing:
        existing.setting_value = update.value
        existing.updated_at = datetime.utcnow()
    else:
        new_setting = AppSettings(
            setting_key=key,
            setting_value=update.value,
            updated_at=datetime.utcnow(),
        )
        db.add(new_setting)

    db.commit()
    logger.info("Setting updated: %s = %s", key, update.value)

    return {"status": "updated", "key": key, "value": update.value}


# ========================================================================
# Mount Path Configuration API
# ========================================================================

@router.get("/config/excluded-mounts")
def get_excluded_mounts(db: Session = Depends(get_db)):
    """Get the list of excluded system mount paths."""
    # Check DB override first
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == "excluded_mounts"
    ).first()

    if setting and setting.setting_value:
        mounts = [m.strip() for m in setting.setting_value.split(",") if m.strip()]
    else:
        mounts = _app_config.excluded_mounts if _app_config else []

    return {"excluded_mounts": mounts}


@router.put("/config/excluded-mounts")
def update_excluded_mounts(
    update: SettingUpdate,
    db: Session = Depends(get_db),
):
    """Update the list of excluded system mount paths."""
    existing = db.query(AppSettings).filter(
        AppSettings.setting_key == "excluded_mounts"
    ).first()

    if existing:
        existing.setting_value = update.value
        existing.updated_at = datetime.utcnow()
    else:
        new_setting = AppSettings(
            setting_key="excluded_mounts",
            setting_value=update.value,
            updated_at=datetime.utcnow(),
        )
        db.add(new_setting)

    db.commit()
    return {"status": "updated", "excluded_mounts": update.value.split(",")}


# ========================================================================
# Server & Sub-App Lookup API — for dropdown population in Settings page
# ========================================================================

@router.get("/config/servers")
def list_known_servers(db: Session = Depends(get_db)):
    """
    Return distinct server names from scan results and sub-app configs.

    Used by the Settings page to populate server name dropdowns so users
    can select from already-configured servers instead of typing manually.
    """
    # Gather server names from both scan_results and sub_app_configs tables
    scan_servers = db.query(ScanResult.server_name).distinct().all()
    config_servers = db.query(SubAppConfigDB.server_name).distinct().all()

    # Merge into a unique sorted list
    all_servers = sorted(set(
        row[0] for row in scan_servers + config_servers if row[0]
    ))
    return {"servers": all_servers}


@router.get("/config/sub-app-names")
def list_known_sub_apps(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return distinct sub-app names, optionally filtered by server.

    Used by Settings and Purge pages to populate sub-app dropdowns
    so users can pick from existing sub-apps instead of typing.
    """
    query = db.query(SubAppConfigDB.sub_app_name).distinct()
    if server_name:
        query = query.filter(SubAppConfigDB.server_name == server_name)
    config_names = query.all()

    # Also pull from scan_results for sub-apps not yet in configs
    scan_query = db.query(ScanResult.sub_app_name).distinct()
    if server_name:
        scan_query = scan_query.filter(ScanResult.server_name == server_name)
    scan_names = scan_query.all()

    all_names = sorted(set(
        row[0] for row in config_names + scan_names if row[0]
    ))
    return {"sub_apps": all_names}


# ========================================================================
# Sub-App Capacity Planning API
# Each sub-app team defines estimated daily consumption, growth rate,
# purge schedule, monthly allocation, and contact email for 80% alerts.
# ========================================================================

class CapacityPlanCreate(BaseModel):
    """Request body for creating/updating a capacity plan."""
    server_name: str
    sub_app_name: str
    daily_consumption_gb: float = 0.0
    growth_rate_pct: float = 0.0
    purge_schedule_json: str = "[]"
    monthly_allocation_gb: float = 0.0
    alert_threshold_pct: float = 80.0
    contact_email: str = ""


@router.get("/capacity-plans")
def list_capacity_plans(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List all sub-app capacity plans, optionally filtered by server.

    Returns each plan with its estimated consumption, growth rate,
    purge schedule, monthly allocation, and contact info.
    """
    query = db.query(SubAppCapacityPlan)
    if server_name:
        query = query.filter(SubAppCapacityPlan.server_name == server_name)

    plans = query.order_by(
        SubAppCapacityPlan.server_name,
        SubAppCapacityPlan.sub_app_name,
    ).all()

    result = []
    for p in plans:
        result.append({
            "id": p.id,
            "server_name": p.server_name,
            "sub_app_name": p.sub_app_name,
            "daily_consumption_gb": p.daily_consumption_gb,
            "growth_rate_pct": p.growth_rate_pct,
            "purge_schedule_json": p.purge_schedule_json,
            "monthly_allocation_gb": p.monthly_allocation_gb,
            "alert_threshold_pct": p.alert_threshold_pct,
            "contact_email": p.contact_email,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })
    return {"plans": result}


@router.post("/capacity-plans")
def create_capacity_plan(
    plan: CapacityPlanCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new capacity plan for a sub-app.

    Defines the team's estimated daily consumption, growth rate,
    purge schedule, monthly allocation, and alert contact email.
    """
    new_plan = SubAppCapacityPlan(
        server_name=plan.server_name,
        sub_app_name=plan.sub_app_name,
        daily_consumption_gb=plan.daily_consumption_gb,
        growth_rate_pct=plan.growth_rate_pct,
        purge_schedule_json=plan.purge_schedule_json,
        monthly_allocation_gb=plan.monthly_allocation_gb,
        alert_threshold_pct=plan.alert_threshold_pct,
        contact_email=plan.contact_email,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return {"message": "Capacity plan created", "id": new_plan.id}


@router.put("/capacity-plans/{plan_id}")
def update_capacity_plan(
    plan_id: int,
    plan: CapacityPlanCreate,
    db: Session = Depends(get_db),
):
    """
    Update an existing capacity plan by ID.

    Allows teams to adjust their consumption estimates, purge schedule,
    or monthly allocation as requirements change.
    """
    existing = db.query(SubAppCapacityPlan).filter(
        SubAppCapacityPlan.id == plan_id
    ).first()
    if not existing:
        return {"error": "Capacity plan not found"}, 404

    existing.server_name = plan.server_name
    existing.sub_app_name = plan.sub_app_name
    existing.daily_consumption_gb = plan.daily_consumption_gb
    existing.growth_rate_pct = plan.growth_rate_pct
    existing.purge_schedule_json = plan.purge_schedule_json
    existing.monthly_allocation_gb = plan.monthly_allocation_gb
    existing.alert_threshold_pct = plan.alert_threshold_pct
    existing.contact_email = plan.contact_email
    existing.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Capacity plan updated", "id": plan_id}


@router.delete("/capacity-plans/{plan_id}")
def delete_capacity_plan(
    plan_id: int,
    db: Session = Depends(get_db),
):
    """Delete a capacity plan by ID."""
    deleted = db.query(SubAppCapacityPlan).filter(
        SubAppCapacityPlan.id == plan_id
    ).delete()
    db.commit()
    return {"message": "Deleted", "count": deleted}


@router.get("/capacity-plans/status")
def get_capacity_status(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Check allocation usage status for all sub-apps with capacity plans.

    Compares current usage against monthly allocation and returns
    usage percentage. Flags sub-apps that have breached their
    alert_threshold_pct (default 80%).
    """
    query = db.query(SubAppCapacityPlan)
    if server_name:
        query = query.filter(SubAppCapacityPlan.server_name == server_name)
    plans = query.all()

    statuses = []
    for plan in plans:
        # Get latest scan result for this server+sub-app to find current usage
        latest_scan = (
            db.query(ScanResult)
            .filter(
                ScanResult.server_name == plan.server_name,
                ScanResult.sub_app_name == plan.sub_app_name,
            )
            .order_by(ScanResult.scan_timestamp.desc())
            .first()
        )
        current_bytes = latest_scan.total_size_bytes if latest_scan else 0
        current_gb = current_bytes / (1024 ** 3)
        usage_pct = (
            (current_gb / plan.monthly_allocation_gb * 100)
            if plan.monthly_allocation_gb > 0 else 0
        )
        # Check if usage has breached the alert threshold
        breached = usage_pct >= plan.alert_threshold_pct

        statuses.append({
            "plan_id": plan.id,
            "server_name": plan.server_name,
            "sub_app_name": plan.sub_app_name,
            "monthly_allocation_gb": plan.monthly_allocation_gb,
            "current_usage_gb": round(current_gb, 2),
            "usage_pct": round(usage_pct, 1),
            "alert_threshold_pct": plan.alert_threshold_pct,
            "breached": breached,
            "contact_email": plan.contact_email,
            "daily_consumption_gb": plan.daily_consumption_gb,
            "growth_rate_pct": plan.growth_rate_pct,
        })

    return {"statuses": statuses}


@router.post("/capacity-plans/check-alerts")
def check_and_send_alerts(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Check all capacity plans for threshold breaches and queue alert emails.

    Compares current usage against each plan's monthly_allocation_gb.
    If usage >= alert_threshold_pct (default 80%), queues an email
    to the plan's contact_email. Avoids duplicate alerts by checking
    the alert_logs table — only sends if no alert was sent in the last 24h.
    """
    import json

    plans = db.query(SubAppCapacityPlan).all()
    alerts_queued = 0

    for plan in plans:
        if not plan.contact_email or plan.monthly_allocation_gb <= 0:
            continue

        # Get current usage from latest scan result
        latest_scan = (
            db.query(ScanResult)
            .filter(
                ScanResult.server_name == plan.server_name,
                ScanResult.sub_app_name == plan.sub_app_name,
            )
            .order_by(ScanResult.scan_timestamp.desc())
            .first()
        )
        if not latest_scan:
            continue

        current_gb = latest_scan.total_size_bytes / (1024 ** 3)
        usage_pct = current_gb / plan.monthly_allocation_gb * 100

        if usage_pct < plan.alert_threshold_pct:
            continue

        # Check if we already sent an alert in the last 24 hours
        from datetime import timedelta
        recent_alert = (
            db.query(AlertLog)
            .filter(
                AlertLog.server_name == plan.server_name,
                AlertLog.sub_app_name == plan.sub_app_name,
                AlertLog.alert_type == "threshold_80",
                AlertLog.created_at >= datetime.utcnow() - timedelta(hours=24),
            )
            .first()
        )
        if recent_alert:
            continue

        # Queue the alert email in background
        background_tasks.add_task(
            _send_threshold_alert,
            db_path=os.environ.get("DB_PATH", "space_optimizer.db"),
            server_name=plan.server_name,
            sub_app_name=plan.sub_app_name,
            contact_email=plan.contact_email,
            current_gb=round(current_gb, 2),
            allocation_gb=plan.monthly_allocation_gb,
            usage_pct=round(usage_pct, 1),
        )
        alerts_queued += 1

    return {"message": f"Alert check complete, {alerts_queued} alerts queued"}


def _send_threshold_alert(
    db_path: str,
    server_name: str,
    sub_app_name: str,
    contact_email: str,
    current_gb: float,
    allocation_gb: float,
    usage_pct: float,
):
    """
    Send an allocation threshold alert email and log the result.

    Uses Python's built-in smtplib for email delivery. Falls back
    to logging the alert if SMTP is not configured. Logs the alert
    in the alert_logs table regardless of delivery status.
    """
    import smtplib
    from email.mime.text import MIMEText

    # Build the alert email content
    subject = (
        f"[ALERT] Storage threshold reached: {sub_app_name} "
        f"on {server_name} ({usage_pct}%)"
    )
    body = (
        f"Storage Alert - Volume Anomaly Detection & Storage Forecaster\n"
        f"{'=' * 60}\n\n"
        f"Sub-Application: {sub_app_name}\n"
        f"Server: {server_name}\n"
        f"Current Usage: {current_gb} GB\n"
        f"Monthly Allocation: {allocation_gb} GB\n"
        f"Usage: {usage_pct}%\n\n"
        f"The storage usage for '{sub_app_name}' has reached "
        f"{usage_pct}% of its monthly allocation ({allocation_gb} GB).\n\n"
        f"Please review the storage consumption and consider:\n"
        f"  - Running a purge cycle for old/stale files\n"
        f"  - Requesting an allocation increase\n"
        f"  - Reviewing the purge schedule configuration\n\n"
        f"This is an automated alert from VADSF.\n"
    )

    sent_success = 0
    try:
        # Attempt SMTP delivery using environment-configured server
        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        smtp_from = os.environ.get("SMTP_FROM", "vadsf-alerts@localhost")

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = contact_email

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.sendmail(smtp_from, [contact_email], msg.as_string())
            sent_success = 1
            logger.info("Alert email sent to %s for %s/%s",
                        contact_email, server_name, sub_app_name)
    except Exception as e:
        # Log the failure but don't crash — alerts are best-effort
        logger.warning(
            "Failed to send alert email to %s: %s (alert logged anyway)",
            contact_email, e,
        )

    # Log the alert in the database regardless of send status
    try:
        session_factory = init_database(db_path)
        db = session_factory()
        alert_log = AlertLog(
            server_name=server_name,
            sub_app_name=sub_app_name,
            alert_type="threshold_80",
            current_usage_gb=current_gb,
            allocation_gb=allocation_gb,
            usage_pct=usage_pct,
            sent_to_email=contact_email,
            sent_success=sent_success,
            created_at=datetime.utcnow(),
        )
        db.add(alert_log)
        db.commit()
        db.close()
    except Exception as e:
        logger.error("Failed to log alert: %s", e)


@router.get("/alert-logs")
def get_alert_logs(
    server_name: Optional[str] = Query(None),
    sub_app_name: Optional[str] = Query(None),
    limit: int = Query(50, description="Max logs to return"),
    db: Session = Depends(get_db),
):
    """
    Retrieve alert log history for auditing threshold notifications.
    """
    query = db.query(AlertLog)
    if server_name:
        query = query.filter(AlertLog.server_name == server_name)
    if sub_app_name:
        query = query.filter(AlertLog.sub_app_name == sub_app_name)

    logs = query.order_by(AlertLog.created_at.desc()).limit(limit).all()
    return {
        "logs": [
            {
                "id": log.id,
                "server_name": log.server_name,
                "sub_app_name": log.sub_app_name,
                "alert_type": log.alert_type,
                "current_usage_gb": log.current_usage_gb,
                "allocation_gb": log.allocation_gb,
                "usage_pct": log.usage_pct,
                "sent_to_email": log.sent_to_email,
                "sent_success": bool(log.sent_success),
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]
    }


# ========================================================================
# Combined Growth / Purge / Forecast chart data for Dashboard
# Returns time-series data spanning past 1 year to future 5 years
# with separate series for growth (green), purge (red), forecast (blue)
# ========================================================================

@router.get("/chart/growth-purge-forecast")
def get_combined_chart_data(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return combined growth, purge, and forecast time-series data
    for the dashboard chart. Spans past 1 year to future 5 years.

    - Growth (green): historical space snapshots aggregated monthly
    - Purge (red): estimated purgeable space at each time point
    - Forecast (dotted blue): projected total space using linear regression
    """
    from datetime import timedelta
    import json

    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)

    # ---- Historical growth data (past 1 year, monthly aggregation) ----
    snapshots_query = db.query(SpaceSnapshot).filter(
        SpaceSnapshot.snapshot_timestamp >= one_year_ago,
    )
    if server_name:
        snapshots_query = snapshots_query.filter(
            SpaceSnapshot.server_name == server_name
        )
    snapshots = snapshots_query.order_by(
        SpaceSnapshot.snapshot_timestamp.asc()
    ).all()

    # Aggregate by month
    monthly_totals = {}
    for snap in snapshots:
        month_key = snap.snapshot_timestamp.strftime("%Y-%m")
        if month_key not in monthly_totals:
            monthly_totals[month_key] = {"size": 0, "count": 0}
        monthly_totals[month_key]["size"] += snap.total_size_bytes
        monthly_totals[month_key]["count"] += 1
    # Average per month (since multiple sub-apps contribute multiple rows)
    growth_labels = sorted(monthly_totals.keys())
    growth_values = []
    for k in growth_labels:
        avg = monthly_totals[k]["size"] / max(monthly_totals[k]["count"], 1)
        growth_values.append(avg)

    # ---- Purge eligible data (estimate at each historical point) ----
    # For each month, estimate how much was purgeable (files > 90 days old)
    purge_values = []
    for month_str in growth_labels:
        # Parse month and estimate purgeable at that point
        year, month = month_str.split("-")
        month_date = datetime(int(year), int(month), 15)
        cutoff = month_date - timedelta(days=90)
        purge_query = db.query(
            func.sum(FileMetadata.file_size_bytes)
        ).filter(
            FileMetadata.is_deleted == 0,
            FileMetadata.last_modified < cutoff,
        )
        if server_name:
            purge_query = purge_query.filter(
                FileMetadata.server_name == server_name
            )
        purge_total = purge_query.scalar() or 0
        purge_values.append(purge_total)

    # ---- Forecast (future 5 years using linear regression) ----
    # Use the last 3 months of historical data for slope estimation
    forecast_labels = []
    forecast_values = []
    if len(growth_values) >= 2:
        # Simple linear slope from last data points
        recent_values = growth_values[-min(6, len(growth_values)):]
        monthly_growth = 0
        if len(recent_values) >= 2:
            monthly_growth = (recent_values[-1] - recent_values[0]) / max(
                len(recent_values) - 1, 1
            )
        last_value = growth_values[-1] if growth_values else 0
        # Project 60 months into the future (5 years)
        for i in range(1, 61):
            future_date = now + timedelta(days=30 * i)
            forecast_labels.append(future_date.strftime("%Y-%m"))
            projected = last_value + monthly_growth * i
            forecast_values.append(max(projected, 0))

    # ---- Purge forecast (projected purgeable space in the future) ----
    purge_forecast_values = []
    last_purge = purge_values[-1] if purge_values else 0
    purge_growth_rate = 0
    if len(purge_values) >= 2:
        recent_purge = purge_values[-min(6, len(purge_values)):]
        purge_growth_rate = (recent_purge[-1] - recent_purge[0]) / max(
            len(recent_purge) - 1, 1
        )
    for i in range(1, 61):
        projected_purge = last_purge + purge_growth_rate * i
        purge_forecast_values.append(max(projected_purge, 0))

    return {
        "labels": growth_labels + forecast_labels,
        "growth": {
            "historical_labels": growth_labels,
            "historical_values": growth_values,
        },
        "purge": {
            "historical_labels": growth_labels,
            "historical_values": purge_values,
            "forecast_labels": forecast_labels,
            "forecast_values": purge_forecast_values,
        },
        "forecast": {
            "labels": forecast_labels,
            "values": forecast_values,
        },
    }


# ========================================================================
# Purge History Summary — shows purgeable amounts at 1w/1m/1y/5y
# ========================================================================

@router.get("/purge-history-summary")
def get_purge_history_summary(
    server_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return purge eligibility summaries for multiple time horizons.

    Shows how much data was/is eligible for purging at:
    - 1 week (7 days)
    - 1 month (30 days)
    - 1 year (365 days)
    - 5 years (1825 days)

    Also returns monthly purge-eligible totals for chart rendering.
    """
    from datetime import timedelta

    now = datetime.utcnow()
    periods = [
        {"label": "1 Week", "days": 7},
        {"label": "1 Month", "days": 30},
        {"label": "1 Year", "days": 365},
        {"label": "5 Years", "days": 1825},
    ]

    summaries = []
    for period in periods:
        cutoff = now - timedelta(days=period["days"])
        query = db.query(
            func.count(FileMetadata.id),
            func.sum(FileMetadata.file_size_bytes),
        ).filter(
            FileMetadata.is_deleted == 0,
            FileMetadata.last_modified < cutoff,
        )
        if server_name:
            query = query.filter(FileMetadata.server_name == server_name)
        result = query.first()
        count = result[0] or 0
        total_bytes = result[1] or 0
        summaries.append({
            "label": period["label"],
            "threshold_days": period["days"],
            "file_count": count,
            "total_bytes": total_bytes,
            "total_human": format_size(total_bytes),
        })

    # Monthly purge-eligible trend (for chart) — last 12 months
    monthly_purge = []
    for months_ago in range(12, 0, -1):
        month_date = now - timedelta(days=30 * months_ago)
        cutoff = month_date - timedelta(days=90)
        query = db.query(
            func.sum(FileMetadata.file_size_bytes)
        ).filter(
            FileMetadata.is_deleted == 0,
            FileMetadata.last_modified < cutoff,
        )
        if server_name:
            query = query.filter(FileMetadata.server_name == server_name)
        total = query.scalar() or 0
        monthly_purge.append({
            "month": month_date.strftime("%Y-%m"),
            "purgeable_bytes": total,
            "purgeable_human": format_size(total),
        })

    return {
        "summaries": summaries,
        "monthly_trend": monthly_purge,
    }
