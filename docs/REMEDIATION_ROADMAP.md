# Remediation Roadmap — Volume-Based Anomaly Detection System

## Overview

This roadmap prioritizes the 38 gaps identified in the [Gap Analysis](./GAP_ANALYSIS.md) into three phases:

- **Phase 1 — Quick Wins**: High severity + Small/Medium effort. Immediately improve production-readiness.
- **Phase 2 — Important**: High severity + Medium/Large effort or Critical items. Core functionality completeness.
- **Phase 3 — Polish**: Medium/Low severity improvements for long-term maintainability and scale.

---

## Phase 1 — Quick Wins (1–2 weeks)

### 1.1 Add CLI entry point with argument parsing

**Gap refs**: 1.2, 5.4  
**Severity**: High | **Effort**: Small

Create a `__main__.py` or add `if __name__ == "__main__"` block with `argparse` to support the documented `--data` and `--mode` CLI flags.

**Devin prompt**:
> Add a CLI entry point to `src/agents/anomaly_detector.py` using argparse. Support `--data <csv_path>` for batch mode and `--mode live` for continuous monitoring. Load config from `config/detection_rules.yaml` and environment variables from `.env`. The entry point should: (1) parse args, (2) load config, (3) build baselines from historical data, (4) if batch mode — analyze all observations and print a report; if live mode — log a message that live polling will start. Add `if __name__ == "__main__"` block.

---

### 1.2 Add custom exception classes

**Gap refs**: 2.1  
**Severity**: High | **Effort**: Small

Create `src/exceptions.py` with domain exceptions for configuration errors, data loading failures, and detection pipeline errors.

**Devin prompt**:
> Create `src/exceptions.py` with the following custom exception classes: `ConfigurationError` (invalid YAML config or missing env vars), `DataLoadError` (CSV parsing or file-not-found errors), `DetectionPipelineError` (baseline building or analysis failures), and `NotificationError` (webhook/PagerDuty delivery failures). Update `anomaly_detector.py` to raise `DataLoadError` instead of returning empty dict on missing file. Add comments explaining each exception class.

---

### 1.3 Add input validation for CSV loading

**Gap refs**: 2.2  
**Severity**: High | **Effort**: Small

Validate CSV headers, data types, and handle malformed rows gracefully.

**Devin prompt**:
> Update `AnomalyDetectionAgent.load_historical_data()` in `src/agents/anomaly_detector.py` to: (1) validate that the CSV has required columns (`timestamp`, `service_name`, `endpoint`, `count`), raising `DataLoadError` if not; (2) wrap row parsing in try/except to skip malformed rows with a warning log; (3) validate that `count` is non-negative and `timestamp` is a valid ISO datetime. Add comments explaining the validation logic.

---

### 1.4 Switch to structured logging with structlog

**Gap refs**: 6.1, 1.4  
**Severity**: High | **Effort**: Small

Replace stdlib `logging` with the already-declared `structlog` dependency for JSON-formatted structured output.

**Devin prompt**:
> Replace all `import logging` / `logging.getLogger(__name__)` usage across the codebase with `structlog`. Create `src/logging_config.py` that configures structlog with JSON output, timestamp, log level, and module name. Update all modules (`anomaly_detector.py`, `service_health.py`, `recommendation_engine.py`, `incident_insight.py`, `zscore_detector.py`, `seasonal_detector.py`) to use `structlog.get_logger()`. Add a comment at the top of `logging_config.py` explaining the structured logging setup.

---

### 1.5 Add container health check endpoint

**Gap refs**: 5.3  
**Severity**: High | **Effort**: Small

Add a minimal HTTP health endpoint for Kubernetes liveness/readiness probes.

**Devin prompt**:
> Add a lightweight health check HTTP server to the anomaly detection system. Create `src/health.py` with a simple HTTP server (using Python's `http.server` or a minimal HTTPX/aiohttp approach) that responds to `GET /health` with `{"status": "ok", "uptime_seconds": <n>}`. Start it on port 8080 in a background thread from the main entry point. Update the Dockerfile to add `HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1`. Add comments explaining the health check purpose.

---

### 1.6 Add graceful shutdown handling

**Gap refs**: 7.1  
**Severity**: High | **Effort**: Small

Register signal handlers for SIGTERM/SIGINT to flush pending notifications and log a clean shutdown.

**Devin prompt**:
> Add graceful shutdown handling to `src/agents/anomaly_detector.py`. Register handlers for `SIGTERM` and `SIGINT` signals that: (1) log "Shutdown signal received", (2) set a `_shutdown` flag that the live-mode polling loop checks, (3) flush any pending anomaly report to the notification channel before exiting. Use Python's `signal` module. Add a comment explaining the shutdown flow.

---

### 1.7 Add unit tests for all agents

**Gap refs**: 3.3, 3.4, 3.5  
**Severity**: High | **Effort**: Small

Add test files for `RecommendationEngine`, `IncidentInsightAgent`, and `ServiceHealthAgent`.

**Devin prompt**:
> Create three new test files: (1) `tests/test_recommendation_engine.py` — test that `RecommendationEngine.recommend()` returns correct actions for each `AnomalyType`/`AnomalySeverity` combination, test that correlated services add heuristic recommendations, test that severity below threshold produces no results; (2) `tests/test_incident_insight.py` — test `generate_report()` produces correct summary text, test `format_for_notification()` output format, test deduplication of recommended actions; (3) `tests/test_service_health.py` — test `ServiceHealthAgent.assess()` returns snapshot, test `correlate()` finds upstream/downstream degraded services using a mock `ServiceMap`. Use pytest with descriptive test names. Add comments explaining test scenarios.

---

### 1.8 Add `pyproject.toml` for proper packaging

**Gap refs**: 1.6  
**Severity**: Medium | **Effort**: Small

Create a `pyproject.toml` with project metadata, dependencies, and tool configuration.

**Devin prompt**:
> Create a `pyproject.toml` at the project root with: (1) `[project]` section with name="volume-anomaly-detection", version="0.1.0", requires-python=">=3.11", dependencies copied from requirements.txt; (2) `[tool.pytest.ini_options]` with testpaths=["tests"], python_files="test_*.py"; (3) `[tool.ruff]` with line-length=120 and target-version="py311". Keep `requirements.txt` for Docker builds. Add a comment in pyproject.toml explaining it serves as the canonical package definition.

---

## Phase 2 — Important (2–4 weeks)

### 2.1 Implement metrics client for Prometheus integration

**Gap refs**: 1.1, 1.7  
**Severity**: High | **Effort**: Medium

Implement the `src/utils/metrics_client.py` module for fetching live metrics from Prometheus.

**Devin prompt**:
> Create `src/utils/metrics_client.py` implementing a `MetricsClient` class that: (1) connects to a Prometheus endpoint (URL from `METRICS_ENDPOINT` env var); (2) has a method `query_volume(service_name, endpoint, time_range)` that executes a PromQL `rate()` query and returns a list of `TransactionVolume` objects; (3) has a method `query_latency(service_name, endpoint, time_range)` for latency percentiles; (4) uses `httpx.AsyncClient` with configurable timeout (30s default) and auth token from `METRICS_AUTH_TOKEN`; (5) includes retry logic with exponential backoff (3 attempts). Add comprehensive error handling raising `NotificationError` on failures. Add comments explaining the PromQL queries used.

---

### 2.2 Implement notification delivery module

**Gap refs**: 1.1, 1.7, 7.4  
**Severity**: High | **Effort**: Medium

Implement `src/utils/notification.py` with webhook and PagerDuty delivery, including cooldown/deduplication.

**Devin prompt**:
> Create `src/utils/notification.py` implementing a `NotificationDispatcher` class that: (1) sends formatted alerts to Slack webhook (`ALERT_WEBHOOK_URL`); (2) sends critical alerts to PagerDuty (`PAGERDUTY_ROUTING_KEY`); (3) implements cooldown logic (configurable, default 15 min) using an in-memory timestamp cache keyed by `(service_name, anomaly_type)`; (4) implements deduplication window (default 30 min) to suppress duplicate alerts; (5) uses `httpx` with timeout and basic retry. Load config from `config/detection_rules.yaml`. Add comments explaining the cooldown and dedup logic.

---

### 2.3 Implement alert deduplication and cooldown

**Gap refs**: 7.4, 7.6  
**Severity**: High | **Effort**: Medium

Ensure the YAML-configured cooldown and deduplication logic is actually enforced in the detection pipeline.

**Devin prompt**:
> Add an `AlertDeduplicator` class to `src/utils/notification.py` (or a new `src/utils/deduplication.py`) that: (1) maintains a TTL cache of recently sent alerts keyed by `(service_name, endpoint, anomaly_type)`; (2) checks `cooldown_minutes` (default 15) before allowing a new alert; (3) checks `deduplication_window_minutes` (default 30) to suppress identical anomaly descriptions; (4) exposes `should_alert(anomaly: AnomalyEvent) -> bool`. Wire this into `IncidentInsightAgent.format_for_notification()` flow. Add comments explaining the deduplication strategy.

---

### 2.4 Add detection state persistence

**Gap refs**: 7.5  
**Severity**: High | **Effort**: Medium

Persist detected anomalies and baselines to disk (SQLite or JSON) so state survives restarts.

**Devin prompt**:
> Create `src/utils/state_store.py` implementing a `StateStore` class that: (1) persists baselines to `data/baselines/computed_baselines.json` after `build_baselines()`; (2) persists recent anomaly events to `data/state/recent_anomalies.json` (rolling 24-hour window); (3) loads persisted state on startup in `AnomalyDetectionAgent.__init__()`; (4) uses file locking (`fcntl`) for safe concurrent writes. Update `anomaly_detector.py` to use `StateStore`. Add comments explaining the persistence strategy and file format.

---

### 2.5 Implement end-to-end integration test

**Gap refs**: 3.1, 3.2  
**Severity**: Critical → High | **Effort**: Medium

Create a full pipeline integration test using the sample CSV data.

**Devin prompt**:
> Create `tests/test_integration.py` with an end-to-end test that: (1) loads `data/historical/sample_transactions.csv` into `AnomalyDetectionAgent`; (2) builds baselines; (3) creates a synthetic anomalous observation (count = 5x the baseline mean); (4) runs `analyze()` and asserts anomalies are detected; (5) passes anomalies through `ServiceHealthAgent.assess()` and `correlate()`; (6) passes through `RecommendationEngine.recommend()`; (7) passes through `IncidentInsightAgent.generate_report()`; (8) asserts the final report has non-empty summary, affected_services, and recommended_actions. Add comments explaining the integration test flow.

---

### 2.6 Add Prometheus metrics exposition

**Gap refs**: 6.2  
**Severity**: High | **Effort**: Medium

Expose operational metrics (anomalies detected, processing duration, errors) using the `prometheus-client` library.

**Devin prompt**:
> Create `src/utils/metrics_exposition.py` that defines and exposes the following Prometheus metrics using `prometheus_client`: (1) `anomalies_detected_total` Counter (labels: service_name, anomaly_type, severity); (2) `detection_duration_seconds` Histogram; (3) `baselines_loaded_total` Gauge; (4) `notifications_sent_total` Counter (labels: channel, status). Start a metrics HTTP server on port 9090 in a background thread. Instrument `AnomalyDetectionAgent.analyze()` and baseline-building. Add comments explaining each metric's purpose.

---

### 2.7 Fix deprecated `datetime.utcnow()` usage

**Gap refs**: 6.5  
**Severity**: Low | **Effort**: Small

Replace all `datetime.utcnow()` calls with `datetime.now(timezone.utc)`.

**Devin prompt**:
> Replace all occurrences of `datetime.utcnow()` across the codebase with `datetime.now(timezone.utc)`. Files affected: `src/agents/service_health.py`, `src/agents/incident_insight.py`, `src/detectors/zscore_detector.py`, `src/detectors/seasonal_detector.py`. Add `from datetime import timezone` to the import section of each affected file. Add a comment noting the migration from the deprecated API.

---

## Phase 3 — Polish (4–8 weeks)

### 3.1 Add REST API with FastAPI

**Gap refs**: 5.1, 5.2  
**Severity**: Medium | **Effort**: Large

Expose HTTP endpoints for triggering analysis, querying results, and managing baselines.

**Devin prompt**:
> Create `src/api/` package with a FastAPI application: (1) `src/api/app.py` with FastAPI instance; (2) `GET /api/v1/anomalies` — list recent anomalies with pagination; (3) `POST /api/v1/analyze` — trigger analysis on a time window; (4) `GET /api/v1/baselines/{service_name}` — retrieve baselines; (5) `GET /api/v1/health` — health check; (6) Auto-generate OpenAPI spec via FastAPI. Add `fastapi` and `uvicorn` to `requirements.txt`. Add comments explaining each endpoint's purpose and expected request/response shapes.

---

### 3.2 Add distributed tracing with OpenTelemetry

**Gap refs**: 6.3  
**Severity**: Medium | **Effort**: Medium

Instrument the detection pipeline with OpenTelemetry spans for observability.

**Devin prompt**:
> Add OpenTelemetry tracing to the anomaly detection pipeline. Add `opentelemetry-api`, `opentelemetry-sdk`, and `opentelemetry-exporter-otlp` to requirements.txt. Create `src/utils/tracing.py` that initializes a tracer provider with OTLP exporter (endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT` env var). Add spans to: `AnomalyDetectionAgent.analyze()`, `ServiceHealthAgent.correlate()`, `RecommendationEngine.recommend()`, `IncidentInsightAgent.generate_report()`. Include anomaly_id, service_name as span attributes. Add comments explaining the tracing setup.

---

### 3.3 Create Grafana dashboard

**Gap refs**: 6.4  
**Severity**: Medium | **Effort**: Medium

Create the `dashboards/grafana_dashboard.json` referenced in the README.

**Devin prompt**:
> Create `dashboards/grafana_dashboard.json` with a Grafana dashboard definition (JSON model) that includes: (1) Panel: Anomalies detected over time (counter graph); (2) Panel: Detection latency histogram; (3) Panel: Active baselines gauge; (4) Panel: Notifications sent by channel; (5) Panel: Service health status table; (6) Variables for service_name and time_range filtering. Target Prometheus as the data source. Add a comment block at the top explaining panel layout.

---

### 3.4 Add dependency vulnerability scanning

**Gap refs**: 4.3  
**Severity**: Medium | **Effort**: Small

Add `pip-audit` to the development workflow and CI (when CI is configured).

**Devin prompt**:
> Add dependency vulnerability scanning: (1) Add `pip-audit` to requirements.txt (as a dev dependency section or separate `requirements-dev.txt`); (2) Create a `Makefile` with targets: `lint` (ruff), `test` (pytest), `audit` (pip-audit), and `all` (run all three); (3) Add a `scripts/check_deps.sh` that runs `pip-audit --strict` and exits non-zero on vulnerabilities. Add comments explaining each Makefile target.

---

### 3.5 Add circuit breaker for external calls

**Gap refs**: 7.2, 7.3  
**Severity**: Medium | **Effort**: Medium

Implement circuit breaker pattern for Prometheus and notification delivery calls.

**Devin prompt**:
> Add a circuit breaker implementation for external HTTP calls. Create `src/utils/circuit_breaker.py` implementing a `CircuitBreaker` class with states (CLOSED, OPEN, HALF_OPEN), configurable failure_threshold (default 5), recovery_timeout (default 60s), and half_open_max_calls (default 1). Wrap `MetricsClient` and `NotificationDispatcher` calls with the circuit breaker. Add retry with exponential backoff (base 1s, max 30s, 3 attempts) before tripping the breaker. Add comments explaining the state machine transitions.

---

### 3.6 Remove unused Pydantic dependency or migrate models

**Gap refs**: 1.3  
**Severity**: Low | **Effort**: Medium

Either remove `pydantic` from requirements or migrate `dataclass` models to Pydantic `BaseModel` for validation benefits.

**Devin prompt**:
> Migrate all dataclass models in `src/models/` to Pydantic v2 `BaseModel` classes: (1) `transaction.py` — convert `TransactionVolume`, `VolumeBaseline`, `VolumeTimeSeries`; (2) `anomaly.py` — convert `AnomalyEvent`, `AnomalyReport`; (3) `service_health.py` — convert `ServiceHealthSnapshot`, `ServiceDependency`, `ServiceMap`. Keep `Recommendation` and `RunbookEntry` in `recommendation_engine.py` as dataclasses (internal only). Use Pydantic validators for field constraints (e.g., `count >= 0`, `hour_of_day` 0-23). Update all imports across the codebase. Add comments explaining validation constraints.

---

### 3.7 Implement Prophet-based detector

**Gap refs**: 1.5  
**Severity**: Low | **Effort**: Medium

Implement the `prophet_detector.py` referenced in the README for advanced forecasting.

**Devin prompt**:
> Create `src/detectors/prophet_detector.py` implementing a `ProphetDetector` class that: (1) uses Facebook Prophet (add `prophet` to requirements.txt) for time-series forecasting; (2) has `fit(series: VolumeTimeSeries)` to train on historical data; (3) has `detect(observation: TransactionVolume) -> Optional[AnomalyEvent]` that checks if the observation falls outside Prophet's uncertainty interval; (4) configurable `interval_width` (default 0.95). Add to the detection pipeline in `AnomalyDetectionAgent` as an optional third detector. Add comments explaining the Prophet model configuration.

---

### 3.8 Add CI/CD pipeline

**Gap refs**: General  
**Severity**: Medium | **Effort**: Medium

Create GitHub Actions workflow for lint, test, audit, and Docker build.

**Devin prompt**:
> Create `.github/workflows/ci.yml` with a GitHub Actions pipeline: (1) Trigger on push to main and pull requests; (2) Job `lint`: run `ruff check src/ tests/`; (3) Job `test`: run `pytest tests/ -v --tb=short` with Python 3.11; (4) Job `audit`: run `pip-audit --strict`; (5) Job `docker-build`: build the Docker image and verify it starts cleanly (run container, wait 5s, check health endpoint); (6) Cache pip dependencies. Add comments explaining each job's purpose.

---

## Summary

| Phase | Items | Focus |
|-------|-------|-------|
| Phase 1 | 8 items | Functional CLI, error handling, testing, logging, health checks |
| Phase 2 | 7 items | Metrics client, notifications, persistence, integration tests, metrics exposition |
| Phase 3 | 8 items | REST API, tracing, dashboard, vulnerability scanning, circuit breaker, CI/CD |

**Estimated total effort**: 8–12 weeks for a single developer working sequentially. Phases can overlap — Phase 1 items are independent and parallelizable.
