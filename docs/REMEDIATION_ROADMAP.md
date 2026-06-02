# Remediation Roadmap — Volume-Based Anomaly Detection

## Table of Contents

- [Phase 1: Quick Wins (High Severity / Low Effort)](#phase-1-quick-wins)
- [Phase 2: Important Improvements (High Severity / Medium Effort)](#phase-2-important-improvements)
- [Phase 3: Polish & Hardening (Medium-Low Severity)](#phase-3-polish--hardening)
- [Implementation Timeline](#implementation-timeline)

---

## Phase 1: Quick Wins

High-impact items that can be completed quickly, typically in a single session.

---

### 1.1 Remove tracked `.env` file from repository (SE-1)

**Severity:** Critical | **Effort:** Small

The `.env` file is currently tracked in the Git repository despite being listed in `.gitignore`. This file contains placeholder secrets and sets a precedent for accidental credential leaks.

**Devin prompt:**
> In the `uc-volume-anomaly-detection` repo, remove the `.env` file from Git tracking without deleting the local file. Run `git rm --cached .env` and commit the change. Verify `.env` is in `.gitignore`. Ensure `.env.example` still exists as the template.

---

### 1.2 Add error handling to CSV parsing (EH-1)

**Severity:** High | **Effort:** Small

`load_historical_data` in `src/agents/anomaly_detector.py` does not catch parsing errors. A malformed row will crash the pipeline.

**Devin prompt:**
> In `src/agents/anomaly_detector.py`, add robust error handling to the `load_historical_data` method. Wrap the CSV row parsing loop in a try/except that catches `KeyError`, `ValueError`, and `csv.Error`. Log malformed rows with a warning (including the row number and error) and skip them instead of crashing. Add a summary log at the end showing how many rows were skipped. Add unit tests in `tests/test_detectors.py` for: (1) a valid CSV, (2) a CSV with a malformed row that gets skipped, (3) an empty CSV, (4) a missing file. Always add comments in code explaining the changes done.

---

### 1.3 Fix test data day-of-week comments (TS-4)

**Severity:** Low | **Effort:** Small

In `tests/test_detectors.py`, the `test_build_baselines` test uses dates Jan 6/13/20 2026, which are Tuesdays (dow=1), not Mondays as the comments claim. The assertion `day_of_week == 0` fails.

**Devin prompt:**
> In `tests/test_detectors.py`, fix the `test_build_baselines` test. The dates January 6, 13, and 20, 2026 are Tuesdays (day_of_week=1), not Mondays. Either update the dates to actual Mondays (e.g., Jan 5, 12, 19 2026) or update the comments and assertion to expect `day_of_week == 1` (Tuesday). Run `PYTHONPATH=. pytest tests/ -v` to confirm all tests pass. Always add comments in code explaining the changes done.

---

### 1.4 Configure and use structlog (OB-1)

**Severity:** High | **Effort:** Small

`structlog` is installed but never used. All modules use stdlib `logging`.

**Devin prompt:**
> In the `uc-volume-anomaly-detection` repo, configure `structlog` for structured JSON logging. Create `src/utils/logging_config.py` that sets up structlog with JSON output, timestamp, log level, and caller info processors. Update all modules (`src/agents/*.py`, `src/detectors/*.py`) to use `structlog.get_logger()` instead of `logging.getLogger(__name__)`. Add a call to the logging config in the module entry point. Run tests to verify nothing breaks. Always add comments in code explaining the changes done.

---

### 1.5 Promote logging level for missing baselines (OB-6, EH-3)

**Severity:** Medium | **Effort:** Small

Missing baselines are logged at `debug` level, making the issue invisible in production.

**Devin prompt:**
> In `src/agents/anomaly_detector.py`, change the log level in the `analyze` method from `logger.debug("No baselines for %s, skipping")` to `logger.warning`. Add a comment explaining this is important for production visibility. Also add a metric counter if Prometheus is set up, or add a TODO comment for future metrics integration. Always add comments in code explaining the changes done.

---

### 1.6 Add `__init__.py` exports and type checking config (CO-4, CO-5)

**Severity:** Low | **Effort:** Small

Empty `__init__.py` files and no type checking configuration.

**Devin prompt:**
> In the `uc-volume-anomaly-detection` repo: (1) Add explicit exports to all `__init__.py` files — `src/models/__init__.py` should export all model classes, `src/detectors/__init__.py` should export both detectors, `src/agents/__init__.py` should export all agents. (2) Create a `pyproject.toml` with `[tool.mypy]` configuration (strict mode, ignore missing imports for third-party libs) and `[tool.pytest.ini_options]` with testpaths and pythonpath. Run `mypy src/` and fix any type errors. Always add comments in code explaining the changes done.

---

## Phase 2: Important Improvements

Higher-effort items that significantly improve reliability, testability, and functionality.

---

### 2.1 Add comprehensive agent tests (TS-1)

**Severity:** High | **Effort:** Medium

Zero test coverage for all four agents.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, create `tests/test_agents.py` with comprehensive tests for all four agents:
>
> For `AnomalyDetectionAgent`: test `load_historical_data` with sample CSV, test `build_baselines` produces correct number of baselines, test `analyze` returns anomalies for extreme observations and empty list for normal observations.
>
> For `ServiceHealthAgent`: test `assess` returns a health snapshot, test `correlate` with a mock service map that has degraded upstream/downstream services.
>
> For `RecommendationEngine`: test `recommend` matches the correct runbook entries for each anomaly type, test severity filtering (anomaly below threshold produces no recommendations), test correlated service recommendations.
>
> For `IncidentInsightAgent`: test `generate_report` with a mix of anomalies produces correct summary, test `format_for_notification` includes severity prefix and actions.
>
> Run `PYTHONPATH=. pytest tests/ -v` and ensure all tests pass. Always add comments in code explaining the changes done.

---

### 2.2 Add integration tests for full pipeline (TS-2)

**Severity:** High | **Effort:** Medium

No end-to-end test verifying the complete detection pipeline.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, create `tests/test_integration.py` with an end-to-end integration test. The test should: (1) Load `data/historical/sample_transactions.csv` via `AnomalyDetectionAgent.load_historical_data`, (2) Build baselines via `build_baselines`, (3) Create a synthetic anomalous observation (e.g., 3x normal volume) and run `analyze`, (4) Pass the anomaly to `ServiceHealthAgent.assess` and `correlate`, (5) Pass to `RecommendationEngine.recommend`, (6) Pass to `IncidentInsightAgent.generate_report`, (7) Verify the report has anomalies, affected services, recommendations, and a non-empty summary. Run with `PYTHONPATH=. pytest tests/test_integration.py -v`. Always add comments in code explaining the changes done.

---

### 2.3 Implement Prometheus metrics export (OB-2)

**Severity:** High | **Effort:** Medium

`prometheus-client` is installed but never used.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, create `src/utils/metrics.py` that defines Prometheus metrics using `prometheus_client`: (1) `anomalies_detected_total` Counter with labels `service_name`, `anomaly_type`, `severity`; (2) `detection_duration_seconds` Histogram for detection latency; (3) `baselines_computed_total` Counter; (4) `active_baselines` Gauge. Instrument `AnomalyDetectionAgent.analyze()` to increment the anomaly counter and record detection duration. Instrument `build_baselines()` to update baseline counters. Add a simple metrics HTTP server startup (e.g., `start_http_server(8000)`) that can be optionally enabled. Add tests to verify metrics increment correctly. Always add comments in code explaining the changes done.

---

### 2.4 Add input validation to models (EH-2, SE-2)

**Severity:** Medium-High | **Effort:** Medium

Models accept any values with no validation, and CSV data is not sanitized.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, add `__post_init__` validation to all dataclasses in `src/models/`:
>
> `TransactionVolume`: validate `count >= 0`, `error_count >= 0`, `error_count <= count`, `avg_latency_ms >= 0`, `p99_latency_ms >= 0`.
>
> `VolumeBaseline`: validate `0 <= hour_of_day <= 23`, `0 <= day_of_week <= 6`, `mean_count >= 0`, `std_count >= 0`, `sample_size >= 0`.
>
> `ServiceHealthSnapshot`: validate `0 <= cpu_utilization <= 1.0`, `0 <= memory_utilization <= 1.0`, `active_pods >= 0`, `error_rate >= 0`.
>
> Raise `ValueError` with descriptive messages for invalid inputs. Update CSV parsing in `anomaly_detector.py` to catch `ValueError` from model construction. Add tests for validation. Always add comments in code explaining the changes done.

---

### 2.5 Add retry logic for external calls (RE-1)

**Severity:** High | **Effort:** Medium

No retry or timeout logic for HTTP calls to metrics endpoints or health checks.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, create `src/utils/http_client.py` with a resilient HTTP client wrapper around HTTPX. Implement: (1) configurable retry with exponential backoff (default 3 retries, base 1s, max 30s), (2) configurable timeout (default 10s connect, 30s read), (3) a `fetch_with_retry(url, method, headers, **kwargs)` function that logs each retry attempt. Update `ServiceHealthAgent._fetch_health` to use this client instead of returning a stub. Add a `try/except` that falls back to `HealthStatus.UNKNOWN` on failure. Add unit tests with mocked HTTP responses (success, retry, timeout). Always add comments in code explaining the changes done.

---

### 2.6 Implement cooldown and deduplication (RE-4)

**Severity:** Medium | **Effort:** Medium

Alert cooldown and deduplication are configured but not implemented.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, implement alert deduplication and cooldown logic. Create `src/utils/deduplication.py` with an `AlertDeduplicator` class that: (1) maintains a dict of `{anomaly_key: last_alert_timestamp}`, (2) generates anomaly keys from `(service_name, endpoint, anomaly_type)`, (3) `should_alert(anomaly: AnomalyEvent) -> bool` returns `False` if the same key was alerted within `cooldown_minutes`, (4) `deduplication_window_minutes` suppresses duplicate severity levels. Load configuration from `config/detection_rules.yaml`. Integrate with `AnomalyDetectionAgent.analyze()` to filter duplicate alerts. Add tests. Always add comments in code explaining the changes done.

---

### 2.7 Add model serialization (AD-3)

**Severity:** Medium | **Effort:** Medium

Models have no JSON serialization support, making it impossible to transmit reports.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, migrate all dataclasses in `src/models/` to Pydantic v2 `BaseModel` classes (since pydantic is already a dependency). This gives you automatic JSON serialization via `.model_dump()` and `.model_dump_json()`, plus validation. Update all imports across the codebase. Ensure `Recommendation` and `RunbookEntry` in `recommendation_engine.py` are also migrated or moved to `src/models/recommendation.py`. Run all tests to confirm compatibility. Always add comments in code explaining the changes done.

---

## Phase 3: Polish & Hardening

Lower-priority items that improve the overall engineering quality.

---

### 3.1 Add REST API with FastAPI (AD-1)

**Severity:** High | **Effort:** Large

The system has no HTTP interface for external integration.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, add a FastAPI REST API. Create `src/api/` directory with:
>
> `src/api/main.py`: FastAPI app with `/health`, `/ready` endpoints.
> `src/api/routes/anomalies.py`: POST `/api/v1/analyze` (accepts a `TransactionVolume` JSON body, returns detected anomalies), GET `/api/v1/anomalies` (returns recent detected anomalies), GET `/api/v1/reports/{report_id}` (returns a specific report).
> `src/api/routes/baselines.py`: POST `/api/v1/baselines/build` (triggers baseline build from CSV path), GET `/api/v1/baselines` (returns current baselines).
>
> Add `fastapi` and `uvicorn` to `requirements.txt`. Add a Dockerfile CMD option for API mode. Create `tests/test_api.py` with httpx test client tests. Always add comments in code explaining the changes done.

---

### 3.2 Implement live monitoring mode (RE-7)

**Severity:** Medium | **Effort:** Large

`--mode=live` is referenced but not implemented.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, implement live monitoring mode. Create `src/agents/live_monitor.py` with a `LiveMonitor` class that: (1) polls a configurable metrics endpoint at a fixed interval (default 60s), (2) converts raw metrics to `TransactionVolume` objects, (3) runs the full agent pipeline (detect → health → recommend → report), (4) sends notifications via webhook for anomalies above configured severity. Also create `src/__main__.py` with argparse CLI supporting `--data <csv_path>` for batch mode and `--mode live` for live polling. Add `--config` flag to specify detection rules YAML. Add signal handling for graceful shutdown. Always add comments in code explaining the changes done.

---

### 3.3 Add missing utility modules (CO-2)

**Severity:** Medium | **Effort:** Medium

`metrics_client.py`, `notification.py`, and `prophet_detector.py` are referenced in docs but don't exist.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, create the missing utility modules:
>
> `src/utils/metrics_client.py`: A `MetricsClient` class that wraps HTTPX to query Prometheus metrics. Methods: `query_range(query, start, end, step)`, `query_instant(query)`. Use the resilient HTTP client from `src/utils/http_client.py`.
>
> `src/utils/notification.py`: A `NotificationClient` with methods `send_webhook(url, payload)` and `send_pagerduty(routing_key, event)`. Load channel config from `detection_rules.yaml`. Include severity filtering.
>
> Update README.md to remove `prophet_detector.py` from the project structure (or add a stub with a TODO). Always add comments in code explaining the changes done.

---

### 3.4 Add dependency vulnerability scanning (SE-4)

**Severity:** Medium | **Effort:** Small

No automated scanning for known vulnerabilities in dependencies.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, add dependency vulnerability scanning: (1) Create `.github/workflows/security.yml` GitHub Actions workflow that runs `pip-audit` on every push and PR. (2) Add `pip-audit` to a `requirements-dev.txt` file alongside `pytest`, `mypy`, and any other dev dependencies. (3) Run `pip-audit` locally and fix any existing vulnerabilities by updating dependency versions in `requirements.txt`. Always add comments in code explaining the changes done.

---

### 3.5 Add circuit breaker pattern (RE-2)

**Severity:** Medium | **Effort:** Medium

No circuit-breaking for external service calls.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, implement a circuit breaker in `src/utils/circuit_breaker.py`. The `CircuitBreaker` class should support: (1) three states — CLOSED, OPEN, HALF_OPEN; (2) configurable failure threshold (default 5), reset timeout (default 60s), and half-open max calls (default 1); (3) decorator pattern `@circuit_breaker` for wrapping async/sync calls; (4) fallback function support. Integrate with `ServiceHealthAgent._fetch_health` and future metrics/notification clients. Add comprehensive tests for state transitions. Always add comments in code explaining the changes done.

---

### 3.6 Add distributed tracing with OpenTelemetry (OB-4)

**Severity:** Medium | **Effort:** Medium

No tracing across the multi-agent pipeline.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, add OpenTelemetry tracing. Install `opentelemetry-api`, `opentelemetry-sdk`, and `opentelemetry-exporter-otlp`. Create `src/utils/tracing.py` that configures a TracerProvider with OTLP exporter (configurable endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT` env var). Add spans to: `AnomalyDetectionAgent.analyze()` (parent span), `SeasonalDetector.detect()`, `ZScoreDetector.detect()`, `ServiceHealthAgent.correlate()`, `RecommendationEngine.recommend()`, and `IncidentInsightAgent.generate_report()`. Include anomaly IDs and service names as span attributes. Always add comments in code explaining the changes done.

---

### 3.7 Add data persistence layer (RE-5)

**Severity:** Medium | **Effort:** Medium

Baselines and anomaly events are in-memory only.

**Devin prompt:**
> In `uc-volume-anomaly-detection`, add a lightweight persistence layer using SQLite. Create `src/utils/storage.py` with a `Storage` class that: (1) persists `VolumeBaseline` objects to a `baselines` table, (2) persists `AnomalyEvent` objects to an `anomalies` table, (3) persists `AnomalyReport` objects to a `reports` table. Use Python's built-in `sqlite3` module. Add methods: `save_baselines()`, `load_baselines()`, `save_anomaly()`, `get_recent_anomalies(hours=24)`, `save_report()`, `get_report(report_id)`. Integrate with `AnomalyDetectionAgent` to auto-persist baselines after building and anomalies after detection. Default database path: `data/anomaly_detection.db`. Add tests. Always add comments in code explaining the changes done.

---

### 3.8 Remove unused Pydantic dependency or migrate (CO-3)

**Severity:** Low | **Effort:** Small (remove) or Medium (migrate)

Pydantic is installed but all models use dataclasses.

> **Note:** If Phase 2 item 2.7 (model serialization via Pydantic migration) is completed, this gap is automatically resolved. Otherwise:

**Devin prompt:**
> In `uc-volume-anomaly-detection`, remove `pydantic>=2.5.0` from `requirements.txt` since it is not used anywhere in the codebase. Run `pip install -r requirements.txt` to verify the remaining dependencies are sufficient. Run all tests to confirm nothing breaks. Always add comments in code explaining the changes done.

---

## Implementation Timeline

| Phase | Items | Estimated Sessions | Priority |
|-------|-------|-------------------|----------|
| **Phase 1** | 6 items | 3-4 sessions | Immediate |
| **Phase 2** | 7 items | 5-7 sessions | Next sprint |
| **Phase 3** | 8 items | 6-10 sessions | Backlog |

### Dependency Graph

```
Phase 1:
  1.1 (remove .env)         → independent
  1.2 (CSV error handling)   → independent
  1.3 (fix test data)        → independent
  1.4 (structlog)            → independent
  1.5 (log levels)           → depends on 1.4
  1.6 (exports + pyproject)  → independent

Phase 2:
  2.1 (agent tests)          → benefits from 1.2, 1.3
  2.2 (integration tests)    → depends on 2.1
  2.3 (prometheus metrics)   → benefits from 1.4
  2.4 (input validation)     → benefits from 1.2
  2.5 (retry logic)          → independent
  2.6 (deduplication)        → independent
  2.7 (model serialization)  → independent

Phase 3:
  3.1 (REST API)             → depends on 2.7
  3.2 (live monitoring)      → depends on 3.1, 3.3
  3.3 (utility modules)      → depends on 2.5
  3.4 (security scanning)    → independent
  3.5 (circuit breaker)      → depends on 2.5
  3.6 (tracing)              → independent
  3.7 (persistence)          → depends on 2.7
  3.8 (remove pydantic)      → conflicts with 2.7 (do one or the other)
```
