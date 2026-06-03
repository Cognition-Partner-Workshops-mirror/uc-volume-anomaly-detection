# REMEDIATION_ROADMAP.md — Volume Anomaly Detection & Storage Forecaster (VADSF)

> Phased plan with executable Devin prompts: Phase 1 (8 quick wins, 1–2 weeks), Phase 2 (7 important items, 2–4 weeks), Phase 3 (8 polish items, 4–8 weeks).

---

## Phase 1 — Quick Wins (1–2 Weeks)

High severity + low effort items that immediately improve reliability and security.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 1.1 | Add `__main__.py` CLI entry point | CO-1 | Small |
| 1.2 | Add global exception handler middleware | EH-1 | Small |
| 1.3 | Upgrade password hashing to bcrypt | SE-1 | Small |
| 1.4 | Move secret key to environment variable | SE-2 | Small |
| 1.5 | Add CSRF protection to forms | SE-3 | Small |
| 1.6 | Add graceful shutdown handlers | RE-1 | Small |
| 1.7 | Configure SQLite connection pooling | RE-2 | Small |
| 1.8 | Enhance health check endpoint | OB-1 | Small |

### 1.1 — Add `__main__.py` CLI entry point

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `server_space_optimizer/__main__.py` that uses `argparse` to accept `--host` (default `0.0.0.0`), `--port` (default `8080`), `--config` (path to YAML config), and `--generate-demo` flags. When `--generate-demo` is passed, run `generate_demo_data` before starting. Start `uvicorn` programmatically with the parsed arguments. Add a comment explaining this enables `python -m server_space_optimizer` usage.

### 1.2 — Add global exception handler middleware

**Devin Prompt:**
> In `server_space_optimizer/app.py`, add a `@app.exception_handler(Exception)` that catches all unhandled exceptions and returns a JSON response `{"error": "Internal server error", "detail": str(exc)}` with status 500. Also add handlers for `RequestValidationError` (422) and `HTTPException`. Log every exception with `logger.exception()`. Add a comment explaining centralized error handling.

### 1.3 — Upgrade password hashing to bcrypt

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `bcrypt` to `requirements.txt`. Update `server_space_optimizer/models/database.py`: replace the `hash_password()` function to use `bcrypt.hashpw()` with `bcrypt.gensalt()`. Add a `verify_password()` function using `bcrypt.checkpw()`. Update `auth_manager.py` to use `verify_password()` instead of comparing SHA-256 hashes directly. Add a migration path: if login with bcrypt fails, try SHA-256 and if it matches, re-hash with bcrypt and update the DB record. Add comments explaining the migration.

### 1.4 — Move secret key to environment variable

**Devin Prompt:**
> In `server_space_optimizer/config.py`, change the `secret_key` field default to `os.environ.get("VADSF_SECRET_KEY", "")`. In `app.py`, check that `secret_key` is non-empty at startup; if empty, generate a random key with `secrets.token_hex(32)` and log a warning that a random key was generated (sessions won't persist across restarts). Add a comment explaining this change.

### 1.5 — Add CSRF protection to forms

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, install `starlette-csrf` or implement manual CSRF tokens. In `app.py`, add CSRF middleware that generates a token per session and validates it on POST requests. Update `login.html`, `signup.html`, and `settings.html` templates to include a hidden `<input name="csrf_token">` field. Add a comment explaining the CSRF protection mechanism.

### 1.6 — Add graceful shutdown handlers

**Devin Prompt:**
> In `server_space_optimizer/app.py`, update the `shutdown_event` handler to: (1) signal the scan scheduler to stop accepting new jobs, (2) wait up to 30 seconds for any in-progress scan to complete, (3) close all database connections cleanly. Use `asyncio.Event` or a threading event to coordinate. Add a comment explaining the graceful shutdown flow.

### 1.7 — Configure SQLite connection pooling

**Devin Prompt:**
> In `server_space_optimizer/models/database.py`, update `init_database()` to pass `connect_args={"check_same_thread": False}` and `pool_size=5, max_overflow=10, pool_timeout=30` to `create_engine()`. Note: SQLite uses `StaticPool` for thread safety — use `poolclass=StaticPool` if needed. Add a comment explaining thread-safe database access for concurrent FastAPI requests.

### 1.8 — Enhance health check endpoint

**Devin Prompt:**
> In `server_space_optimizer/api/routes.py`, enhance the `/health` endpoint to return: `{"status": "healthy", "database": "connected|error", "scheduler": "running|stopped", "uptime_seconds": float, "version": "1.0.0"}`. Check database connectivity with a simple `SELECT 1` query. Check scheduler status from the APScheduler instance. Add a comment explaining what each health field indicates.

---

## Phase 2 — Important Items (2–4 Weeks)

High severity + medium effort items that improve maintainability and API quality.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 2.1 | Split routes.py into logical routers | CO-2 | Medium |
| 2.2 | Extract utility modules | CO-3 | Medium |
| 2.3 | Add API integration tests | TE-2 | Large |
| 2.4 | Create test fixtures and factories | TE-3 | Medium |
| 2.5 | Add API versioning (`/api/v1/`) | AD-1 | Medium |
| 2.6 | Add OpenAPI docs and response models | AD-2 | Small |
| 2.7 | Add Prometheus metrics | OB-2 | Medium |

### 2.1 — Split routes.py into logical routers

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, refactor `server_space_optimizer/api/routes.py` (1800+ lines) into separate router modules: `api/dashboard.py` (dashboard, chart, cost endpoints), `api/purge.py` (purge report, history endpoints), `api/config.py` (sub-app configs, settings, excluded mounts), `api/capacity.py` (capacity plans, alerts), `api/scanning.py` (scan trigger, status, agent report), `api/extensions.py` (file extensions). Each file should define its own `APIRouter`. Update `app.py` to include all routers. Ensure all existing endpoints remain at the same paths. Add comments to each router file describing its scope.

### 2.2 — Extract utility modules

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `server_space_optimizer/utils/` package with: (1) `formatting.py` — move `format_size()`, `format_number()`, `humanize_bytes()` functions, (2) `date_helpers.py` — move date comparison, threshold calculation, age-in-days logic, (3) `validators.py` — server name validation, path validation, email validation. Update all imports across routes.py, scanner files, and predictor. Add comments explaining each utility module's purpose.

### 2.3 — Add API integration tests

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `tests/test_api_integration.py` using FastAPI's `TestClient`. Write tests for: (1) GET `/api/dashboard` returns valid `DashboardSummary`, (2) GET `/api/servers/{name}/purge` returns purge candidates, (3) POST `/api/config/sub-apps` creates a config and GET lists it, (4) POST `/api/capacity-plans` creates a plan, (5) POST `/api/agent/report` accepts agent data, (6) GET `/api/chart/growth-purge-forecast` returns chart data. Use an in-memory SQLite database. Add a `conftest.py` with shared fixtures.

### 2.4 — Create test fixtures and factories

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `tests/conftest.py` with pytest fixtures: (1) `db_session` — creates in-memory SQLite with all tables, yields session, rolls back after test, (2) `test_client` — FastAPI TestClient with injected test DB, (3) `sample_server_config` — returns a valid `ServerConfig`, (4) `sample_files` — inserts 50 `FileMetadata` records with varied ages/sizes, (5) `sample_snapshots` — inserts 90 days of `SpaceSnapshot` records. Also create `tests/factories.py` with factory functions for each model.

### 2.5 — Add API versioning

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add API versioning. Create a new router prefix `/api/v1/` that includes all existing API routes. Keep `/api/` as a redirect or alias to `/api/v1/` for backward compatibility. Update `app.js` frontend to use `/api/v1/` paths. Add a version header `X-API-Version: 1` to all responses. Add a comment explaining the versioning strategy.

### 2.6 — Add OpenAPI documentation

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, enhance every API endpoint with: (1) `response_model` parameter for type-safe responses, (2) `summary` and `description` strings, (3) `tags` grouping (Dashboard, Purge, Config, Capacity, Scanning, Extensions), (4) Example request/response bodies using `Body(example=...)`. Update `app.py` to set `title="VADSF API"`, `description`, `version="1.0.0"` on the FastAPI instance. The docs should be accessible at `/docs`.

### 2.7 — Add Prometheus metrics

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `prometheus-fastapi-instrumentator` to `requirements.txt`. In `app.py`, initialize the instrumentator to auto-track request count, latency, and in-progress requests. Add custom metrics: `scan_duration_seconds` (histogram), `files_scanned_total` (counter), `purge_candidates_total` (gauge), `capacity_alerts_sent_total` (counter). Expose metrics at `/metrics`. Add a comment explaining each custom metric.

---

## Phase 3 — Polish Items (4–8 Weeks)

Medium/low severity items that round out the engineering quality.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 3.1 | Add edge case and boundary tests | TE-4 | Medium |
| 3.2 | Add rate limiting to login | SE-4 | Small |
| 3.3 | Add pagination to list endpoints | AD-3 | Medium |
| 3.4 | Add structured JSON logging | OB-3 | Small |
| 3.5 | Add retry logic for SMTP alerts | RE-3 | Small |
| 3.6 | Add performance/load tests | TE-5 | Medium |
| 3.7 | Add audit logging for config changes | OB-5 | Small |
| 3.8 | Add security headers middleware | SE-6 | Small |

### 3.1 — Add edge case and boundary tests

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `tests/test_edge_cases.py` with tests for: (1) dashboard with zero servers configured, (2) purge report with no files in database, (3) growth prediction with only 1 data point, (4) file metadata with 0-byte files, (5) files with timestamps in the future, (6) Unicode characters in file paths and server names, (7) very large file sizes (>1TB), (8) capacity plan with 0 monthly allocation. Each test should verify the API returns a valid response without errors.

### 3.2 — Add rate limiting to login

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `slowapi` to `requirements.txt`. Configure rate limiting on `/login` POST to 5 attempts per minute per IP. On exceeding the limit, return 429 with `{"error": "Too many login attempts. Try again in 60 seconds."}`. Also track failed login attempts per username in `app_settings` and lock the account after 10 consecutive failures. Add a comment explaining the rate limiting strategy.

### 3.3 — Add pagination to list endpoints

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `limit` (default 50, max 500) and `offset` (default 0) query parameters to: `/api/config/sub-apps`, `/api/capacity-plans`, `/api/alert-logs`, `/api/extensions`. Return response as `{"items": [...], "total": int, "limit": int, "offset": int, "has_more": bool}`. Update the frontend JavaScript to support "Load More" buttons using pagination. Add a comment explaining the pagination model.

### 3.4 — Add structured JSON logging

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `python-json-logger` to `requirements.txt`. Create `server_space_optimizer/utils/logging_config.py` that configures structured JSON logging with fields: `timestamp`, `level`, `logger`, `message`, `request_id`, `server_name`, `sub_app_name`. Add request ID middleware that generates a UUID per request and injects it into the log context. Update all `logger` calls across the codebase. Add a comment explaining the structured logging format.

### 3.5 — Add retry logic for SMTP alerts

**Devin Prompt:**
> In `server_space_optimizer/api/routes.py`, update `_send_threshold_alert()` to retry up to 3 times with exponential backoff (1s, 2s, 4s) on `SMTPException` or `ConnectionError`. Log each retry attempt. If all retries fail, log the failure and update the `AlertLog` with `sent_success=0`. Add a comment explaining the retry strategy and backoff timing.

### 3.6 — Add performance/load tests

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create `tests/test_performance.py` using `pytest-benchmark`. Write benchmarks for: (1) `/api/dashboard` with 100 servers × 10 sub-apps, (2) `/api/servers/{name}/purge` with 100,000 file records, (3) `/api/chart/growth-purge-forecast` with 5 years of daily snapshots, (4) incremental scanner with 10,000 files. Set performance thresholds: dashboard <500ms, purge <1s, chart <2s, scan <10s. Add a comment explaining the performance targets.

### 3.7 — Add audit logging for config changes

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, create an `AuditLog` model in `database.py` with fields: `action` (create/update/delete), `entity_type` (sub_app_config/capacity_plan/setting), `entity_id`, `old_value` (JSON), `new_value` (JSON), `user_id`, `timestamp`. Add audit logging to all POST/PUT/DELETE config endpoints. Create a `/api/audit-logs` GET endpoint with date range filtering. Add a comment explaining audit trail coverage.

### 3.8 — Add security headers middleware

**Devin Prompt:**
> In `server_space_optimizer/app.py`, add middleware that sets security headers on all responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy: default-src 'self'; script-src 'self' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; font-src fonts.gstatic.com cdn.jsdelivr.net`. Add a comment explaining each header's purpose.

---

## Timeline Summary

```
Week 1-2:  Phase 1 — 8 quick wins (CLI, error handling, security, shutdown)
Week 3-6:  Phase 2 — 7 important items (routes refactor, tests, API versioning, metrics)
Week 7-12: Phase 3 — 8 polish items (edge cases, rate limiting, pagination, logging)
```

## Priority Matrix

```
              Low Effort          Medium Effort        Large Effort
            ┌─────────────────┬──────────────────┬──────────────────┐
  Critical  │                 │                  │ TE-1 (tests)     │
            ├─────────────────┼──────────────────┼──────────────────┤
  High      │ CO-1, SE-1,     │ CO-2, CO-3,      │ TE-2 (integ.    │
            │ SE-2, SE-3,     │ AD-1, OB-2       │  tests)          │
            │ RE-1, RE-2,     │                  │                  │
            │ OB-1, AD-2,     │                  │                  │
            │ EH-1, EH-2      │                  │                  │
            ├─────────────────┼──────────────────┼──────────────────┤
  Medium    │ EH-3, EH-4,     │ CO-4, CO-5,      │                  │
            │ SE-4, OB-3,     │ TE-4, TE-5,      │                  │
            │ RE-3             │ AD-3, SE-5, OB-4 │                  │
            ├─────────────────┼──────────────────┼──────────────────┤
  Low       │ CO-6, EH-5,     │ RE-4             │                  │
            │ TE-6, SE-6,     │                  │                  │
            │ AD-5, OB-5, RE-5│                  │                  │
            └─────────────────┴──────────────────┴──────────────────┘
```
