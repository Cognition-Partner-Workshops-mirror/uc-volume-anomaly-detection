# Gap Analysis — Volume-Based Anomaly Detection

## Table of Contents

- [1. Code Organization](#1-code-organization)
- [2. Error Handling](#2-error-handling)
- [3. Testing](#3-testing)
- [4. Security](#4-security)
- [5. API Design](#5-api-design)
- [6. Observability](#6-observability)
- [7. Resilience](#7-resilience)
- [Summary Table](#summary-table)

---

## 1. Code Organization

### Strengths
- Clean separation of concerns: agents, detectors, models, utils, config, and data directories.
- Each agent has a single responsibility with a clear interface.
- Models are isolated in `src/models/` with no circular dependencies.
- Configuration files (YAML, JSON) are separate from code.

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| CO-1 | **No CLI entry point / `__main__.py`** | Medium | Small | The `README.md` references running `python -m src.agents.anomaly_detector --data ... --mode=live`, but no `__main__.py` or `argparse` CLI exists in the codebase. The module cannot actually be run as described. |
| CO-2 | **Missing files referenced in README** | Medium | Small | `src/detectors/prophet_detector.py`, `src/utils/metrics_client.py`, `src/utils/notification.py`, `dashboards/grafana_dashboard.json`, and `docs/` are listed in the project structure but do not exist. |
| CO-3 | **Pydantic installed but unused** | Low | Small | `pydantic>=2.5.0` is in requirements.txt, but all models use `dataclasses`. Either migrate to Pydantic (for validation) or remove the dependency. |
| CO-4 | **No package-level exports** | Low | Small | All `__init__.py` files are empty. Adding explicit exports would improve the public API and enable `from src.models import TransactionVolume`. |
| CO-5 | **No type checking configuration** | Low | Small | No `pyproject.toml`, `setup.py`, `setup.cfg`, or `mypy.ini` exists. The project has type hints but no way to enforce them. |

---

## 2. Error Handling

### Strengths
- `load_historical_data` checks for file existence before proceeding.
- Division-by-zero guards exist in z-score calculations (`std_count == 0` returns `None`).
- `error_rate` property handles `count == 0` gracefully.

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| EH-1 | **No exception handling in CSV parsing** | High | Small | `load_historical_data` does not catch `KeyError`, `ValueError`, or `csv.Error`. A malformed row will crash the entire pipeline. |
| EH-2 | **No validation on model inputs** | Medium | Medium | Dataclasses accept any value — negative counts, future timestamps, or empty strings are silently accepted. No `__post_init__` validation. |
| EH-3 | **Silent failure on missing baselines** | Medium | Small | `analyze()` returns an empty list when no baselines exist for a service/endpoint, with only a `debug`-level log. This could mask configuration issues in production. |
| EH-4 | **No error handling in `_fetch_health`** | Medium | Small | The stub method will be replaced with real HTTP calls, but there's no error handling pattern (try/except, timeouts, fallback) to guide the implementation. |
| EH-5 | **`uuid4().hex[:8]` collision risk** | Low | Small | 8 hex chars (32 bits) gives ~1-in-65K collision chance after ~256 IDs. Acceptable for small scale, but should use full UUIDs for production. |

---

## 3. Testing

### Strengths
- Test structure mirrors source structure with clear test classes.
- Tests cover both positive and negative detection cases.
- Statistical helper functions have dedicated tests.
- Tests use descriptive method names (`test_no_anomaly_within_threshold`).

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| TS-1 | **No tests for agents** | High | Medium | `AnomalyDetectionAgent`, `ServiceHealthAgent`, `RecommendationEngine`, and `IncidentInsightAgent` have zero test coverage. Only detectors and stat helpers are tested. |
| TS-2 | **No integration tests** | High | Medium | No tests verify the end-to-end pipeline (load data → build baselines → detect → correlate → recommend → report). |
| TS-3 | **No test for CSV loading** | Medium | Small | `load_historical_data` is untested — no tests for missing files, malformed CSVs, or empty files. |
| TS-4 | **Test data uses incorrect day-of-week comments** | Low | Small | In `test_build_baselines`, dates Jan 6/13/20 2026 are Tuesdays (`dow=1`), but comments say "Monday 10am". The assertion `day_of_week == 0` will fail. |
| TS-5 | **No test configuration or coverage reporting** | Medium | Small | No `pytest.ini`, `pyproject.toml [tool.pytest]`, or coverage configuration. No CI pipeline to run tests automatically. |
| TS-6 | **No latency detection tests** | Medium | Small | `detect_latency` in `ZScoreDetector` has no test coverage. |

---

## 4. Security

### Strengths
- Secrets are externalized via environment variables (`.env` file).
- `.env` is in `.gitignore`, preventing accidental commits.
- YAML config uses `${VAR}` substitution for sensitive values.

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| SE-1 | **`.env` file committed to repository** | Critical | Small | A `.env` file exists in the repo (alongside `.env.example`). While `.gitignore` lists `.env`, the file is tracked. Contains `changeme` placeholder values but sets a dangerous precedent. |
| SE-2 | **No input validation on CSV data** | High | Medium | Externally provided CSV data is parsed without any sanitization. Malicious or corrupted data could cause unexpected behavior. |
| SE-3 | **No authentication for health check endpoint** | Medium | Medium | `_fetch_health` stub has no auth mechanism. When implemented, it will need token-based auth for Prometheus/service health endpoints. |
| SE-4 | **No dependency vulnerability scanning** | Medium | Small | No `safety`, `pip-audit`, `dependabot`, or `snyk` configuration for automated dependency vulnerability detection. |
| SE-5 | **No rate limiting on alert notifications** | Medium | Small | While `cooldown_minutes` and `deduplication_window_minutes` are configured, no implementation enforces these limits, risking notification floods. |

---

## 5. API Design

### Strengths
- Clean internal API boundaries between agents, detectors, and models.
- Consistent method naming conventions (`detect`, `assess`, `correlate`, `recommend`).
- Models provide computed properties for derived values.

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| AD-1 | **No REST API / HTTP interface** | High | Large | The system has no web API. It's a library that must be imported or run via CLI (which also doesn't exist). No way for external systems to submit observations or retrieve results. |
| AD-2 | **No OpenAPI / schema documentation** | Medium | Medium | No auto-generated API docs. If a REST API is added, it should include OpenAPI/Swagger specs. |
| AD-3 | **No serialization layer** | Medium | Medium | Models are dataclasses with no `to_dict()`, `to_json()`, or Pydantic serialization. Reports cannot be easily transmitted to external consumers. |
| AD-4 | **No versioning strategy** | Low | Small | No API versioning, module versioning, or `__version__` attribute. The baseline config has `"version": "1.0"` but nothing consumes it. |
| AD-5 | **Inconsistent model paradigm** | Low | Medium | `Recommendation` and `RunbookEntry` are defined inline in `recommendation_engine.py` instead of in `src/models/`. Inconsistent with other models. |

---

## 6. Observability

### Strengths
- Standard Python `logging` is used throughout all agents and detectors.
- `structlog` is in requirements (production-grade structured logging).
- `prometheus-client` is a dependency (metrics export).
- Log messages include context (service names, counts, thresholds).

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| OB-1 | **Structlog not configured or used** | High | Small | `structlog` is installed but never imported. All modules use stdlib `logging`. No structured log format (JSON, key-value) is configured. |
| OB-2 | **Prometheus client not used** | High | Medium | `prometheus-client` is installed but never imported. No metrics are exported (anomaly counts, detection latency, baseline sizes). |
| OB-3 | **No health check endpoint** | Medium | Small | No `/health` or `/ready` endpoint for container orchestration (Kubernetes liveness/readiness probes). |
| OB-4 | **No distributed tracing** | Medium | Medium | No OpenTelemetry, Jaeger, or tracing integration. Multi-agent pipelines benefit from trace propagation for debugging. |
| OB-5 | **No dashboard definition** | Medium | Medium | README references `dashboards/grafana_dashboard.json` but the file doesn't exist. No visualization of detection results. |
| OB-6 | **Logging levels inconsistent** | Low | Small | Some important operational events use `debug` level (e.g., "No baselines for X, skipping"), making them invisible in production. |

---

## 7. Resilience

### Strengths
- Detectors handle edge cases (zero std deviation, empty baselines) without crashing.
- `ServiceHealthAgent` caches health snapshots to reduce redundant fetches.
- Alert deduplication and cooldown are designed (though not implemented).

### Gaps

| ID | Gap | Severity | Effort | Details |
|----|-----|----------|--------|---------|
| RE-1 | **No retry logic for external calls** | High | Medium | `_fetch_health` and future metrics/notification clients have no retry, backoff, or timeout configuration. |
| RE-2 | **No circuit breaker pattern** | Medium | Medium | If Prometheus or health endpoints are down, the system will repeatedly attempt failed calls with no circuit-breaking behavior. |
| RE-3 | **No graceful degradation** | Medium | Medium | If the SeasonalDetector fails to build baselines (e.g., insufficient data), the entire service/endpoint is silently skipped. No fallback detection strategy. |
| RE-4 | **Cooldown/deduplication not implemented** | Medium | Medium | `config/detection_rules.yaml` defines `cooldown_minutes: 15` and `deduplication_window_minutes: 30`, but no code enforces these rules. |
| RE-5 | **No data persistence** | Medium | Medium | Baselines are computed in-memory with no persistence. A restart requires full re-computation from CSV. No database or cache layer. |
| RE-6 | **No idempotency guarantees** | Low | Small | Re-analyzing the same observation produces duplicate anomaly events in `self.detected_anomalies`. No deduplication of results. |
| RE-7 | **Live mode not implemented** | Medium | Large | The `--mode=live` option referenced in the README has no implementation. No polling loop, streaming consumer, or webhook receiver exists. |

---

## Summary Table

| Category | Gaps | Critical | High | Medium | Low |
|----------|------|----------|------|--------|-----|
| Code Organization | 5 | 0 | 0 | 2 | 3 |
| Error Handling | 5 | 0 | 1 | 3 | 1 |
| Testing | 6 | 0 | 2 | 2 | 2 |
| Security | 5 | 1 | 1 | 3 | 0 |
| API Design | 5 | 0 | 1 | 2 | 2 |
| Observability | 6 | 0 | 2 | 3 | 1 |
| Resilience | 7 | 0 | 1 | 5 | 1 |
| **Total** | **39** | **1** | **8** | **20** | **10** |

### Top Priority Items

1. **SE-1 (Critical):** Remove tracked `.env` file from repository.
2. **EH-1 (High):** Add error handling to CSV parsing.
3. **TS-1 (High):** Add tests for all four agents.
4. **TS-2 (High):** Create integration tests for the full pipeline.
5. **OB-1 (High):** Configure and use structlog for structured logging.
6. **OB-2 (High):** Implement Prometheus metrics export.
7. **AD-1 (High):** Add REST API for external integration.
8. **RE-1 (High):** Add retry logic with exponential backoff for external calls.
9. **SE-2 (High):** Add input validation for CSV data ingestion.
