"""
Generate demo/test data for Volume Anomaly Detection & Storage Forecaster.

Creates 1000+ file metadata entries across multiple dummy servers with
varying file sizes (1KB-500MB) and ages (1 day to 2 years). Also generates
historical space snapshots for growth prediction and scan results.

Usage:
    python -m server_space_optimizer.scripts.generate_demo_data
"""

import os
import random
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server_space_optimizer.models.database import (
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    SubAppCapacityPlan,
    SubAppConfigDB,
    init_database,
)

# Demo servers and sub-apps configuration
DEMO_SERVERS = {
    "prod-server-01": {
        "host": "10.0.1.100",
        "mount": "/mnt/nas/production",
        "sub_apps": {
            "billing-service": "/mnt/nas/production/billing",
            "payment-gateway": "/mnt/nas/production/payments",
            "application-logs": "/mnt/nas/production/logs",
        },
    },
    "prod-server-02": {
        "host": "10.0.1.101",
        "mount": "/mnt/shared_nas",
        "sub_apps": {
            "data-warehouse": "/mnt/shared_nas/warehouse",
            "reporting-service": "/mnt/shared_nas/reports",
            "batch-processing": "/mnt/shared_nas/batch",
        },
    },
    "staging-server-01": {
        "host": "10.0.2.50",
        "mount": "/mnt/staging_nas",
        "sub_apps": {
            "staging-apps": "/mnt/staging_nas/apps",
            "staging-data": "/mnt/staging_nas/data",
        },
    },
}

# File extensions with typical size ranges (min_bytes, max_bytes)
FILE_TYPES = [
    (".log", 1024, 500 * 1024 * 1024),         # 1KB - 500MB
    (".csv", 5 * 1024, 200 * 1024 * 1024),      # 5KB - 200MB
    (".json", 512, 50 * 1024 * 1024),            # 512B - 50MB
    (".xml", 1024, 100 * 1024 * 1024),           # 1KB - 100MB
    (".txt", 256, 10 * 1024 * 1024),             # 256B - 10MB
    (".dat", 10 * 1024, 500 * 1024 * 1024),      # 10KB - 500MB
    (".bak", 1024 * 1024, 500 * 1024 * 1024),    # 1MB - 500MB
    (".tmp", 512, 50 * 1024 * 1024),             # 512B - 50MB
    (".gz", 1024, 100 * 1024 * 1024),            # 1KB - 100MB
    (".tar", 10 * 1024, 200 * 1024 * 1024),      # 10KB - 200MB
    (".parquet", 50 * 1024, 300 * 1024 * 1024),  # 50KB - 300MB
    (".sql", 1024, 20 * 1024 * 1024),            # 1KB - 20MB
    (".conf", 128, 100 * 1024),                   # 128B - 100KB
    (".sh", 256, 50 * 1024),                      # 256B - 50KB
    (".py", 512, 200 * 1024),                     # 512B - 200KB
    (".jar", 100 * 1024, 100 * 1024 * 1024),     # 100KB - 100MB
    (".war", 1024 * 1024, 200 * 1024 * 1024),    # 1MB - 200MB
    (".pdf", 50 * 1024, 50 * 1024 * 1024),       # 50KB - 50MB
    (".bmp", 100 * 1024, 20 * 1024 * 1024),      # 100KB - 20MB
    (".wav", 500 * 1024, 100 * 1024 * 1024),     # 500KB - 100MB
]

# Subdirectory name pools for realistic paths
SUBDIRS = [
    "2024", "2025", "2026", "archive", "current", "backups", "temp",
    "reports", "exports", "imports", "daily", "monthly", "quarterly",
    "q1", "q2", "q3", "q4", "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

FILE_PREFIXES = [
    "transaction", "order", "invoice", "report", "summary", "audit",
    "extract", "backup", "snapshot", "dump", "data", "export", "import",
    "batch", "process", "output", "result", "analysis", "metric",
    "log", "error", "access", "system", "app", "service", "worker",
]


def random_file_path(base_path: str, ext: str) -> str:
    """Generate a realistic random file path."""
    depth = random.randint(0, 3)
    parts = [base_path]
    for _ in range(depth):
        parts.append(random.choice(SUBDIRS))
    prefix = random.choice(FILE_PREFIXES)
    suffix = random.randint(1000, 99999)
    filename = f"{prefix}_{suffix}{ext}"
    return os.path.join(*parts, filename)


def random_date_in_range(days_back_min: int, days_back_max: int) -> datetime:
    """Generate a random datetime between days_back_min and days_back_max days ago."""
    days = random.uniform(days_back_min, days_back_max)
    return datetime.utcnow() - timedelta(days=days)


def generate_files(db_session, target_count: int = 1200):
    """Generate random file metadata entries across all demo servers."""
    now = datetime.utcnow()
    files_per_subapp = target_count // sum(
        len(s["sub_apps"]) for s in DEMO_SERVERS.values()
    )
    total_generated = 0

    for server_name, server_info in DEMO_SERVERS.items():
        for sub_app_name, base_path in server_info["sub_apps"].items():
            # Vary the count per sub-app slightly for realism
            count = files_per_subapp + random.randint(-20, 40)
            sub_app_total_size = 0

            for _ in range(count):
                ext, min_size, max_size = random.choice(FILE_TYPES)
                # Use log-uniform distribution for sizes (more small files, fewer large)
                import math
                log_min = math.log(min_size)
                log_max = math.log(max_size)
                size = int(math.exp(random.uniform(log_min, log_max)))

                # File age: 1 day to 730 days (2 years)
                created = random_date_in_range(1, 730)
                # Last modified: between creation and now
                days_since_created = (now - created).days
                if days_since_created > 1:
                    modified = created + timedelta(
                        days=random.randint(0, min(days_since_created, 365))
                    )
                else:
                    modified = created
                # Last accessed: between modification and now
                days_since_modified = (now - modified).days
                if days_since_modified > 0:
                    accessed = modified + timedelta(
                        days=random.randint(0, days_since_modified)
                    )
                else:
                    accessed = modified

                fpath = random_file_path(base_path, ext)

                file_meta = FileMetadata(
                    server_name=server_name,
                    sub_app_name=sub_app_name,
                    file_path=fpath,
                    file_size_bytes=size,
                    file_extension=ext,
                    last_modified=modified,
                    last_accessed=accessed,
                    created_at=created,
                    last_scanned=now,
                    is_deleted=0,
                )
                db_session.add(file_meta)
                sub_app_total_size += size
                total_generated += 1

            # Create a scan result for this sub-app.
            # Use a future timestamp (+1 hour) to ensure demo data stays
            # as the "latest" scan result even if the scheduler runs on startup.
            demo_scan_time = now + timedelta(hours=1)
            scan_result = ScanResult(
                server_name=server_name,
                sub_app_name=sub_app_name,
                scan_timestamp=demo_scan_time,
                total_size_bytes=sub_app_total_size,
                total_file_count=count,
                total_dir_count=random.randint(5, 50),
                scan_type="full",
                scan_duration_seconds=random.uniform(0.5, 10.0),
            )
            db_session.add(scan_result)

            print(
                f"  {server_name}/{sub_app_name}: "
                f"{count} files, {sub_app_total_size / (1024*1024):.1f} MB"
            )

    db_session.commit()
    print(f"\nTotal files generated: {total_generated}")
    return total_generated


def generate_historical_snapshots(db_session, days_back: int = 90):
    """
    Generate historical space snapshots for growth prediction.

    Creates daily snapshots going back 'days_back' days with a
    realistic growth trend (slight daily increase with noise).
    """
    now = datetime.utcnow()
    total_snapshots = 0

    for server_name, server_info in DEMO_SERVERS.items():
        for sub_app_name in server_info["sub_apps"]:
            # Base size with growth trend
            base_size = random.uniform(5, 50) * 1024 * 1024 * 1024  # 5-50 GB
            daily_growth = base_size * random.uniform(0.001, 0.005)  # 0.1-0.5%/day
            base_files = random.randint(5000, 50000)
            daily_new_files = random.randint(5, 50)

            for day in range(days_back, 0, -1):
                ts = now - timedelta(days=day)
                # Apply growth with noise
                growth_factor = (days_back - day) * daily_growth
                noise = random.uniform(-0.02, 0.02) * base_size
                size = base_size + growth_factor + noise
                files = base_files + (days_back - day) * daily_new_files

                snapshot = SpaceSnapshot(
                    server_name=server_name,
                    sub_app_name=sub_app_name,
                    snapshot_timestamp=ts,
                    total_size_bytes=max(size, 0),
                    total_file_count=files,
                )
                db_session.add(snapshot)
                total_snapshots += 1

    db_session.commit()
    print(f"Historical snapshots generated: {total_snapshots}")
    return total_snapshots


def generate_sub_app_configs(db_session):
    """Seed the sub-app configurations into the database."""
    now = datetime.utcnow()
    count = 0
    for server_name, server_info in DEMO_SERVERS.items():
        for sub_app_name, path in server_info["sub_apps"].items():
            existing = (
                db_session.query(SubAppConfigDB)
                .filter(
                    SubAppConfigDB.server_name == server_name,
                    SubAppConfigDB.sub_app_name == sub_app_name,
                )
                .first()
            )
            if not existing:
                config = SubAppConfigDB(
                    server_name=server_name,
                    sub_app_name=sub_app_name,
                    path=path,
                    patterns="*.log,*.csv,*.dat",
                    is_dedicated_mount=0,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(config)
                count += 1
    db_session.commit()
    print(f"Sub-app configs seeded: {count}")


def main():
    """Main entry point: generate all demo data."""
    db_path = os.environ.get("DB_PATH", "space_optimizer.db")
    print(f"Generating demo data in: {db_path}")
    print("=" * 60)

    session_factory = init_database(db_path)
    db = session_factory()

    try:
        # Clear existing file metadata to regenerate fresh
        deleted = db.query(FileMetadata).delete()
        print(f"Cleared {deleted} existing file metadata entries")

        # Clear existing snapshots to regenerate
        deleted_snaps = db.query(SpaceSnapshot).delete()
        print(f"Cleared {deleted_snaps} existing snapshot entries")

        # Clear existing scan results
        deleted_scans = db.query(ScanResult).delete()
        print(f"Cleared {deleted_scans} existing scan result entries")

        # Clear existing capacity plans for fresh demo
        deleted_plans = db.query(SubAppCapacityPlan).delete()
        print(f"Cleared {deleted_plans} existing capacity plans")
        db.commit()

        print("\n--- Generating file metadata ---")
        generate_files(db, target_count=1200)

        print("\n--- Generating historical snapshots (90 days) ---")
        generate_historical_snapshots(db, days_back=90)

        print("\n--- Seeding sub-app configurations ---")
        generate_sub_app_configs(db)

        print("\n--- Seeding capacity plans ---")
        generate_capacity_plans(db)

        print("\n" + "=" * 60)
        print("Demo data generation complete!")
        print("You can now start the server and explore the dashboard.")
    finally:
        db.close()


def generate_capacity_plans(db):
    """
    Seed demo capacity plans for each sub-app with realistic consumption,
    growth rates, purge schedules, and monthly allocations.

    Each team has different consumption patterns:
    - billing-service: 10 GB/day, 10% growth, purge 50% at 7d + 50% at 30d
    - payment-gateway: 5 GB/day, 5% growth, purge 60% at 7d + 40% at 30d
    - data-warehouse: 20 GB/day, 8% growth, purge 30% at 30d + 70% at 60d
    """
    import json

    # Demo capacity plans with varied consumption patterns
    demo_plans = [
        {
            "server_name": "prod-server-01",
            "sub_app_name": "billing-service",
            "daily_consumption_gb": 10.0,
            "growth_rate_pct": 10.0,
            "purge_schedule": [{"pct": 50, "after_days": 7}, {"pct": 50, "after_days": 30}],
            "monthly_allocation_gb": 500.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "billing-team@company.com",
        },
        {
            "server_name": "prod-server-01",
            "sub_app_name": "payment-gateway",
            "daily_consumption_gb": 5.0,
            "growth_rate_pct": 5.0,
            "purge_schedule": [{"pct": 60, "after_days": 7}, {"pct": 40, "after_days": 30}],
            "monthly_allocation_gb": 300.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "payments-team@company.com",
        },
        {
            "server_name": "prod-server-01",
            "sub_app_name": "application-logs",
            "daily_consumption_gb": 15.0,
            "growth_rate_pct": 12.0,
            "purge_schedule": [{"pct": 70, "after_days": 7}, {"pct": 30, "after_days": 14}],
            "monthly_allocation_gb": 200.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "devops-team@company.com",
        },
        {
            "server_name": "prod-server-02",
            "sub_app_name": "data-warehouse",
            "daily_consumption_gb": 20.0,
            "growth_rate_pct": 8.0,
            "purge_schedule": [{"pct": 30, "after_days": 30}, {"pct": 70, "after_days": 60}],
            "monthly_allocation_gb": 800.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "data-team@company.com",
        },
        {
            "server_name": "prod-server-02",
            "sub_app_name": "reporting-service",
            "daily_consumption_gb": 8.0,
            "growth_rate_pct": 6.0,
            "purge_schedule": [{"pct": 50, "after_days": 14}, {"pct": 50, "after_days": 30}],
            "monthly_allocation_gb": 400.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "reporting-team@company.com",
        },
        {
            "server_name": "prod-server-02",
            "sub_app_name": "batch-processing",
            "daily_consumption_gb": 25.0,
            "growth_rate_pct": 15.0,
            "purge_schedule": [{"pct": 80, "after_days": 3}, {"pct": 20, "after_days": 7}],
            "monthly_allocation_gb": 600.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "batch-team@company.com",
        },
        {
            "server_name": "staging-server-01",
            "sub_app_name": "staging-apps",
            "daily_consumption_gb": 3.0,
            "growth_rate_pct": 3.0,
            "purge_schedule": [{"pct": 100, "after_days": 7}],
            "monthly_allocation_gb": 100.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "staging-team@company.com",
        },
        {
            "server_name": "staging-server-01",
            "sub_app_name": "staging-data",
            "daily_consumption_gb": 5.0,
            "growth_rate_pct": 5.0,
            "purge_schedule": [{"pct": 50, "after_days": 7}, {"pct": 50, "after_days": 14}],
            "monthly_allocation_gb": 150.0,
            "alert_threshold_pct": 80.0,
            "contact_email": "staging-team@company.com",
        },
    ]

    now = datetime.utcnow()
    count = 0
    for plan_data in demo_plans:
        plan = SubAppCapacityPlan(
            server_name=plan_data["server_name"],
            sub_app_name=plan_data["sub_app_name"],
            daily_consumption_gb=plan_data["daily_consumption_gb"],
            growth_rate_pct=plan_data["growth_rate_pct"],
            purge_schedule_json=json.dumps(plan_data["purge_schedule"]),
            monthly_allocation_gb=plan_data["monthly_allocation_gb"],
            alert_threshold_pct=plan_data["alert_threshold_pct"],
            contact_email=plan_data["contact_email"],
            created_at=now,
            updated_at=now,
        )
        db.add(plan)
        count += 1
    db.commit()
    print(f"Capacity plans seeded: {count}")


if __name__ == "__main__":
    main()
