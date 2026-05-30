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
    AppSettings,
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    SubAppConfigDB,
    get_session,
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
        "current_size_gb": round(current_gb, 2),
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
