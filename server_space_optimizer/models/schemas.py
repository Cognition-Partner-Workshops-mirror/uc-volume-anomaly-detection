"""
Pydantic schemas for API request/response models.

These schemas define the data structures used in the REST API
for communicating scan results, predictions, and purge reports.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubAppSpaceInfo(BaseModel):
    """Space usage information for a single sub-application."""
    sub_app_name: str
    total_size_bytes: float
    # Human-readable size string (e.g., "1.5 GB")
    total_size_human: str
    file_count: int
    dir_count: int
    last_scan_time: Optional[datetime] = None


class ServerSpaceInfo(BaseModel):
    """Aggregate space information for a server with sub-app breakdown."""
    server_name: str
    server_host: str
    nas_mount_path: str
    total_size_bytes: float
    total_size_human: str
    total_file_count: int
    sub_apps: list[SubAppSpaceInfo]
    last_scan_time: Optional[datetime] = None
    scan_type: str = "unknown"


class PurgeCandidate(BaseModel):
    """A file identified as eligible for purging based on age thresholds."""
    file_path: str
    file_size_bytes: float
    file_size_human: str
    last_modified: datetime
    last_accessed: datetime
    # Number of days since last modification
    days_since_modified: int
    # Number of days since last access
    days_since_accessed: int
    sub_app_name: str
    server_name: str


class PurgeReport(BaseModel):
    """Purge eligibility report grouped by age threshold."""
    threshold_days: int
    total_candidates: int
    total_reclaimable_bytes: float
    total_reclaimable_human: str
    candidates: list[PurgeCandidate]


class GrowthPrediction(BaseModel):
    """Volume growth prediction for a specific time period."""
    period: str = Field(
        ..., description="Prediction period: weekly, monthly, yearly, or five_year"
    )
    predicted_growth_bytes: float
    predicted_growth_human: str
    # Growth rate as a percentage
    growth_rate_percent: float
    # Predicted total size at end of period
    predicted_total_bytes: float
    predicted_total_human: str
    # Confidence level of the prediction (0.0 - 1.0)
    confidence: float
    # Number of historical data points used for the prediction
    data_points_used: int


class ServerGrowthReport(BaseModel):
    """Growth predictions for a server, broken down by sub-app."""
    server_name: str
    sub_app_name: str
    current_size_bytes: float
    current_size_human: str
    predictions: list[GrowthPrediction]
    # Historical data points used for the chart
    historical_data: list[dict]


class ScanStatusResponse(BaseModel):
    """Response for scan status API endpoint."""
    is_scanning: bool
    last_scan_time: Optional[datetime] = None
    next_scan_time: Optional[datetime] = None
    scan_interval_minutes: int
    servers_configured: int


class DashboardSummary(BaseModel):
    """Summary data for the main dashboard view."""
    total_servers: int
    total_sub_apps: int
    total_size_bytes: float
    total_size_human: str
    total_file_count: int
    servers: list[ServerSpaceInfo]
    last_scan_time: Optional[datetime] = None
