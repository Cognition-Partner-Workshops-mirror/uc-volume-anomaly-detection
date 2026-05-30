"""
SQLite database setup and session management for storing scan history.

Uses SQLAlchemy ORM to define tables for scan results, file metadata,
historical space snapshots, user accounts, and dynamic sub-app configs.
"""

import hashlib
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""
    pass


class ScanResult(Base):
    """Records each scan execution with aggregate results per sub-app."""
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_name = Column(String(255), nullable=False, index=True)
    sub_app_name = Column(String(255), nullable=False, index=True)
    scan_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Total size in bytes for this sub-app at scan time
    total_size_bytes = Column(Float, nullable=False, default=0)
    # Number of files counted
    total_file_count = Column(Integer, nullable=False, default=0)
    # Number of directories counted
    total_dir_count = Column(Integer, nullable=False, default=0)
    # Whether this was an incremental or full scan
    scan_type = Column(String(20), nullable=False, default="full")
    # Duration of scan in seconds
    scan_duration_seconds = Column(Float, nullable=False, default=0)


class FileMetadata(Base):
    """
    Stores metadata for each file to enable incremental scanning.

    On subsequent scans, only files with mtime > last_scan_time
    are re-evaluated, making scans on 10TB servers much faster.
    """
    __tablename__ = "file_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_name = Column(String(255), nullable=False, index=True)
    sub_app_name = Column(String(255), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    file_size_bytes = Column(Float, nullable=False, default=0)
    # File extension extracted from file_path (e.g. ".log", ".csv")
    file_extension = Column(String(50), nullable=True, default="")
    # Last modification time of the file
    last_modified = Column(DateTime, nullable=False)
    # Last access time of the file (used for purge eligibility)
    last_accessed = Column(DateTime, nullable=False)
    # Creation time of the file
    created_at = Column(DateTime, nullable=False)
    # Timestamp when this record was last updated by a scan
    last_scanned = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Flag indicating if the file was deleted (detected during scan)
    is_deleted = Column(Integer, nullable=False, default=0)


class SpaceSnapshot(Base):
    """
    Hourly/daily space snapshots used for growth prediction.

    Stores aggregate space per server and sub-app for trend analysis.
    """
    __tablename__ = "space_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_name = Column(String(255), nullable=False, index=True)
    sub_app_name = Column(String(255), nullable=False, index=True)
    snapshot_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    total_size_bytes = Column(Float, nullable=False, default=0)
    total_file_count = Column(Integer, nullable=False, default=0)


class User(Base):
    """
    User accounts for login authentication.

    Supports username/email login with SHA-256 hashed passwords.
    Default password for new signups is 'welcome123'.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    # SHA-256 hashed password
    password_hash = Column(String(64), nullable=False)
    # Display name for the UI
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)


class SubAppConfigDB(Base):
    """
    Dynamic sub-app configuration stored in the database.

    Allows users to add/edit/remove sub-app mount paths, folders, and
    patterns via the web UI instead of editing YAML files manually.
    """
    __tablename__ = "sub_app_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_name = Column(String(255), nullable=False, index=True)
    sub_app_name = Column(String(255), nullable=False)
    # Path (relative or absolute) for the sub-app
    path = Column(Text, nullable=False, default="")
    # Comma-separated glob patterns for matching subfolders
    patterns = Column(Text, nullable=False, default="")
    # Whether this sub-app has a dedicated mount point
    is_dedicated_mount = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AppSettings(Base):
    """
    Application-wide settings stored in the database.

    Stores key-value pairs for cost rate, excluded mounts, etc.
    """
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(100), nullable=False, unique=True, index=True)
    setting_value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_database(db_path: str) -> sessionmaker:
    """
    Initialize the SQLite database and create all tables.

    Returns a sessionmaker bound to the database engine.
    """
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def get_session(session_factory: sessionmaker) -> Session:
    """Create and return a new database session."""
    return session_factory()
