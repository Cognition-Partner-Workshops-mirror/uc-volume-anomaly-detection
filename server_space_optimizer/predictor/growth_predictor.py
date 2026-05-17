"""
Volume growth predictor using linear regression on historical snapshots.

Analyzes historical space usage data to predict future growth on
weekly, monthly, and yearly basis. Uses numpy for efficient numerical
computation and simple linear regression for trend extrapolation.
"""

import logging
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from server_space_optimizer.models.database import SpaceSnapshot
from server_space_optimizer.models.schemas import GrowthPrediction, ServerGrowthReport
from server_space_optimizer.scanner.space_calculator import format_size

logger = logging.getLogger(__name__)


class GrowthPredictor:
    """
    Predicts volume growth using linear regression on historical data.

    Collects space snapshots over time and fits a linear model to
    predict growth trends for weekly, monthly, and yearly periods.
    """

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def _get_historical_data(
        self,
        server_name: str,
        sub_app_name: str,
        days_back: int = 90,
    ) -> list[dict]:
        """
        Retrieve historical space snapshots for trend analysis.

        Returns data points as list of dicts with timestamp and size.
        """
        cutoff = datetime.utcnow() - timedelta(days=days_back)

        snapshots = (
            self.db_session.query(SpaceSnapshot)
            .filter(
                SpaceSnapshot.server_name == server_name,
                SpaceSnapshot.sub_app_name == sub_app_name,
                SpaceSnapshot.snapshot_timestamp >= cutoff,
            )
            .order_by(SpaceSnapshot.snapshot_timestamp.asc())
            .all()
        )

        return [
            {
                "timestamp": snap.snapshot_timestamp.isoformat(),
                "size_bytes": snap.total_size_bytes,
                "file_count": snap.total_file_count,
            }
            for snap in snapshots
        ]

    def _linear_regression(
        self, timestamps: list[float], sizes: list[float]
    ) -> tuple[float, float, float]:
        """
        Perform simple linear regression: size = slope * time + intercept.

        Returns (slope, intercept, r_squared) where slope is bytes/second
        growth rate and r_squared indicates the confidence of the fit.
        """
        if len(timestamps) < 2:
            return 0.0, sizes[0] if sizes else 0.0, 0.0

        x = np.array(timestamps)
        y = np.array(sizes)

        # Calculate linear regression coefficients using numpy
        n = len(x)
        sum_x = np.sum(x)
        sum_y = np.sum(y)
        sum_xy = np.sum(x * y)
        sum_x2 = np.sum(x * x)

        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 0.0, np.mean(y), 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        # Calculate R-squared for confidence measurement
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return float(slope), float(intercept), float(max(0, r_squared))

    def predict_growth(
        self,
        server_name: str,
        sub_app_name: str,
    ) -> ServerGrowthReport:
        """
        Generate growth predictions for weekly, monthly, and yearly periods.

        Uses historical snapshots to fit a linear growth model and
        extrapolate future usage for each time period.
        """
        historical_data = self._get_historical_data(
            server_name, sub_app_name, days_back=90
        )

        # Get the current size from the most recent snapshot
        latest = (
            self.db_session.query(SpaceSnapshot)
            .filter(
                SpaceSnapshot.server_name == server_name,
                SpaceSnapshot.sub_app_name == sub_app_name,
            )
            .order_by(SpaceSnapshot.snapshot_timestamp.desc())
            .first()
        )

        current_size = latest.total_size_bytes if latest else 0

        predictions = []

        if len(historical_data) < 2:
            # Not enough data for predictions, return zero-growth estimates
            for period, days in [("weekly", 7), ("monthly", 30), ("yearly", 365)]:
                predictions.append(
                    GrowthPrediction(
                        period=period,
                        predicted_growth_bytes=0,
                        predicted_growth_human="0 B",
                        growth_rate_percent=0,
                        predicted_total_bytes=current_size,
                        predicted_total_human=format_size(current_size),
                        confidence=0,
                        data_points_used=len(historical_data),
                    )
                )
        else:
            # Convert timestamps to seconds for regression
            timestamps = [
                datetime.fromisoformat(d["timestamp"]).timestamp()
                for d in historical_data
            ]
            sizes = [d["size_bytes"] for d in historical_data]

            slope, intercept, r_squared = self._linear_regression(timestamps, sizes)

            # Slope is bytes/second; convert to bytes/day for predictions
            bytes_per_day = slope * 86400

            for period, days in [("weekly", 7), ("monthly", 30), ("yearly", 365)]:
                predicted_growth = bytes_per_day * days
                predicted_total = current_size + predicted_growth
                growth_rate = (
                    (predicted_growth / current_size * 100)
                    if current_size > 0
                    else 0
                )

                predictions.append(
                    GrowthPrediction(
                        period=period,
                        predicted_growth_bytes=max(0, predicted_growth),
                        predicted_growth_human=format_size(max(0, predicted_growth)),
                        growth_rate_percent=round(max(0, growth_rate), 2),
                        predicted_total_bytes=max(0, predicted_total),
                        predicted_total_human=format_size(max(0, predicted_total)),
                        confidence=round(r_squared, 2),
                        data_points_used=len(historical_data),
                    )
                )

        logger.info(
            "Growth prediction: server=%s, sub_app=%s, data_points=%d",
            server_name,
            sub_app_name,
            len(historical_data),
        )

        return ServerGrowthReport(
            server_name=server_name,
            sub_app_name=sub_app_name,
            current_size_bytes=current_size,
            current_size_human=format_size(current_size),
            predictions=predictions,
            historical_data=historical_data,
        )

    def predict_all_sub_apps(
        self,
        server_name: str,
    ) -> list[ServerGrowthReport]:
        """
        Generate growth predictions for all sub-apps on a server.

        Returns a list of growth reports, one per sub-app.
        """
        # Get distinct sub-app names for this server
        sub_apps = (
            self.db_session.query(SpaceSnapshot.sub_app_name)
            .filter(SpaceSnapshot.server_name == server_name)
            .distinct()
            .all()
        )

        reports = []
        for (sub_app_name,) in sub_apps:
            report = self.predict_growth(server_name, sub_app_name)
            reports.append(report)

        return reports
