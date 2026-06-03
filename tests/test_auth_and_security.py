"""
Tests for authentication, security, and API routes.

Validates password hashing, user creation, session management,
input validation, and SQL injection resistance.
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from server_space_optimizer.auth.auth_manager import (
    DEFAULT_PASSWORD,
    authenticate_user,
    create_user,
)
from server_space_optimizer.config import AppConfig, ServerConfig, SubAppConfig
from server_space_optimizer.models.database import (
    FileMetadata,
    ScanResult,
    SpaceSnapshot,
    SubAppCapacityPlan,
    SubAppConfigDB,
    User,
    get_session,
    hash_password,
    init_database,
)
from server_space_optimizer.scanner.purge_analyzer import PurgeAnalyzer
from server_space_optimizer.scanner.space_calculator import format_size


# ===========================================================
# Fixtures
# ===========================================================

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
# Test: Password hashing
# ===========================================================

class TestPasswordHashing:
    """Tests for the SHA-256 password hashing utility."""

    def test_hash_deterministic(self):
        """Same password always produces the same hash."""
        h1 = hash_password("test123")
        h2 = hash_password("test123")
        assert h1 == h2

    def test_hash_different_passwords(self):
        """Different passwords produce different hashes."""
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_hash_length(self):
        """SHA-256 hash should be 64 hex characters."""
        h = hash_password("anypassword")
        assert len(h) == 64
        # Verify it's a valid hex string
        int(h, 16)

    def test_hash_empty_string(self):
        """Empty string should still produce a valid hash."""
        h = hash_password("")
        assert len(h) == 64

    def test_hash_unicode(self):
        """Unicode passwords should hash without error."""
        h = hash_password("pässwörd_ñ")
        assert len(h) == 64

    def test_hash_not_plaintext(self):
        """Hash output must not contain the original password."""
        pw = "welcome123"
        h = hash_password(pw)
        assert pw not in h


# ===========================================================
# Test: User creation and authentication
# ===========================================================

class TestUserAuth:
    """Tests for user creation and login authentication."""

    def test_create_user(self, db_session):
        """Creating a user should persist in the database."""
        user = create_user(db_session, "testuser", "test@example.com", "pass123")
        assert user is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        # Password must be hashed, not plaintext
        assert user.password_hash != "pass123"
        assert user.password_hash == hash_password("pass123")

    def test_create_user_default_password(self, db_session):
        """Creating a user without password should use DEFAULT_PASSWORD."""
        user = create_user(db_session, "defuser", "def@example.com")
        assert user is not None
        assert user.password_hash == hash_password(DEFAULT_PASSWORD)

    def test_create_duplicate_username(self, db_session):
        """Duplicate username should return None."""
        create_user(db_session, "dupuser", "first@example.com", "pass")
        dup = create_user(db_session, "dupuser", "second@example.com", "pass")
        assert dup is None

    def test_create_duplicate_email(self, db_session):
        """Duplicate email should return None."""
        create_user(db_session, "user1", "same@example.com", "pass")
        dup = create_user(db_session, "user2", "same@example.com", "pass")
        assert dup is None

    def test_authenticate_valid(self, db_session):
        """Valid credentials should return the User object."""
        create_user(db_session, "authuser", "auth@example.com", "mypass")
        user = authenticate_user(db_session, "authuser", "mypass")
        assert user is not None
        assert user.username == "authuser"

    def test_authenticate_wrong_password(self, db_session):
        """Wrong password should return None."""
        create_user(db_session, "authuser2", "auth2@example.com", "correct")
        user = authenticate_user(db_session, "authuser2", "wrong")
        assert user is None

    def test_authenticate_nonexistent_user(self, db_session):
        """Non-existent username should return None."""
        user = authenticate_user(db_session, "nobody", "anypass")
        assert user is None

    def test_authenticate_updates_last_login(self, db_session):
        """Successful auth should update last_login timestamp."""
        create_user(db_session, "loginuser", "login@example.com", "pass")
        user = authenticate_user(db_session, "loginuser", "pass")
        assert user.last_login is not None

    def test_inactive_user_cannot_login(self, db_session):
        """Deactivated users should not be able to authenticate."""
        user = create_user(db_session, "inactive", "inactive@example.com", "pass")
        user.is_active = 0
        db_session.commit()
        result = authenticate_user(db_session, "inactive", "pass")
        assert result is None


# ===========================================================
# Test: SQL injection resistance
# ===========================================================

class TestSQLInjection:
    """Verify that SQLAlchemy ORM prevents SQL injection attacks."""

    def test_username_injection(self, db_session):
        """SQL injection in username should not bypass authentication."""
        create_user(db_session, "admin", "admin@test.com", "secret")
        # Attempt SQL injection via username
        result = authenticate_user(
            db_session, "admin' OR '1'='1", "anything"
        )
        assert result is None

    def test_password_injection(self, db_session):
        """SQL injection in password should not bypass authentication."""
        create_user(db_session, "admin2", "admin2@test.com", "secret")
        result = authenticate_user(
            db_session, "admin2", "' OR '1'='1"
        )
        assert result is None

    def test_create_user_injection(self, db_session):
        """SQL injection in create_user fields should be safely escaped."""
        user = create_user(
            db_session,
            "user'; DROP TABLE users; --",
            "injection@test.com",
            "pass",
        )
        # Should create the user with the literal string as username
        assert user is not None
        assert "DROP TABLE" in user.username


# ===========================================================
# Test: Database model integrity
# ===========================================================

class TestDatabaseModels:
    """Tests for SQLAlchemy model creation and constraints."""

    def test_scan_result_creation(self, db_session):
        """ScanResult should persist with all required fields."""
        sr = ScanResult(
            server_name="test-srv",
            sub_app_name="billing",
            scan_timestamp=datetime.utcnow(),
            total_size_bytes=1024000,
            total_file_count=50,
            total_dir_count=5,
            scan_type="full",
            scan_duration_seconds=1.5,
        )
        db_session.add(sr)
        db_session.commit()

        fetched = db_session.query(ScanResult).first()
        assert fetched.server_name == "test-srv"
        assert fetched.total_size_bytes == 1024000

    def test_file_metadata_extension(self, db_session):
        """FileMetadata should store the extracted file extension."""
        fm = FileMetadata(
            server_name="srv1",
            sub_app_name="app1",
            file_path="/mnt/nas/data/report.csv.gz",
            file_size_bytes=5000,
            file_extension=".gz",
            last_modified=datetime.utcnow(),
            last_accessed=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db_session.add(fm)
        db_session.commit()

        fetched = db_session.query(FileMetadata).first()
        assert fetched.file_extension == ".gz"

    def test_sub_app_config_db(self, db_session):
        """SubAppConfigDB should persist server/sub-app mappings."""
        cfg = SubAppConfigDB(
            server_name="prod-01",
            sub_app_name="billing",
            path="/mnt/nas/billing",
            patterns="*.log,*.csv",
            is_dedicated_mount=0,
        )
        db_session.add(cfg)
        db_session.commit()

        fetched = db_session.query(SubAppConfigDB).first()
        assert fetched.server_name == "prod-01"
        assert fetched.patterns == "*.log,*.csv"

    def test_capacity_plan_model(self, db_session):
        """SubAppCapacityPlan should store capacity planning config."""
        plan = SubAppCapacityPlan(
            server_name="srv1",
            sub_app_name="billing",
            daily_consumption_gb=10.0,
            growth_rate_pct=10.0,
            purge_schedule_json='[{"pct":50,"after_days":7}]',
            monthly_allocation_gb=500.0,
            alert_threshold_pct=80.0,
            contact_email="team@example.com",
        )
        db_session.add(plan)
        db_session.commit()

        fetched = db_session.query(SubAppCapacityPlan).first()
        assert fetched.daily_consumption_gb == 10.0
        assert fetched.contact_email == "team@example.com"

    def test_space_snapshot(self, db_session):
        """SpaceSnapshot should store historical data points."""
        snap = SpaceSnapshot(
            server_name="srv1",
            sub_app_name="billing",
            snapshot_timestamp=datetime.utcnow(),
            total_size_bytes=1073741824,
            total_file_count=1000,
        )
        db_session.add(snap)
        db_session.commit()

        fetched = db_session.query(SpaceSnapshot).first()
        assert fetched.total_size_bytes == 1073741824


# ===========================================================
# Test: Purge analyzer edge cases
# ===========================================================

class TestPurgeEdgeCases:
    """Edge case tests for purge analysis."""

    def test_purge_respects_sub_app_filter(self, db_session):
        """Purge report should filter by sub-app when specified."""
        old = datetime.utcnow() - timedelta(days=200)
        for name in ["billing", "payments"]:
            for i in range(3):
                db_session.add(FileMetadata(
                    server_name="srv1",
                    sub_app_name=name,
                    file_path=f"/mnt/{name}/file_{i}.dat",
                    file_size_bytes=1024,
                    last_modified=old,
                    last_accessed=old,
                    created_at=old,
                    is_deleted=0,
                ))
        db_session.commit()

        analyzer = PurgeAnalyzer(db_session)
        # Filter to billing only
        report = analyzer.analyze_purge_candidates(
            "srv1", sub_app_name="billing", threshold_days=90
        )
        assert report.total_candidates == 3
        for c in report.candidates:
            assert c.sub_app_name == "billing"

    def test_purge_excludes_deleted_files(self, db_session):
        """Already-deleted files should not appear as purge candidates."""
        old = datetime.utcnow() - timedelta(days=200)
        db_session.add(FileMetadata(
            server_name="srv1",
            sub_app_name="app1",
            file_path="/mnt/deleted_file.dat",
            file_size_bytes=1024,
            last_modified=old,
            last_accessed=old,
            created_at=old,
            is_deleted=1,
        ))
        db_session.commit()

        analyzer = PurgeAnalyzer(db_session)
        report = analyzer.analyze_purge_candidates("srv1", threshold_days=90)
        assert report.total_candidates == 0

    def test_purge_limit(self, db_session):
        """Purge report should respect the limit parameter."""
        old = datetime.utcnow() - timedelta(days=200)
        for i in range(20):
            db_session.add(FileMetadata(
                server_name="srv1",
                sub_app_name="app1",
                file_path=f"/mnt/file_{i}.dat",
                file_size_bytes=1024 * (i + 1),
                last_modified=old,
                last_accessed=old,
                created_at=old,
                is_deleted=0,
            ))
        db_session.commit()

        analyzer = PurgeAnalyzer(db_session)
        report = analyzer.analyze_purge_candidates(
            "srv1", threshold_days=90, limit=5
        )
        assert len(report.candidates) == 5
        assert report.total_candidates == 20


# ===========================================================
# Test: Configuration security
# ===========================================================

class TestConfigSecurity:
    """Tests for configuration and secrets handling."""

    def test_secret_key_from_env(self):
        """Secret key should be configurable via environment variable."""
        # The default value should not be a production-ready secret
        config = AppConfig()
        assert config.secret_key is not None
        assert len(config.secret_key) > 0

    def test_default_password_env_var(self):
        """DEFAULT_PASSWORD should be loaded (env or fallback)."""
        assert DEFAULT_PASSWORD is not None
        assert len(DEFAULT_PASSWORD) > 0

    def test_excluded_mounts_default(self):
        """Default excluded mounts should include system paths."""
        config = AppConfig()
        assert "/var" in config.excluded_mounts
        assert "/tmp" in config.excluded_mounts
        assert "/proc" in config.excluded_mounts

    def test_format_size_edge_cases(self):
        """Format size should handle edge cases."""
        assert format_size(0) == "0.00 B"
        assert format_size(-1) == "0 B"
        assert "TB" in format_size(2 * 1099511627776)
