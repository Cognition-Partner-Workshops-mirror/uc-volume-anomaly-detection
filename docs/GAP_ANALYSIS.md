# GAP_ANALYSIS.md — NAS Capacity Pulse

> Engineering gap assessment across 7 categories. Updated to reflect current codebase with 58 passing tests, env-var secrets, and comprehensive documentation.
>
> 32 gaps: 0 Critical, 12 High, 12 Medium, 8 Low.

---

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Organization | 0 | 2 | 2 | 1 | 5 |
| Error Handling | 0 | 2 | 2 | 1 | 5 |
| Testing | 0 | 2 | 2 | 1 | 5 |
| Security | 0 | 2 | 2 | 1 | 5 |
| API Design | 0 | 1 | 2 | 1 | 4 |
| Observability | 0 | 1 | 1 | 2 | 4 |
| Resilience | 0 | 2 | 1 | 1 | 4 |
| **Total** | **0** | **12** | **12** | **8** | **32** |

> **Previous assessment**: 38 gaps (1 Critical). Since then: hardcoded passwords moved to env vars (SE-2 resolved), test coverage expanded from 36 to 58 tests (TE-1 downgraded from Critical), README and docs comprehensively updated.

---

## 1. Code Organization

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| CO-1 | Monolithic routes file | High | Medium | `api/routes.py` is ~1,850 lines with all endpoints in a single file. Should be split into logical routers: `dashboard.py`, `purge.py`, `config.py`, `capacity.py`. |
| CO-2 | Absent utility modules | High | Medium | Common helpers (size formatting, date calculations, validation) are scattered inline. Need a `utils/` package with `formatting.py`, `validators.py`. |
| CO-3 | No dependency injection container | Medium | Medium | Dependencies (`session_factory`, `scan_scheduler`, `app_config`) are passed via module-level `set_dependencies()`. FastAPI's DI system should be used more idiomatically. |
| CO-4 | Mixed concerns in app.py | Medium | Small | `app.py` handles startup/shutdown, static files, templates, auth routes, and scheduler. Should separate lifecycle from route registration. |
| CO-5 | Inconsistent import ordering | Low | Small | Imports don't consistently follow stdlib → third-party → local ordering. Minor readability concern. |

---

## 2. Error Handling

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| EH-1 | No centralized error handler | High | Medium | No global `@app.exception_handler`. Unhandled exceptions return raw 500 with stack traces. Need consistent JSON error envelope. |
| EH-2 | Silent failures in scanner | High | Small | `incremental_scanner.py` catches broad `Exception` and logs but continues. File-level errors could silently corrupt aggregate counts. |
| EH-3 | Inconsistent HTTP status codes | Medium | Small | Some endpoints return `{"error": "..."}` with 200 status instead of proper 4xx/5xx codes. |
| EH-4 | No error response schema | Medium | Small | Error responses lack a consistent structure — some use `{"detail"}`, others `{"error"}`, others `{"message"}`. |
| EH-5 | Missing input validation messages | Low | Small | Pydantic validation errors produce generic messages. Custom validators with descriptive errors would improve API usability. |

---

## 3. Testing

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| TE-1 | No API integration tests | High | Medium | All 58 tests are unit-level. No tests exercise FastAPI routes via `TestClient`. Need endpoint-level tests for dashboard, purge, predictions, agent report. |
| TE-2 | No end-to-end agent flow test | High | Large | No test covers the full agent → POST → DB → chart-data pipeline. Critical for validating cross-platform (Linux agent → Windows dashboard) correctness. |
| TE-3 | No test coverage measurement | Medium | Small | No `pytest-cov` configuration. Coverage reports would identify untested code paths (e.g., capacity alert email sending). |
| TE-4 | Missing edge case tests for growth predictor | Medium | Small | Growth predictor only tested with linear data. Should test with noisy data, insufficient data points, and extreme growth rates. |
| TE-5 | test_detectors.py pre-existing failure | Low | Small | `tests/test_detectors.py` has a pre-existing failure from the original anomaly detection module. Should be fixed or skipped. |

---

## 4. Security

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| SE-1 | SHA-256 password hashing | High | Small | SHA-256 is fast and vulnerable to brute-force. Should upgrade to bcrypt or argon2 with migration path for existing hashes. |
| SE-2 | Simple session token format | High | Medium | Token is `username:password_hash[:16]` — leaks hash prefix. Should use JWT with expiry and refresh tokens, or itsdangerous signed cookies. |
| SE-3 | No CSRF protection | Medium | Small | HTML forms (login, signup, settings) lack CSRF tokens. Vulnerable to cross-site request forgery attacks. |
| SE-4 | No rate limiting on auth endpoints | Medium | Small | Login/signup have no rate limiting. Susceptible to brute-force password attacks. |
| SE-5 | No HTTPS by default | Low | Small | HTTP only. Production deployments should use reverse proxy (nginx/Caddy) for TLS. Documented in README but not enforced. |

> **Resolved**: ~~SE-prev: Hardcoded passwords~~ — `DEFAULT_PASSWORD` and `SECRET_KEY` now read from environment variables with dev-mode fallbacks. `.env.example` provided.

---

## 5. API Design

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| AD-1 | No API versioning | High | Medium | All endpoints are at `/api/*` with no version prefix. Breaking changes would affect all consumers. Should version as `/api/v1/*`. |
| AD-2 | No pagination on list endpoints | Medium | Small | `/api/extensions` and `/api/sub-app-configs` return all records. Large datasets will cause slow responses. Should add `?page=&limit=`. |
| AD-3 | Inconsistent response envelopes | Medium | Small | Some responses are bare objects, others wrapped in `{data: ..., meta: ...}`. Should standardize. |
| AD-4 | OpenAPI docs not customized | Low | Small | FastAPI auto-generates Swagger UI at `/docs`, but schema descriptions and examples are sparse. |

---

## 6. Observability

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| OB-1 | No health check endpoint | High | Small | No `/health` or `/ready` endpoint. Monitoring tools and load balancers need this. |
| OB-2 | No structured logging | Medium | Medium | Logging uses basic `logging.basicConfig()` with string formatting. Should use structured JSON logs for log aggregation tools. |
| OB-3 | No request ID tracing | Low | Small | No correlation ID on requests. Makes debugging multi-request flows difficult. |
| OB-4 | No metrics endpoint | Low | Medium | No Prometheus-compatible `/metrics` endpoint. Would enable Grafana dashboards for the dashboard itself. |

---

## 7. Resilience

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| RE-1 | No graceful shutdown | High | Small | `ScanScheduler.stop()` is called but doesn't wait for in-progress scans. Long-running scans could be interrupted mid-commit. |
| RE-2 | No SQLite connection pooling | High | Small | Each request creates and closes a new session. SQLAlchemy's connection pool is not configured for optimal SQLite usage. |
| RE-3 | No retry logic for agent POST | Medium | Small | Shell agent's `curl` POST has no retry on network failure. Should retry 2-3 times with exponential backoff. |
| RE-4 | No backup for SQLite database | Low | Small | No automated backup strategy for `space_optimizer.db`. A corruption event could lose all historical data. |

---

## Improvements Since Last Assessment

| Item | Previous State | Current State |
|------|---------------|---------------|
| Hardcoded passwords | `DEFAULT_PASSWORD = "welcome123"` in source | Read from `DEFAULT_PASSWORD` env var |
| Secret key | Hardcoded in config.py | Read from `SECRET_KEY` env var |
| Test coverage | 36 unit tests | 58 tests (unit + auth + security + SQL injection) |
| Documentation | Minimal README | Comprehensive README (architecture, quick start, Grafana comparison) |
| Technical design | None | `docs/TECHNICAL_DESIGN.md` with flowcharts |
| .env.example | Did not exist | Created with all configurable env vars |
| Product naming | Mixed VADSF/NAS Capacity Pulse | Consistently "NAS Capacity Pulse" throughout |
