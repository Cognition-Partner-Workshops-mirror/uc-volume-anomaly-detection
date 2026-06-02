# Knowledge Base — Volume-Based Anomaly Detection

## Table of Contents

- [1. Architecture Overview](#1-architecture-overview)
  - [1.1 System Purpose](#11-system-purpose)
  - [1.2 Multi-Agent Architecture](#12-multi-agent-architecture)
  - [1.3 Agent Communication Flow](#13-agent-communication-flow)
  - [1.4 Infrastructure Components](#14-infrastructure-components)
- [2. Data Model Documentation](#2-data-model-documentation)
  - [2.1 Transaction Models](#21-transaction-models)
  - [2.2 Anomaly Models](#22-anomaly-models)
  - [2.3 Service Health Models](#23-service-health-models)
  - [2.4 Recommendation Models](#24-recommendation-models)
  - [2.5 Entity Relationships](#25-entity-relationships)
- [3. Detection Algorithms](#3-detection-algorithms)
  - [3.1 Z-Score Detector](#31-z-score-detector)
  - [3.2 Seasonal Detector](#32-seasonal-detector)
  - [3.3 Severity Classification](#33-severity-classification)
- [4. Agent Inventory](#4-agent-inventory)
  - [4.1 Anomaly Detection Agent](#41-anomaly-detection-agent)
  - [4.2 Service Health Agent](#42-service-health-agent)
  - [4.3 Recommendation Engine](#43-recommendation-engine)
  - [4.4 Incident Insight Agent](#44-incident-insight-agent)
- [5. Key Business Logic](#5-key-business-logic)
  - [5.1 Baseline Computation](#51-baseline-computation)
  - [5.2 Multi-Detector Analysis Pipeline](#52-multi-detector-analysis-pipeline)
  - [5.3 Runbook-Based Recommendations](#53-runbook-based-recommendations)
  - [5.4 Incident Report Consolidation](#54-incident-report-consolidation)
- [6. Configuration Reference](#6-configuration-reference)
  - [6.1 Detection Rules (YAML)](#61-detection-rules-yaml)
  - [6.2 Baseline Configuration (JSON)](#62-baseline-configuration-json)
  - [6.3 Environment Variables](#63-environment-variables)
- [7. Integration Points](#7-integration-points)
- [8. Build and Deployment](#8-build-and-deployment)

---

## 1. Architecture Overview

### 1.1 System Purpose

This project implements a **multi-agent system** for detecting abnormal transaction volume patterns in microservices. It enables early identification of production issues (e.g., after releases) before end-user impact occurs. The system addresses the limitation of traditional threshold-based alerting, which misses gradual degradation and novel failure patterns.

### 1.2 Multi-Agent Architecture

The system is composed of four specialized agents that form a pipeline:

```
┌──────────────────────────┐     ┌────────────────────────────────┐
│  Anomaly Detection Agent │────▶│  Service Health Assessment Agent│
│  (anomaly_detector.py)   │     │  (service_health.py)           │
└──────────────────────────┘     └──────────────┬─────────────────┘
                                                │
┌──────────────────────────┐     ┌──────────────▼─────────────────┐
│  Recommendation Engine   │◀────│  Incident Insight Agent         │
│  (recommendation_engine) │     │  (incident_insight.py)          │
└──────────────────────────┘     └────────────────────────────────┘
```

| Agent | Source File | Role |
|-------|------------|------|
| **Anomaly Detection Agent** | `src/agents/anomaly_detector.py` | Loads historical data, builds seasonal baselines, runs Z-score and seasonal detectors to identify anomalies |
| **Service Health Agent** | `src/agents/service_health.py` | Correlates detected anomalies with upstream/downstream service health signals |
| **Recommendation Engine** | `src/agents/recommendation_engine.py` | Matches anomaly patterns against a runbook knowledge base to suggest corrective actions |
| **Incident Insight Agent** | `src/agents/incident_insight.py` | Consolidates anomalies, health snapshots, and recommendations into structured incident reports |

### 1.3 Agent Communication Flow

1. **AnomalyDetectionAgent** ingests historical CSV data and builds hourly-by-day-of-week baselines via `SeasonalDetector.build_baselines()`.
2. For each new observation, the agent runs both the **SeasonalDetector** and the **ZScoreDetector** (for volume and latency), producing `AnomalyEvent` objects.
3. Detected anomalies are passed to the **ServiceHealthAgent**, which fetches health snapshots for the affected service and its upstream/downstream dependencies. Correlated degraded services are attached to the anomaly.
4. Anomalies (with correlation data) are fed to the **RecommendationEngine**, which matches them against `RunbookEntry` definitions and produces `Recommendation` objects.
5. Finally, the **IncidentInsightAgent** consolidates all findings into an `AnomalyReport` with a human-readable summary, suitable for notification to support teams.

### 1.4 Infrastructure Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11 | Core language |
| Data Validation | Pydantic ≥2.5 | Not yet used in models (dataclasses used instead) |
| Configuration | PyYAML ≥6.0.1 | YAML-based detection rules |
| HTTP Client | HTTPX ≥0.25 | External service communication (metrics, health checks) |
| Structured Logging | Structlog ≥23.2 | Production-grade logging |
| Metrics Client | prometheus-client ≥0.19 | Prometheus integration |
| Environment Config | python-dotenv ≥1.0 | `.env` file loading |
| Testing | Pytest ≥7.4 | Test framework |
| Containerization | Docker (python:3.11-slim) | Deployment packaging |

---

## 2. Data Model Documentation

All models use Python `dataclasses`. They are located in `src/models/`.

### 2.1 Transaction Models

**File:** `src/models/transaction.py`

#### `TransactionVolume`

Represents a single time-bucketed observation of transaction volume for a service endpoint.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timestamp` | `datetime` | — | Observation timestamp |
| `service_name` | `str` | — | Name of the microservice |
| `endpoint` | `str` | — | API endpoint path |
| `count` | `int` | — | Number of transactions in the time bucket |
| `error_count` | `int` | `0` | Number of errored transactions |
| `avg_latency_ms` | `float` | `0.0` | Average response latency in milliseconds |
| `p99_latency_ms` | `float` | `0.0` | 99th percentile latency in milliseconds |

**Computed property:** `error_rate` → `error_count / count` (0.0 if count is 0).

#### `VolumeBaseline`

Statistical baseline for a specific hour-of-day and day-of-week combination.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `service_name` | `str` | — | Service name |
| `endpoint` | `str` | — | Endpoint path |
| `hour_of_day` | `int` | — | Hour (0-23) |
| `day_of_week` | `int` | — | Day of week (0=Monday, 6=Sunday) |
| `mean_count` | `float` | — | Historical mean transaction count |
| `std_count` | `float` | — | Historical standard deviation of count |
| `mean_latency_ms` | `float` | — | Historical mean latency |
| `std_latency_ms` | `float` | — | Historical standard deviation of latency |
| `sample_size` | `int` | `0` | Number of historical samples used |

**Computed properties:** `upper_bound` (mean + 3σ), `lower_bound` (max(0, mean − 3σ)).

#### `VolumeTimeSeries`

A time-ordered collection of `TransactionVolume` observations for one service/endpoint.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `service_name` | `str` | — | Service name |
| `endpoint` | `str` | — | Endpoint path |
| `observations` | `list[TransactionVolume]` | `[]` | Ordered observations |

**Computed properties:** `total_count`, `time_range`.

### 2.2 Anomaly Models

**File:** `src/models/anomaly.py`

#### `AnomalySeverity` (Enum)

| Value | String |
|-------|--------|
| `LOW` | `"low"` |
| `MEDIUM` | `"medium"` |
| `HIGH` | `"high"` |
| `CRITICAL` | `"critical"` |

#### `AnomalyType` (Enum)

| Value | String | Description |
|-------|--------|-------------|
| `VOLUME_SPIKE` | `"volume_spike"` | Unexpected increase in transaction count |
| `VOLUME_DROP` | `"volume_drop"` | Unexpected decrease in transaction count |
| `LATENCY_SPIKE` | `"latency_spike"` | Unexpected increase in response latency |
| `ERROR_RATE_SPIKE` | `"error_rate_spike"` | Unexpected increase in error rate |
| `PATTERN_SHIFT` | `"pattern_shift"` | Fundamental change in traffic pattern |

#### `AnomalyEvent`

A single detected anomaly.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `anomaly_id` | `str` | — | Unique ID (format: `anom-{hex8}`) |
| `anomaly_type` | `AnomalyType` | — | Type of anomaly |
| `severity` | `AnomalySeverity` | — | Severity classification |
| `service_name` | `str` | — | Affected service |
| `endpoint` | `str` | — | Affected endpoint |
| `detected_at` | `datetime` | — | Detection timestamp |
| `observed_value` | `float` | — | Actual observed metric value |
| `expected_value` | `float` | — | Expected baseline value |
| `deviation_score` | `float` | — | Z-score or deviation magnitude |
| `description` | `str` | — | Human-readable description |
| `correlated_services` | `list[str]` | `[]` | Services correlated with this anomaly |
| `recommended_actions` | `list[str]` | `[]` | Recommended remediation actions |

**Computed property:** `deviation_percentage` → percentage deviation from expected.

#### `AnomalyReport`

Consolidated incident report.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `report_id` | `str` | — | Unique ID (format: `rpt-{hex8}`) |
| `generated_at` | `datetime` | — | Report generation timestamp |
| `time_window_start` | `datetime` | — | Analysis window start |
| `time_window_end` | `datetime` | — | Analysis window end |
| `anomalies` | `list[AnomalyEvent]` | `[]` | All detected anomalies |
| `affected_services` | `list[str]` | `[]` | Unique affected service names |
| `summary` | `str` | `""` | Human-readable summary |
| `recommended_actions` | `list[str]` | `[]` | Deduplicated action list |

**Computed properties:** `critical_count`, `high_count`.

### 2.3 Service Health Models

**File:** `src/models/service_health.py`

#### `HealthStatus` (Enum)

| Value | String |
|-------|--------|
| `HEALTHY` | `"healthy"` |
| `DEGRADED` | `"degraded"` |
| `UNHEALTHY` | `"unhealthy"` |
| `UNKNOWN` | `"unknown"` |

#### `ServiceHealthSnapshot`

Point-in-time health assessment for a service.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `service_name` | `str` | — | Service name |
| `timestamp` | `datetime` | — | Snapshot timestamp |
| `status` | `HealthStatus` | — | Overall health status |
| `cpu_utilization` | `float` | `0.0` | CPU usage (0.0–1.0) |
| `memory_utilization` | `float` | `0.0` | Memory usage (0.0–1.0) |
| `active_pods` | `int` | `0` | Currently running pods |
| `desired_pods` | `int` | `0` | Desired pod count |
| `avg_response_time_ms` | `float` | `0.0` | Average response time |
| `error_rate` | `float` | `0.0` | Current error rate |
| `request_rate` | `float` | `0.0` | Requests per second |

**Computed property:** `pod_availability` → `active_pods / desired_pods`.

#### `ServiceDependency`

Directed edge in the service dependency graph.

| Field | Type | Description |
|-------|------|-------------|
| `source_service` | `str` | Service that depends on target |
| `target_service` | `str` | Service being depended upon |
| `dependency_type` | `str` | Protocol: `"http"`, `"grpc"`, `"message_queue"`, `"database"` |
| `criticality` | `str` | Importance: `"required"`, `"optional"`, `"fallback"` |

#### `ServiceMap`

Container for the service dependency graph.

| Field | Type | Description |
|-------|------|-------------|
| `services` | `list[str]` | All registered service names |
| `dependencies` | `list[ServiceDependency]` | All dependency edges |

**Methods:** `get_downstream(service)` → dependents, `get_upstream(service)` → dependencies.

### 2.4 Recommendation Models

**File:** `src/agents/recommendation_engine.py` (inline dataclasses)

#### `Recommendation`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `action` | `str` | — | Recommended corrective action |
| `confidence` | `float` | — | Confidence score (0.0–1.0) |
| `source` | `str` | — | Origin: `"runbook"`, `"historical_incident"`, `"heuristic"` |
| `priority` | `int` | `0` | Priority ranking (lower = higher priority) |
| `details` | `str` | `""` | Additional context |

#### `RunbookEntry`

| Field | Type | Description |
|-------|------|-------------|
| `anomaly_types` | `list[AnomalyType]` | Anomaly types this entry applies to |
| `severity_threshold` | `AnomalySeverity` | Minimum severity to trigger |
| `actions` | `list[str]` | Ordered corrective actions |
| `description` | `str` | Description of the pattern |

### 2.5 Entity Relationships

```
TransactionVolume ──(aggregated into)──▶ VolumeTimeSeries
VolumeTimeSeries  ──(builds)──────────▶ VolumeBaseline[]
TransactionVolume ──(compared to)──────▶ VolumeBaseline ──(produces)──▶ AnomalyEvent
AnomalyEvent      ──(assessed by)──────▶ ServiceHealthSnapshot
AnomalyEvent      ──(matched to)───────▶ RunbookEntry ──(generates)──▶ Recommendation[]
AnomalyEvent[]    ──(consolidated)─────▶ AnomalyReport
ServiceMap        ──(contains)─────────▶ ServiceDependency[]
```

---

## 3. Detection Algorithms

### 3.1 Z-Score Detector

**File:** `src/detectors/zscore_detector.py`

The Z-score detector compares a single observation against its matching baseline using the standard z-score formula:

```
z = (observed_count - baseline_mean) / baseline_std
```

**Volume detection** (`detect` method):
- Computes z-score from `observation.count` vs `baseline.mean_count / std_count`.
- If `|z| >= warning_threshold` (default 2.0), flags an anomaly.
- Positive z → `VOLUME_SPIKE`; negative z → `VOLUME_DROP`.

**Latency detection** (`detect_latency` method):
- Computes z-score from `observation.avg_latency_ms` vs `baseline.mean_latency_ms / std_latency_ms`.
- Only flags increases (`z >= warning_threshold`); produces `LATENCY_SPIKE`.

**Configurable thresholds:**
- `warning_threshold`: Default `2.0` (flags MEDIUM)
- `critical_threshold`: Default `3.0` (flags HIGH)

### 3.2 Seasonal Detector

**File:** `src/detectors/seasonal_detector.py`

The seasonal detector builds hourly-by-day-of-week baselines from historical data, then detects deviations from the expected seasonal pattern.

**Baseline building** (`build_baselines` method):
1. Groups all observations by `(hour_of_day, day_of_week)` tuples.
2. For each bucket with at least `min_samples` (default 4) observations, computes mean and sample standard deviation for both count and latency.
3. Produces a `VolumeBaseline` per bucket.

**Detection** (`detect` method):
- Finds the matching baseline for the observation's hour and day-of-week.
- Computes z-score and compares against `deviation_threshold` (default 2.5).
- Classification: positive z → `VOLUME_SPIKE`, negative z → `VOLUME_DROP`.

**Statistical helpers:** `_mean()` and `_std()` implement simple arithmetic mean and sample standard deviation (Bessel's correction, `n-1` denominator).

### 3.3 Severity Classification

Each detector has its own severity mapping:

**Z-Score Detector:**

| Z-Score Range | Severity |
|---------------|----------|
| `|z| >= critical * 2` (≥6.0) | CRITICAL |
| `|z| >= critical` (≥3.0) | HIGH |
| `|z| >= warning` (≥2.0) | MEDIUM |
| `|z| < warning` | LOW |

**Seasonal Detector:**

| Z-Score Range | Severity |
|---------------|----------|
| `|z| >= threshold * 2.5` (≥6.25) | CRITICAL |
| `|z| >= threshold * 1.5` (≥3.75) | HIGH |
| `|z| >= threshold` (≥2.5) | MEDIUM |
| `|z| < threshold` | LOW |

---

## 4. Agent Inventory

### 4.1 Anomaly Detection Agent

**File:** `src/agents/anomaly_detector.py`  
**Class:** `AnomalyDetectionAgent`

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `__init__` | `zscore_warning`, `zscore_critical`, `seasonal_threshold` | — | Initializes both detectors with configurable thresholds |
| `load_historical_data` | `csv_path: str` | `dict[str, VolumeTimeSeries]` | Parses CSV into time series keyed by `service/endpoint` |
| `build_baselines` | `historical_data` | `None` | Delegates to `SeasonalDetector.build_baselines()` for each series |
| `analyze` | `observation: TransactionVolume` | `list[AnomalyEvent]` | Runs seasonal + z-score (volume and latency) checks against baselines |

**State:** Maintains `self.baselines` (dict of baseline lists) and `self.detected_anomalies` (cumulative list).

### 4.2 Service Health Agent

**File:** `src/agents/service_health.py`  
**Class:** `ServiceHealthAgent`

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `__init__` | `service_map: Optional[ServiceMap]` | — | Initializes with optional dependency graph |
| `assess` | `anomaly: AnomalyEvent` | `ServiceHealthSnapshot` | Fetches/caches health snapshot for anomaly's service |
| `correlate` | `anomaly: AnomalyEvent` | `list[str]` | Checks upstream/downstream services for degradation; attaches to anomaly |
| `_fetch_health` | `service_name: str` | `ServiceHealthSnapshot` | **Stub** — returns healthy snapshot (to be replaced with Prometheus/Datadog) |

### 4.3 Recommendation Engine

**File:** `src/agents/recommendation_engine.py`  
**Class:** `RecommendationEngine`

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `__init__` | `runbook: Optional[list[RunbookEntry]]` | — | Loads runbook (defaults to `DEFAULT_RUNBOOK`) |
| `recommend` | `anomaly, correlated_services` | `list[Recommendation]` | Matches anomaly against runbook entries; adds correlation-based suggestions |

**Default Runbook (4 entries):**

| Anomaly Type | Severity Threshold | # Actions | Description |
|-------------|-------------------|-----------|-------------|
| `VOLUME_DROP` | HIGH | 4 | Upstream failure or routing issue |
| `VOLUME_SPIKE` | HIGH | 4 | Retry storms or batch job overlap |
| `LATENCY_SPIKE` | MEDIUM | 4 | Database or resource contention |
| `ERROR_RATE_SPIKE` | MEDIUM | 4 | Dependency failures or bad deployments |

**Confidence scoring:** Runbook actions receive descending confidence: `0.8, 0.7, 0.6, 0.5` for actions 1–4. Correlation-based recommendations get `0.7`.

### 4.4 Incident Insight Agent

**File:** `src/agents/incident_insight.py`  
**Class:** `IncidentInsightAgent`

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `generate_report` | `anomalies, health_snapshots, recommendations, time_window_start, time_window_end` | `AnomalyReport` | Builds consolidated report with deduplicated actions |
| `_build_summary` | `anomalies, affected_services, health_snapshots` | `str` | Creates human-readable multi-line summary |
| `format_for_notification` | `report: AnomalyReport` | `str` | Formats report for Slack/PagerDuty with severity prefix and top-5 actions |

---

## 5. Key Business Logic

### 5.1 Baseline Computation

The system computes baselines at an **hourly granularity, stratified by day-of-week**. This captures weekly seasonality (e.g., Monday mornings have different traffic than Saturday nights).

- **Input:** Historical CSV with columns `timestamp, service_name, endpoint, count, error_count, avg_latency_ms, p99_latency_ms`.
- **Bucketing:** Each observation is assigned to a `(hour, weekday)` tuple.
- **Minimum samples:** Buckets with fewer than `min_samples` (default 4, configurable) are dropped.
- **Statistics:** Mean and sample standard deviation (Bessel-corrected) are computed per bucket for both count and latency.
- **Output:** A list of `VolumeBaseline` objects per service/endpoint combination.

### 5.2 Multi-Detector Analysis Pipeline

For each incoming `TransactionVolume` observation, the `AnomalyDetectionAgent.analyze()` method runs three checks in sequence:

1. **Seasonal detection:** Matches observation to its `(hour, dow)` baseline and checks for deviation beyond the seasonal threshold.
2. **Z-score volume detection:** Uses the same baseline but applies the z-score threshold (typically lower than seasonal).
3. **Z-score latency detection:** Checks `avg_latency_ms` against baseline latency statistics.

All three can fire independently, meaning a single observation can produce up to 3 anomaly events.

### 5.3 Runbook-Based Recommendations

The recommendation engine implements a pattern-matching system:

1. For each anomaly, iterate through all `RunbookEntry` definitions.
2. **Type match:** The anomaly's type must be in the entry's `anomaly_types` list.
3. **Severity gate:** The anomaly's severity must meet or exceed the entry's `severity_threshold` (compared by rank: LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3).
4. **Action generation:** Each matched entry's actions are emitted as `Recommendation` objects with decreasing confidence scores.
5. **Correlation enrichment:** If correlated services are provided, additional heuristic recommendations are appended.

### 5.4 Incident Report Consolidation

The `IncidentInsightAgent` merges multiple data streams:

- **Deduplication:** Recommended actions are deduplicated by preserving insertion order (`dict.fromkeys`).
- **Affected services:** Extracted as a unique set from all anomaly events.
- **Summary generation:** Counts CRITICAL/HIGH anomalies, lists per-service health (status, pod count, error rate).
- **Notification formatting:** Adds severity prefix (`[CRITICAL]` or `[HIGH]`), includes time window, summary text, and top 5 actions.

---

## 6. Configuration Reference

### 6.1 Detection Rules (YAML)

**File:** `config/detection_rules.yaml`

```yaml
baseline:
  window_days: 30                    # Historical lookback for baseline computation
  min_samples_per_bucket: 4          # Minimum observations per (hour, dow) bucket
  granularity: hourly                # Time bucket granularity

detectors:
  zscore:
    enabled: true
    warning_threshold: 2.0           # Z-score for MEDIUM severity
    critical_threshold: 3.0          # Z-score for HIGH severity
  seasonal:
    enabled: true
    deviation_threshold: 2.5         # Seasonal z-score threshold
  error_rate:
    enabled: true
    warning_threshold: 0.05          # 5% error rate warning
    critical_threshold: 0.10         # 10% error rate critical

alerting:
  cooldown_minutes: 15               # Minimum time between alerts for same issue
  deduplication_window_minutes: 30   # Window for deduplicating similar alerts
  notification_channels:             # Webhook + PagerDuty channels
    - type: webhook
      url: "${ALERT_WEBHOOK_URL}"
      severity_filter: ["high", "critical"]
    - type: pagerduty
      routing_key: "${PAGERDUTY_ROUTING_KEY}"
      severity_filter: ["critical"]

services:
  monitored:                         # 4 monitored services with 8 endpoints total
    - payment-service: [/api/v1/payments, /api/v1/payments/status]
    - order-service: [/api/v1/orders, /api/v1/orders/status]
    - auth-service: [/api/v1/auth/login, /api/v1/auth/token]
    - notification-service: [/api/v1/notifications/send]
```

### 6.2 Baseline Configuration (JSON)

**File:** `data/baselines/baseline_config.json`

Contains pre-computed baseline statistics for `payment-service` (4 buckets) and `order-service` (4 buckets). Each entry specifies:

- `hour` / `dow`: Time bucket identifier
- `mean_count` / `std_count`: Volume statistics
- `mean_latency_ms` / `std_latency_ms`: Latency statistics

### 6.3 Environment Variables

**File:** `.env.example`

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENDPOINT` | `http://prometheus:9090` | Prometheus/metrics endpoint URL |
| `METRICS_AUTH_TOKEN` | `changeme` | Auth token for metrics endpoint |
| `DETECTION_SENSITIVITY` | `5` | Anomaly sensitivity (1-10 scale) |
| `BASELINE_WINDOW_DAYS` | `30` | Days of history for baseline computation |
| `SEASONAL_THRESHOLD` | `2.5` | Seasonal deviation threshold |
| `ZSCORE_WARNING` | `2.0` | Z-score warning threshold |
| `ZSCORE_CRITICAL` | `3.0` | Z-score critical threshold |
| `ALERT_WEBHOOK_URL` | — | Slack/webhook URL for alert notifications |
| `PAGERDUTY_ROUTING_KEY` | `changeme` | PagerDuty routing key |
| `GRAFANA_URL` | `http://grafana:3000` | Grafana instance URL |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 7. Integration Points

| Integration | Technology | Status | Files |
|------------|-----------|--------|-------|
| **Prometheus Metrics** | prometheus-client, HTTPX | Dependency installed, client not implemented | `src/utils/` (placeholder) |
| **Slack/Webhook Alerts** | HTTPX | Configured in YAML, sending not implemented | `config/detection_rules.yaml` |
| **PagerDuty** | HTTPX | Configured in YAML, sending not implemented | `config/detection_rules.yaml` |
| **Grafana Dashboards** | JSON | Dashboard reference in README, file not present | Referenced in `README.md` |
| **Service Health Checks** | HTTPX | Stub implementation returns healthy | `src/agents/service_health.py` |
| **CSV Data Ingestion** | stdlib csv | Fully implemented | `src/agents/anomaly_detector.py` |
| **Live Monitoring Mode** | — | Referenced in CLI (`--mode=live`), not implemented | `README.md` |

---

## 8. Build and Deployment

### Docker Build

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY data/ ./data/
COPY config/ ./config/
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.agents.anomaly_detector"]
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run anomaly detection on sample data
PYTHONPATH=. python -m src.agents.anomaly_detector --data data/historical/sample_transactions.csv

# Run tests
PYTHONPATH=. python -m pytest tests/ -v
```

### Monitored Services

The system is configured to monitor 4 microservices across 8 endpoints:

| Service | Endpoints |
|---------|----------|
| `payment-service` | `/api/v1/payments`, `/api/v1/payments/status` |
| `order-service` | `/api/v1/orders`, `/api/v1/orders/status` |
| `auth-service` | `/api/v1/auth/login`, `/api/v1/auth/token` |
| `notification-service` | `/api/v1/notifications/send` |
