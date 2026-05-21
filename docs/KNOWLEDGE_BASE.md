# Knowledge Base — Volume-Based Anomaly Detection System

## 1. Architecture Overview

### System Purpose

A multi-agent system for detecting and analyzing transaction volume anomalies in microservices. It provides automated incident response recommendations and service health correlation for SRE and DevOps teams.

### High-Level Architecture

```
┌──────────────────────┐     ┌───────────────────────────┐
│  Anomaly Detection   │────▶│  Service Health Assessment │
│  Agent               │     │  Agent                    │
└──────────────────────┘     └───────────┬───────────────┘
                                         │
┌──────────────────────┐     ┌───────────▼───────────────┐
│  Knowledge-Based     │◀────│  Incident Insight         │
│  Recommendation Agent│     │  Agent                    │
└──────────────────────┘     └───────────────────────────┘
```

### Agent Responsibilities

| Agent | Module | Role |
|-------|--------|------|
| Anomaly Detection Agent | `src/agents/anomaly_detector.py` | Loads historical CSV data, builds seasonal baselines, runs Z-score and seasonal detectors against live observations |
| Service Health Agent | `src/agents/service_health.py` | Fetches per-service health snapshots (CPU, memory, pods, error rate) and correlates anomalies with upstream/downstream dependencies |
| Recommendation Engine | `src/agents/recommendation_engine.py` | Matches detected anomalies against a built-in runbook and generates prioritized corrective actions |
| Incident Insight Agent | `src/agents/incident_insight.py` | Consolidates anomalies, health snapshots, and recommendations into human-readable reports for notification delivery |

### Detection Algorithms

| Detector | Module | Technique |
|----------|--------|-----------|
| Z-Score Detector | `src/detectors/zscore_detector.py` | Computes z-scores against hourly/day-of-week baselines; classifies into MEDIUM/HIGH/CRITICAL severity |
| Seasonal Detector | `src/detectors/seasonal_detector.py` | Builds hourly-by-day-of-week baselines from historical data; flags observations beyond configurable σ thresholds |

### Communication Pattern

All agent communication is **in-process, synchronous Python method calls**. There is no inter-service messaging, no HTTP between agents, and no event bus. The pipeline flows:

1. `AnomalyDetectionAgent.analyze()` → produces `AnomalyEvent` list
2. `ServiceHealthAgent.assess()` / `correlate()` → enriches events with health + correlated services
3. `RecommendationEngine.recommend()` → attaches corrective actions
4. `IncidentInsightAgent.generate_report()` → produces `AnomalyReport`

### Infrastructure Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11 | Application language |
| Containerization | Docker (python:3.11-slim) | Single-container deployment |
| Metrics Source | Prometheus (planned) | External metrics ingestion endpoint |
| Alerting | Webhook / PagerDuty (configured) | Notification delivery channels |
| Dashboard | Grafana (planned) | Visualization (referenced in README, dashboard file absent) |

---

## 2. Data Models

### Transaction Domain

| Class | Module | Key Fields | Purpose |
|-------|--------|-----------|---------|
| `TransactionVolume` | `src/models/transaction.py` | `timestamp`, `service_name`, `endpoint`, `count`, `error_count`, `avg_latency_ms`, `p99_latency_ms` | A single time-bucketed observation of request volume and performance |
| `VolumeBaseline` | `src/models/transaction.py` | `service_name`, `endpoint`, `hour_of_day`, `day_of_week`, `mean_count`, `std_count`, `mean_latency_ms`, `std_latency_ms`, `sample_size` | Statistical expectation for a given hour/day combination |
| `VolumeTimeSeries` | `src/models/transaction.py` | `service_name`, `endpoint`, `observations: list[TransactionVolume]` | Ordered collection of observations for one service endpoint |

### Anomaly Domain

| Class | Module | Key Fields | Purpose |
|-------|--------|-----------|---------|
| `AnomalyEvent` | `src/models/anomaly.py` | `anomaly_id`, `anomaly_type`, `severity`, `service_name`, `endpoint`, `detected_at`, `observed_value`, `expected_value`, `deviation_score`, `correlated_services`, `recommended_actions` | A single detected anomaly event |
| `AnomalyReport` | `src/models/anomaly.py` | `report_id`, `generated_at`, `time_window_start/end`, `anomalies`, `affected_services`, `summary`, `recommended_actions` | Consolidated incident report |
| `AnomalySeverity` | `src/models/anomaly.py` | Enum: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | Severity classification |
| `AnomalyType` | `src/models/anomaly.py` | Enum: `VOLUME_SPIKE`, `VOLUME_DROP`, `LATENCY_SPIKE`, `ERROR_RATE_SPIKE`, `PATTERN_SHIFT` | Type classification |

### Service Health Domain

| Class | Module | Key Fields | Purpose |
|-------|--------|-----------|---------|
| `ServiceHealthSnapshot` | `src/models/service_health.py` | `service_name`, `timestamp`, `status`, `cpu_utilization`, `memory_utilization`, `active_pods`, `desired_pods`, `avg_response_time_ms`, `error_rate`, `request_rate` | Point-in-time health record |
| `ServiceDependency` | `src/models/service_health.py` | `source_service`, `target_service`, `dependency_type`, `criticality` | Directed dependency edge |
| `ServiceMap` | `src/models/service_health.py` | `services`, `dependencies` | Graph of service topology with upstream/downstream queries |
| `HealthStatus` | `src/models/service_health.py` | Enum: `HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNKNOWN` | Health state classification |

### Recommendation Domain

| Class | Module | Key Fields | Purpose |
|-------|--------|-----------|---------|
| `Recommendation` | `src/agents/recommendation_engine.py` | `action`, `confidence`, `source`, `priority`, `details` | A single corrective action suggestion |
| `RunbookEntry` | `src/agents/recommendation_engine.py` | `anomaly_types`, `severity_threshold`, `actions`, `description` | Pattern-to-action mapping in the knowledge base |

---

## 3. API Surface Map

This is a **library/CLI application**, not a web service. It exposes no HTTP endpoints of its own. Interactions are:

### CLI Entry Points

| Command | Description |
|---------|-------------|
| `python -m src.agents.anomaly_detector --data <csv_path>` | Run batch anomaly detection on historical CSV data |
| `python -m src.agents.anomaly_detector --mode=live` | Start live monitoring mode (polls Prometheus endpoint) |
| `python -m src.utils.generate_sample_data` | Generate sample historical data (referenced in README, not implemented) |

### External Integration Points (Outbound)

| Integration | Protocol | Configuration |
|-------------|----------|---------------|
| Prometheus Metrics | HTTP (HTTPX client) | `METRICS_ENDPOINT` env var |
| Slack Webhook | HTTP POST | `ALERT_WEBHOOK_URL` env var |
| PagerDuty | HTTP POST | `PAGERDUTY_ROUTING_KEY` env var |
| Grafana Dashboard | HTTP (links) | `GRAFANA_URL` env var |

### Monitored Services (from config)

| Service | Endpoints |
|---------|-----------|
| `payment-service` | `/api/v1/payments`, `/api/v1/payments/status` |
| `order-service` | `/api/v1/orders`, `/api/v1/orders/status` |
| `auth-service` | `/api/v1/auth/login`, `/api/v1/auth/token` |
| `notification-service` | `/api/v1/notifications/send` |

---

## 4. Business Logic Inventory

### Baseline Construction

1. Load historical CSV data (columns: `timestamp`, `service_name`, `endpoint`, `count`, `error_count`, `avg_latency_ms`, `p99_latency_ms`)
2. Group observations by `(hour_of_day, day_of_week)` per service/endpoint
3. Require minimum sample count (`min_samples=4` by default) before creating a baseline
4. Compute `mean` and `std` (sample standard deviation) for counts and latency

### Anomaly Detection Pipeline

1. **Seasonal Detection**: Compare observation count against its hour/dow baseline; flag if deviation > `deviation_threshold` (default 2.5σ)
2. **Z-Score Volume Detection**: Compute z-score against matching baseline; flag if |z| > `warning_threshold` (default 2.0σ)
3. **Z-Score Latency Detection**: Compute z-score for `avg_latency_ms`; flag if above warning threshold

### Severity Classification

| Detector | MEDIUM | HIGH | CRITICAL |
|----------|--------|------|----------|
| Z-Score | ≥ 2.0σ | ≥ 3.0σ | ≥ 6.0σ |
| Seasonal | ≥ 2.5σ | ≥ 3.75σ | ≥ 6.25σ |

### Runbook Matching

The `RecommendationEngine` matches anomalies against 4 built-in runbook entries:

| Anomaly Type | Severity Threshold | Actions Count |
|-------------|-------------------|---------------|
| `VOLUME_DROP` | HIGH | 4 actions (upstream health, LB config, deployments, DNS) |
| `VOLUME_SPIKE` | HIGH | 4 actions (retry storms, rate limiting, auto-scaling, batch overlap) |
| `LATENCY_SPIKE` | MEDIUM | 4 actions (connection pools, slow queries, resource contention, cache) |
| `ERROR_RATE_SPIKE` | MEDIUM | 4 actions (error logs, dependency availability, config changes, certs) |

### Alerting Controls

- **Cooldown**: 15 minutes between notifications for the same anomaly
- **Deduplication window**: 30 minutes
- **Severity routing**: HIGH/CRITICAL → Webhook; CRITICAL only → PagerDuty

---

## 5. Integration Points

| System | Direction | Protocol | Status |
|--------|-----------|----------|--------|
| Prometheus | Inbound (metrics pull) | HTTP/HTTPX | Configured via env var; client module referenced but not implemented (`src/utils/metrics_client.py` absent) |
| Slack | Outbound (alerts) | Webhook POST | Configured in `detection_rules.yaml`; notification module referenced but not implemented (`src/utils/notification.py` absent) |
| PagerDuty | Outbound (critical alerts) | API POST | Configured in `detection_rules.yaml`; not implemented |
| Grafana | Reference (dashboard links) | HTTP | URL configured; dashboard JSON file referenced in README but absent |
| CSV Files | Inbound (historical data) | Filesystem | Fully implemented in `AnomalyDetectionAgent.load_historical_data()` |

---

## 6. Build and Deployment Summary

### Dependencies (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic` | ≥ 2.5.0 | Data validation (declared but not used in current code — models use `dataclass`) |
| `pyyaml` | ≥ 6.0.1 | YAML config parsing |
| `httpx` | ≥ 0.25.0 | Async HTTP client for Prometheus/webhook calls |
| `structlog` | ≥ 23.2.0 | Structured logging (declared but current code uses stdlib `logging`) |
| `python-dotenv` | ≥ 1.0.0 | Environment variable loading from `.env` |
| `prometheus-client` | ≥ 0.19.0 | Prometheus metrics exposition |
| `pytest` | ≥ 7.4.0 | Test framework |

### Container Build

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

### Runtime Configuration

- Environment variables loaded from `.env` file (see `.env.example`)
- Detection rules loaded from `config/detection_rules.yaml`
- Baseline config stored in `data/baselines/baseline_config.json`
- Historical data stored in `data/historical/sample_transactions.csv`

### CI/CD

No CI/CD pipeline is configured in the repository.

### Test Execution

```bash
PYTHONPATH=/home/ubuntu/repos/uc-volume-anomaly-detection python -m pytest tests/ -v
```

Single test file: `tests/test_detectors.py` with 8 test cases covering Z-score detection, seasonal baseline building, and statistical helper functions.
