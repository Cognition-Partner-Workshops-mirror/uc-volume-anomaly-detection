# GAP_ANALYSIS.md — Volume Anomaly Detection & Storage Forecaster (VADSF)

> 38 gaps across 7 engineering categories. Key findings: 1 Critical (minimal test coverage), 16 High, 13 Medium, 8 Low.

---

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Organization | 0 | 3 | 2 | 1 | 6 |
| Error Handling | 0 | 2 | 2 | 1 | 5 |
| Testing | 1 | 2 | 2 | 1 | 6 |
| Security | 0 | 3 | 2 | 1 | 6 |
| API Design | 0 | 2 | 2 | 1 | 5 |
| Observability | 0 | 2 | 2 | 1 | 5 |
| Resilience | 0 | 2 | 1 | 2 | 5 |
| **Total** | **1** | **16** | **13** | **8** | **38** |

---

## 1. Code Organization

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| CO-1 | Missing CLI entry point | High | Small | No `__main__.py` or CLI tool. Application can only be started via `uvicorn` command. Should have `python -m server_space_optimizer` entry point with argument parsing. |
| CO-2 | Monolithic routes file | High | Medium | `api/routes.py` is ~1,800 lines with all endpoints in a single file. Should be split into logical routers: `dashboard.py`, `purge.py`, `config.py`, `capacity.py`, `auth.py`. |
| CO-3 | Absent utility modules | High | Medium | Common helpers (size formatting, date calculations, validation) are scattered inline across routes. Need a `utils/` package with `formatting.py`, `validators.py`, `date_helpers.py`. |
| CO-4 | No dependency injection container | Medium | Medium | Dependencies (`session_factory`, `scan_scheduler`, `app_config`) are passed via module-level `set_dependencies()` call. FastAPI's dependency injection system should be used more idiomatically. |
| CO-5 | Mixed concerns in app.py | Medium | Small | `app.py` handles startup/shutdown, static file serving, template rendering, auth middleware, and scheduler initialization. Should separate middleware, lifecycle, and route registration. |
| CO-6 | Inconsistent import ordering | Low | Small | Imports across files don't follow a consistent convention (stdlib → third-party → local). Minor but affects readability. |

---

## 2. Error Handling

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| EH-1 | No centralized error handler | High | Medium | No global exception handler middleware. Unhandled exceptions return raw 500 with stack traces. Need `@app.exception_handler` for consistent JSON error responses. |
| EH-2 | Silent failures in scanner | High | Small | `incremental_scanner.py` catches broad `Exception` and logs but continues. File-level errors could corrupt aggregate counts without any visible indication. |
| EH-3 | Inconsistent HTTP status codes | Medium | Small | Some endpoints return `{"error": "..."}` with 200 status instead of proper 4xx/5xx. Example: `/api/config/sub-apps/{id}` returns 200 even for non-existent IDs in some paths. |
| EH-4 | No error response schema | Medium | Small | Error responses lack a consistent structure. Some use `{"detail": "..."}`, others `{"error": "..."}`, others `{"message": "..."}`. |
| EH-5 | Missing input validation messages | Low | Small | Some Pydantic validation errors produce generic messages. Custom validators with descriptive error messages would improve API usability. |

---

## 3. Testing

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| TE-1 | Minimal test coverage | **Critical** | Large | Only `test_detectors.py` exists with limited tests. No tests for API endpoints, database operations, scanner logic, auth, or capacity planning. Estimated coverage <10%. |
| TE-2 | No integration tests | High | Large | No end-to-end tests that exercise the full request cycle (HTTP → route → DB → response). Need `TestClient` based integration tests for critical flows. |
| TE-3 | No test fixtures or factories | High | Medium | No shared fixtures for database sessions, mock data, or test configuration. Each test would need to set up its own DB, making tests slow and repetitive. |
| TE-4 | Missing edge case tests | Medium | Medium | No tests for boundary conditions: empty databases, servers with no sub-apps, zero-byte files, very old timestamps, Unicode file paths. |
| TE-5 | No performance/load tests | Medium | Medium | No benchmarks for scanning large directories (10TB target), API response times under load, or database query performance with millions of file records. |
| TE-6 | No contract tests for agent API | Low | Small | The shell agent (`space_agent.sh`) POSTs JSON to `/api/agent/report` but there are no contract tests ensuring the agent's output matches the API's expected schema. |

---

## 4. Security

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| SE-1 | SHA-256 password hashing without salt | High | Small | Passwords are hashed with plain SHA-256 (`hashlib.sha256`). No salt, no key stretching. Should use `bcrypt` or `argon2` with per-user salts. |
| SE-2 | Hardcoded secret key | High | Small | `secret_key` has a default value in config. Session cookies are signed with this predictable key in production if not overridden. |
| SE-3 | No CSRF protection | High | Small | Form submissions (login, signup, settings) have no CSRF tokens. Session-based auth is vulnerable to cross-site request forgery. |
| SE-4 | No rate limiting | Medium | Small | Login endpoint has no rate limiting or account lockout. Brute-force attacks against `/login` are possible. |
| SE-5 | SQL injection surface | Medium | Small | Most queries use SQLAlchemy ORM (safe), but some use string formatting for `LIKE` clauses. Should be audited for injection vectors. |
| SE-6 | No Content Security Policy headers | Low | Small | No CSP, X-Frame-Options, or other security headers set. Dashboard pages could be embedded in iframes (clickjacking). |

---

## 5. API Design

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| AD-1 | No API versioning | High | Medium | All endpoints are under `/api/` with no version prefix. Breaking changes would affect all clients. Should use `/api/v1/`. |
| AD-2 | No OpenAPI documentation customization | High | Small | FastAPI auto-generates OpenAPI spec but endpoint descriptions and response models are incomplete. Many endpoints lack `response_model` or `summary`. |
| AD-3 | No pagination for list endpoints | Medium | Medium | `/api/config/sub-apps`, `/api/capacity-plans`, `/api/alert-logs` return all records. Need `limit`/`offset` or cursor-based pagination for large datasets. |
| AD-4 | Inconsistent query parameter naming | Medium | Small | Some endpoints use `server_name`, others use `server`. Filter parameters should follow a consistent naming convention. |
| AD-5 | No HATEOAS or resource links | Low | Small | API responses don't include links to related resources. Example: dashboard server objects don't link to their detail/purge/prediction endpoints. |

---

## 6. Observability

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| OB-1 | No health check endpoint | High | Small | No `/health` or `/ready` endpoint for load balancers or container orchestrators to check application health. (Note: a basic `/health` was added but returns minimal info.) |
| OB-2 | No metrics collection | High | Medium | No Prometheus metrics, StatsD counters, or similar. Can't track request rates, scan durations, error rates, or database query performance. |
| OB-3 | Inconsistent logging format | Medium | Small | Logging uses Python's standard `logging` module but lacks structured format (JSON). Log messages mix formats and verbosity levels. |
| OB-4 | No distributed tracing | Medium | Medium | No request ID propagation or OpenTelemetry integration. Hard to trace a request through scanner → database → response chain. |
| OB-5 | No audit logging | Low | Small | No audit trail for configuration changes, user actions, or purge operations. Settings changes and capacity plan edits are not logged. |

---

## 7. Resilience

| # | Gap | Severity | Effort | Details |
|---|-----|----------|--------|---------|
| RE-1 | No graceful shutdown | High | Small | APScheduler and background scans don't have graceful shutdown handlers. `SIGTERM` kills the process mid-scan, potentially leaving incomplete data. |
| RE-2 | No database connection pooling config | High | Small | SQLite connection is created with defaults. For concurrent requests, need `pool_size`, `pool_timeout`, and `check_same_thread=False` configuration. |
| RE-3 | No retry logic for SMTP | Medium | Small | Email sending in `_send_threshold_alert()` has no retry on transient failures. A single SMTP timeout silently drops the alert. |
| RE-4 | No circuit breaker for agent reports | Low | Medium | If the central dashboard is down, agents will fail silently. Agents should queue reports locally and retry. |
| RE-5 | No idempotency for agent reports | Low | Small | Duplicate agent reports (e.g., network retry) could create duplicate `FileMetadata` records. Need idempotency keys or upsert logic. |

---

## Severity Distribution

```
Critical (1):  TE-1 — Minimal test coverage
High    (16): CO-1, CO-2, CO-3, EH-1, EH-2, TE-2, TE-3, SE-1, SE-2, SE-3,
              AD-1, AD-2, OB-1, OB-2, RE-1, RE-2
Medium  (13): CO-4, CO-5, EH-3, EH-4, TE-4, TE-5, SE-4, SE-5, AD-3, AD-4,
              OB-3, OB-4, RE-3
Low      (8): CO-6, EH-5, TE-6, SE-6, AD-5, OB-5, RE-4, RE-5
```

---

## Effort Distribution

```
Small  (20): CO-1, CO-6, EH-2, EH-3, EH-4, EH-5, TE-6, SE-1, SE-2, SE-3,
             SE-4, SE-6, AD-2, AD-4, AD-5, OB-1, OB-3, OB-5, RE-1, RE-2, RE-3, RE-5
Medium (14): CO-2, CO-3, CO-4, CO-5, TE-3, TE-4, TE-5, SE-5, AD-1, AD-3,
             OB-2, OB-4, RE-4
Large   (4): TE-1, TE-2
```
