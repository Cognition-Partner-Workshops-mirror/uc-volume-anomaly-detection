"""
Tests for the Server Space Optimizer core modules.

Validates space calculation, incremental scanning, path resolution,
purge analysis, growth prediction, and configuration loading.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from server_space_optimizer.config import (
    AppConfig,
    ServerConfig,
    SubAppConfig,
    load_config,
)
from server_space_optimizer.models.database import (
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    get_session,
    init_database,
)
from server_space_optimizer.scanner.space_calculator import (
    format_size,
    scan_directory_recursive,
    scan_files_since,
)
from server_space_optimizer.scanner.path_resolver import resolve_sub_app_paths
from server_space_optimizer.scanner.incremental_scanner import IncrementalScanner
from server_space_optimizer.scanner.purge_analyzer import PurgeAnalyzer
from server_space_optimizer.predictor.growth_predictor import GrowthPredictor


# ===========================================================
# Fixtures for creating temporary test directories and database
# ===========================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory structure for testing scans."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create sub-app directories with test files
        sub_app1 = os.path.join(tmpdir, "billing")
        sub_app2 = os.path.join(tmpdir, "payments")
        sub_app3 = os.path.join(tmpdir, "logs_2024")
        sub_app4 = os.path.join(tmpdir, "logs_2025")
        os.makedirs(sub_app1)
        os.makedirs(sub_app2)
        os.makedirs(sub_app3)
        os.makedirs(sub_app4)

        # Create test files with known sizes
        for i in range(5):
            with open(os.path.join(sub_app1, f"file_{i}.dat"), "w") as f:
                f.write("x" * (1024 * (i + 1)))  # 1KB to 5KB
        for i in range(3):
            with open(os.path.join(sub_app2, f"data_{i}.csv"), "w") as f:
                f.write("y" * (2048 * (i + 1)))  # 2KB to 6KB
        for i in range(2):
            with open(os.path.join(sub_app3, f"log_{i}.txt"), "w") as f:
                f.write("z" * 512)
        with open(os.path.join(sub_app4, "log_0.txt"), "w") as f:
            f.write("w" * 256)

        yield tmpdir


@pytest.fixture
def db_session():
    """Create a temporary SQLite database session for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    session_factory = init_database(db_path)
    session = get_session(session_factory)
    yield session
    session.close()
    os.unlink(db_path)


# ===========================================================
# Test: format_size utility
# ===========================================================

class TestFormatSize:
    """Tests for the human-readable size formatter."""

    def test_zero_bytes(self):
        assert format_size(0) == "0.00 B"

    def test_bytes(self):
        assert format_size(500) == "500.00 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.00 KB"

    def test_megabytes(self):
        assert format_size(1048576) == "1.00 MB"

    def test_gigabytes(self):
        assert format_size(1073741824) == "1.00 GB"

    def test_terabytes(self):
        assert format_size(1099511627776) == "1.00 TB"

    def test_negative(self):
        assert format_size(-100) == "0 B"


# ===========================================================
# Test: Directory scanning
# ===========================================================

class TestDirectoryScanning:
    """Tests for the space calculator's directory scanning."""

    def test_scan_existing_directory(self, temp_dir):
        """Scan a directory and verify file counts and total size."""
        billing_path = os.path.join(temp_dir, "billing")
        result = scan_directory_recursive(billing_path)

        assert result.file_count == 5
        assert result.total_size_bytes > 0
        assert len(result.errors) == 0

    def test_scan_nonexistent_directory(self):
        """Scanning a nonexistent directory returns errors."""
        result = scan_directory_recursive("/nonexistent/path")
        assert result.file_count == 0
        assert len(result.errors) > 0

    def test_scan_collects_file_info(self, temp_dir):
        """Verify file metadata is collected when requested."""
        billing_path = os.path.join(temp_dir, "billing")
        result = scan_directory_recursive(billing_path, collect_file_info=True)

        assert len(result.files) == 5
        for f in result.files:
            assert f.size_bytes > 0
            assert f.path.startswith(billing_path)

    def test_scan_without_file_info(self, temp_dir):
        """Aggregate-only scan should not collect file details."""
        billing_path = os.path.join(temp_dir, "billing")
        result = scan_directory_recursive(billing_path, collect_file_info=False)

        assert result.file_count == 5
        assert len(result.files) == 0

    def test_scan_files_since(self, temp_dir):
        """Incremental scan should only return recently modified files."""
        billing_path = os.path.join(temp_dir, "billing")
        # All files were just created, so they are all "recent"
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_files = list(scan_files_since(billing_path, one_hour_ago))
        assert len(recent_files) == 5

        # Use a future timestamp - no files should match
        future = datetime.now() + timedelta(hours=1)
        no_files = list(scan_files_since(billing_path, future))
        assert len(no_files) == 0


# ===========================================================
# Test: Path resolver for sub-app configurations
# ===========================================================

class TestPathResolver:
    """Tests for the sub-app path resolution logic."""

    def test_relative_path(self, temp_dir):
        """Relative path should be joined with nas_mount_path."""
        server = ServerConfig(
            server_name="test",
            server_host="localhost",
            nas_mount_path=temp_dir,
        )
        sub_app = SubAppConfig(name="billing", path="billing")

        paths = resolve_sub_app_paths(server, sub_app)
        assert len(paths) == 1
        assert paths[0] == os.path.join(temp_dir, "billing")

    def test_dedicated_mount(self, temp_dir):
        """Dedicated mount should use the absolute path directly."""
        billing_path = os.path.join(temp_dir, "billing")
        server = ServerConfig(
            server_name="test",
            server_host="localhost",
            nas_mount_path="/some/other/path",
        )
        sub_app = SubAppConfig(
            name="billing",
            path=billing_path,
            is_dedicated_mount=True,
        )

        paths = resolve_sub_app_paths(server, sub_app)
        assert len(paths) == 1
        assert paths[0] == billing_path

    def test_pattern_matching(self, temp_dir):
        """Glob patterns should match directories in the NAS mount."""
        server = ServerConfig(
            server_name="test",
            server_host="localhost",
            nas_mount_path=temp_dir,
        )
        sub_app = SubAppConfig(name="logs", patterns=["logs_*"])

        paths = resolve_sub_app_paths(server, sub_app)
        assert len(paths) == 2  # logs_2024 and logs_2025

    def test_no_path_or_patterns(self, temp_dir):
        """Sub-app with no path or patterns returns empty list."""
        server = ServerConfig(
            server_name="test",
            server_host="localhost",
            nas_mount_path=temp_dir,
        )
        sub_app = SubAppConfig(name="empty")

        paths = resolve_sub_app_paths(server, sub_app)
        assert len(paths) == 0

    def test_nonexistent_path(self, temp_dir):
        """Non-existent relative path returns empty list."""
        server = ServerConfig(
            server_name="test",
            server_host="localhost",
            nas_mount_path=temp_dir,
        )
        sub_app = SubAppConfig(name="missing", path="does_not_exist")

        paths = resolve_sub_app_paths(server, sub_app)
        assert len(paths) == 0


# ===========================================================
# Test: Incremental scanner
# ===========================================================

class TestIncrementalScanner:
    """Tests for the incremental scanning logic."""

    def test_full_scan(self, temp_dir, db_session):
        """First scan should be a full scan and store file metadata."""
        scanner = IncrementalScanner(db_session)
        billing_path = os.path.join(temp_dir, "billing")

        result = scanner.scan_sub_app(
            server_name="test-server",
            sub_app_name="billing",
            directory_path=billing_path,
        )

        assert result.file_count == 5
        assert result.total_size_bytes > 0

        # Verify scan result was stored in the database
        scan_record = db_session.query(ScanResult).first()
        assert scan_record is not None
        assert scan_record.scan_type == "full"
        assert scan_record.total_file_count == 5

    def test_incremental_scan_after_full(self, temp_dir, db_session):
        """Second scan should be incremental."""
        scanner = IncrementalScanner(db_session)
        billing_path = os.path.join(temp_dir, "billing")

        # First scan (full)
        scanner.scan_sub_app("test-server", "billing", billing_path)

        # Wait briefly so timestamps differ
        time.sleep(0.1)

        # Second scan (should be incremental)
        result = scanner.scan_sub_app("test-server", "billing", billing_path)

        # Verify two scan records exist
        scan_count = db_session.query(ScanResult).count()
        assert scan_count == 2

        # Second scan should be incremental type
        scans = (
            db_session.query(ScanResult)
            .order_by(ScanResult.scan_timestamp.desc())
            .all()
        )
        assert scans[0].scan_type == "incremental"

    def test_force_full_scan(self, temp_dir, db_session):
        """Forced full scan should override incremental mode."""
        scanner = IncrementalScanner(db_session)
        billing_path = os.path.join(temp_dir, "billing")

        # First scan
        scanner.scan_sub_app("test-server", "billing", billing_path)

        # Forced full scan
        result = scanner.scan_sub_app(
            "test-server", "billing", billing_path, force_full=True
        )

        scans = (
            db_session.query(ScanResult)
            .order_by(ScanResult.scan_timestamp.desc())
            .all()
        )
        assert scans[0].scan_type == "full"


# ===========================================================
# Test: Purge analyzer
# ===========================================================

class TestPurgeAnalyzer:
    """Tests for the purge eligibility analysis."""

    def test_purge_report_empty(self, db_session):
        """Purge report with no data should return zero candidates."""
        analyzer = PurgeAnalyzer(db_session)
        report = analyzer.analyze_purge_candidates(
            server_name="test", threshold_days=90
        )

        assert report.total_candidates == 0
        assert report.total_reclaimable_bytes == 0
        assert len(report.candidates) == 0

    def test_purge_with_old_files(self, db_session):
        """Files older than threshold should be flagged as candidates."""
        # Insert test file metadata with old timestamps
        old_date = datetime.utcnow() - timedelta(days=200)
        for i in range(3):
            meta = FileMetadata(
                server_name="test-server",
                sub_app_name="billing",
                file_path=f"/mnt/nas/billing/old_file_{i}.dat",
                file_size_bytes=1024 * 1024 * (i + 1),  # 1MB, 2MB, 3MB
                last_modified=old_date,
                last_accessed=old_date,
                created_at=old_date,
                last_scanned=datetime.utcnow(),
                is_deleted=0,
            )
            db_session.add(meta)
        db_session.commit()

        analyzer = PurgeAnalyzer(db_session)
        report = analyzer.analyze_purge_candidates(
            server_name="test-server", threshold_days=90
        )

        assert report.total_candidates == 3
        assert report.total_reclaimable_bytes > 0
        # Candidates should be sorted by size descending (largest first)
        assert (
            report.candidates[0].file_size_bytes
            >= report.candidates[1].file_size_bytes
        )


# ===========================================================
# Test: Growth predictor
# ===========================================================

class TestGrowthPredictor:
    """Tests for the volume growth prediction engine."""

    def test_prediction_no_data(self, db_session):
        """Predictions with no data should return zero growth."""
        predictor = GrowthPredictor(db_session)
        report = predictor.predict_growth("test-server", "billing")

        assert len(report.predictions) == 3
        for pred in report.predictions:
            assert pred.predicted_growth_bytes == 0
            assert pred.confidence == 0

    def test_prediction_with_data(self, db_session):
        """Predictions with historical data should compute growth trends."""
        # Insert historical snapshots simulating daily growth
        base_size = 1073741824  # 1 GB
        daily_growth = 10485760  # 10 MB per day

        for day in range(30):
            ts = datetime.utcnow() - timedelta(days=30 - day)
            snapshot = SpaceSnapshot(
                server_name="test-server",
                sub_app_name="billing",
                snapshot_timestamp=ts,
                total_size_bytes=base_size + daily_growth * day,
                total_file_count=1000 + day * 10,
            )
            db_session.add(snapshot)
        db_session.commit()

        predictor = GrowthPredictor(db_session)
        report = predictor.predict_growth("test-server", "billing")

        assert len(report.predictions) == 3
        # With consistent growth, predictions should be positive
        weekly = next(p for p in report.predictions if p.period == "weekly")
        monthly = next(p for p in report.predictions if p.period == "monthly")
        yearly = next(p for p in report.predictions if p.period == "yearly")

        assert weekly.predicted_growth_bytes > 0
        assert monthly.predicted_growth_bytes > weekly.predicted_growth_bytes
        assert yearly.predicted_growth_bytes > monthly.predicted_growth_bytes
        # data_points_used is on each prediction, not on the report
        assert weekly.data_points_used == 30


# ===========================================================
# Test: Configuration loading
# ===========================================================

class TestConfig:
    """Tests for configuration loading and validation."""

    def test_default_config(self):
        """Default config should have sensible defaults."""
        config = AppConfig()
        assert config.scan_interval_minutes == 60
        assert config.port == 8080
        assert len(config.purge_thresholds_days) == 3

    def test_sub_app_dedicated_mount(self):
        """Sub-app with dedicated mount should parse correctly."""
        sub_app = SubAppConfig(
            name="warehouse",
            path="/mnt/dedicated_nas/data",
            is_dedicated_mount=True,
        )
        assert sub_app.is_dedicated_mount is True
        assert sub_app.path == "/mnt/dedicated_nas/data"

    def test_sub_app_patterns(self):
        """Sub-app with glob patterns should parse correctly."""
        sub_app = SubAppConfig(
            name="logs",
            patterns=["logs_*", "audit_*"],
        )
        assert len(sub_app.patterns) == 2
        assert sub_app.path == ""

    def test_load_config_from_yaml(self):
        """Config should load from the sample YAML file."""
        config_path = str(
            Path(__file__).parent.parent / "server_config" / "servers.yaml"
        )
        config = load_config(config_path)

        assert len(config.servers) == 3
        assert config.servers[0].server_name == "prod-server-01"
        assert len(config.servers[0].sub_apps) == 3

        # Verify pattern-based sub-app
        logs_app = config.servers[0].sub_apps[2]
        assert logs_app.name == "application-logs"
        assert len(logs_app.patterns) == 2

        # Verify dedicated mount sub-app
        warehouse_app = config.servers[1].sub_apps[0]
        assert warehouse_app.is_dedicated_mount is True
