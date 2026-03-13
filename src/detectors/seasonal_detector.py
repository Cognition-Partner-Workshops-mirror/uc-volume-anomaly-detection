"""Seasonal decomposition-based anomaly detection."""

import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Optional
from uuid import uuid4

from src.models.anomaly import AnomalyEvent, AnomalySeverity, AnomalyType
from src.models.transaction import TransactionVolume, VolumeBaseline, VolumeTimeSeries

logger = logging.getLogger(__name__)


class SeasonalDetector:
    """Detects anomalies using seasonal pattern decomposition.

    Builds hourly-by-day-of-week baselines from historical data and flags
    observations that deviate significantly from their seasonal expectation.
    """

    def __init__(
        self,
        deviation_threshold: float = 2.5,
        min_samples: int = 4,
    ) -> None:
        self.deviation_threshold = deviation_threshold
        self.min_samples = min_samples

    def build_baselines(
        self,
        time_series: VolumeTimeSeries,
    ) -> list[VolumeBaseline]:
        """Build hourly-by-day-of-week baselines from historical observations."""
        buckets: dict[tuple[int, int], list[TransactionVolume]] = defaultdict(list)

        for obs in time_series.observations:
            key = (obs.timestamp.hour, obs.timestamp.weekday())
            buckets[key].append(obs)

        baselines: list[VolumeBaseline] = []
        for (hour, dow), observations in buckets.items():
            if len(observations) < self.min_samples:
                continue

            counts = [obs.count for obs in observations]
            latencies = [obs.avg_latency_ms for obs in observations]

            baselines.append(
                VolumeBaseline(
                    service_name=time_series.service_name,
                    endpoint=time_series.endpoint,
                    hour_of_day=hour,
                    day_of_week=dow,
                    mean_count=_mean(counts),
                    std_count=_std(counts),
                    mean_latency_ms=_mean(latencies),
                    std_latency_ms=_std(latencies),
                    sample_size=len(observations),
                )
            )

        logger.info(
            "Built %d seasonal baselines for %s/%s",
            len(baselines),
            time_series.service_name,
            time_series.endpoint,
        )
        return baselines

    def detect(
        self,
        observation: TransactionVolume,
        baselines: list[VolumeBaseline],
    ) -> Optional[AnomalyEvent]:
        """Check an observation against its matching seasonal baseline."""
        hour = observation.timestamp.hour
        dow = observation.timestamp.weekday()

        baseline = self._find_baseline(baselines, hour, dow)
        if baseline is None:
            return None

        if baseline.std_count == 0:
            return None

        z_score = (observation.count - baseline.mean_count) / baseline.std_count
        abs_z = abs(z_score)

        if abs_z < self.deviation_threshold:
            return None

        anomaly_type = (
            AnomalyType.VOLUME_SPIKE if z_score > 0 else AnomalyType.VOLUME_DROP
        )
        severity = self._classify_severity(abs_z)

        direction = "above" if z_score > 0 else "below"
        description = (
            f"Seasonal anomaly: {observation.service_name}/{observation.endpoint} "
            f"volume={observation.count} is {abs_z:.1f}σ {direction} "
            f"seasonal baseline={baseline.mean_count:.0f} "
            f"(hour={hour}, day={dow}, samples={baseline.sample_size})"
        )

        return AnomalyEvent(
            anomaly_id=f"anom-{uuid4().hex[:8]}",
            anomaly_type=anomaly_type,
            severity=severity,
            service_name=observation.service_name,
            endpoint=observation.endpoint,
            detected_at=datetime.utcnow(),
            observed_value=float(observation.count),
            expected_value=baseline.mean_count,
            deviation_score=abs_z,
            description=description,
        )

    @staticmethod
    def _find_baseline(
        baselines: list[VolumeBaseline],
        hour: int,
        dow: int,
    ) -> Optional[VolumeBaseline]:
        for b in baselines:
            if b.hour_of_day == hour and b.day_of_week == dow:
                return b
        return None

    def _classify_severity(self, abs_z: float) -> AnomalySeverity:
        if abs_z >= self.deviation_threshold * 2.5:
            return AnomalySeverity.CRITICAL
        if abs_z >= self.deviation_threshold * 1.5:
            return AnomalySeverity.HIGH
        if abs_z >= self.deviation_threshold:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)
