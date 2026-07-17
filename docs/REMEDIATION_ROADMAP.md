# REMEDIATION_ROADMAP.md — NAS Capacity Pulse

> Phased plan with executable Devin prompts: Phase 1 (7 quick wins, 1–2 weeks), Phase 2 (6 important items, 2–4 weeks), Phase 3 (7 polish items, 4–8 weeks).
>
> Updated to reflect current state: secrets moved to env vars, 58 passing tests, comprehensive docs delivered.

---

## Completed Items (This Sprint)

| Item | Gap Ref | Status |
|------|---------|--------|
| Move `DEFAULT_PASSWORD` to env var | SE-prev | ✓ Done — `os.environ.get("DEFAULT_PASSWORD", "welcome123")` |
| Move `SECRET_KEY` to env var | SE-prev | ✓ Done — `os.environ.get("SECRET_KEY", "space-optimizer-dev-key")` |
| Create `.env.example` | SE-prev | ✓ Done — all configurable env vars documented |
| Expand test suite (22 new tests) | TE-prev | ✓ Done — 58 total (auth, security, SQL injection, models, purge edge cases) |
| Comprehensive README.md | Doc | ✓ Done — architecture, problem statement, quick start, Grafana comparison |
| Technical design document | Doc | ✓ Done — `docs/TECHNICAL_DESIGN.md` with flowcharts and data flow diagrams |
| Update KNOWLEDGE_BASE / GAP_ANALYSIS | Doc | ✓ Done — reflects current 8-table schema, all API endpoints, env var config |

---

## Phase 1 — Quick Wins (1–2 Weeks)

High severity + low effort items that immediately improve reliability and security.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 1.1 | Upgrade password hashing to bcrypt | SE-1 | Small |
| 1.2 | Add global exception handler middleware | EH-1 | Small |
| 1.3 | Add CSRF protection to forms | SE-3 | Small |
| 1.4 | Add health check endpoint | OB-1 | Small |
| 1.5 | Add graceful shutdown with scan drain | RE-1 | Small |
| 1.6 | Configure SQLite connection pooling | RE-2 | Small |
| 1.7 | Add retry logic to shell agent | RE-3 | Small |

### 1.1 — Upgrade password hashing to bcrypt

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `bcrypt` to `requirements.txt`. Update `server_space_optimizer/models/database.py`: replace `hash_password()` to use `bcrypt.hashpw()` with `bcrypt.gensalt()`. Add a `verify_password()` function using `bcrypt.checkpw()`. Update `auth_manager.py` to use `verify_password()` instead of comparing SHA-256 hashes. Add a migration path: if bcrypt check fails, try SHA-256 and if it matches, re-hash with bcrypt and update the DB record. Add comments explaining the migration. Update tests in `test_auth_and_security.py`.

### 1.2 — Add global exception handler middleware

**Devin Prompt:**
> In `server_space_optimizer/app.py`, add `@app.exception_handler(Exception)` that returns `{"error": "Internal server error", "detail": str(exc)}` with status 500. Add handlers for `RequestValidationError` (422) and `HTTPException`. Log every exception with `logger.exception()`. Add a comment explaining centralized error handling.

### 1.3 — Add CSRF protection to forms

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, implement CSRF protection. In `app.py`, add middleware that generates a per-session CSRF token and validates it on POST requests. Update `login.html`, `signup.html`, and `settings.html` templates to include a hidden `<input name="csrf_token">` field. Add a comment explaining the CSRF mechanism.

### 1.4 — Add health check endpoint

**Devin Prompt:**
> In `server_space_optimizer/api/routes.py`, add a `GET /api/health` endpoint that returns `{"status": "ok", "database": "connected", "scheduler": "running|stopped", "last_scan": "<timestamp>"}`. Check DB connectivity by running a simple query. Check scheduler status from `_scan_scheduler`. Add a comment explaining this is for monitoring/load-balancer probes.

### 1.5 — Add graceful shutdown with scan drain

**Devin Prompt:**
> In `server_space_optimizer/scheduler/scan_scheduler.py`, update the `stop()` method to: (1) signal no new jobs, (2) wait up to 30 seconds for in-progress scans to complete using a threading Event, (3) then shut down. Update `app.py` lifespan to await this. Add a comment explaining the graceful drain.

### 1.6 — Configure SQLite connection pooling

**Devin Prompt:**
> In `server_space_optimizer/models/database.py`, update `init_database()` to configure `StaticPool` for SQLite (since it's single-file). Set `connect_args={"check_same_thread": False}` and `pool_pre_ping=True`. Add a comment explaining why these settings are needed for SQLite + multi-threaded FastAPI.

### 1.7 — Add retry logic to shell agent

**Devin Prompt:**
> In `server_space_optimizer/agent/space_agent.sh`, update the `send_report()` function to retry the `curl` POST up to 3 times with exponential backoff (2s, 4s, 8s) on network failure. Use curl's `--retry` flag or a bash retry loop. Add a comment explaining the retry strategy.

---

## Phase 2 — Important (2–4 Weeks)

High severity items requiring moderate effort.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 2.1 | Replace session tokens with JWT | SE-2 | Medium |
| 2.2 | Split routes.py into sub-routers | CO-1 | Medium |
| 2.3 | Extract utility modules | CO-2 | Medium |
| 2.4 | Add API integration tests | TE-1 | Medium |
| 2.5 | Add rate limiting to auth endpoints | SE-4 | Small |
| 2.6 | Add structured JSON logging | OB-2 | Medium |

### 2.1 — Replace session tokens with JWT

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `python-jose[cryptography]` to `requirements.txt`. Create `server_space_optimizer/auth/jwt_handler.py` with `create_access_token(data, expires_delta)` and `verify_token(token)` functions using HS256 signing with `SECRET_KEY`. Update `app.py` to issue JWT on login and validate on each request. Set token expiry to 24 hours. Add a refresh token mechanism. Add comments explaining the JWT flow.

### 2.2 — Split routes.py into sub-routers

**Devin Prompt:**
> In `server_space_optimizer/api/`, split the monolithic `routes.py` into: `dashboard_routes.py` (dashboard/chart endpoints), `purge_routes.py` (purge analysis/delete), `config_routes.py` (sub-app configs, settings, servers), `capacity_routes.py` (capacity plans, alerts), `agent_routes.py` (agent report ingestion). Each file creates its own `APIRouter`. Update `__init__.py` to combine them. Keep backward-compatible URL paths.

### 2.3 — Extract utility modules

**Devin Prompt:**
> Create `server_space_optimizer/utils/` package with: `formatting.py` (move `format_size()` from space_calculator), `validators.py` (server name validation, email validation, path sanitization), `date_helpers.py` (UTC timestamp helpers, age calculations). Update all imports across the codebase. Add a comment in each utility module explaining its purpose.

### 2.4 — Add API integration tests

**Devin Prompt:**
> In `tests/test_api_integration.py`, add tests using `fastapi.testclient.TestClient`. Test: `GET /api/dashboard` returns valid summary, `POST /api/agent/report` stores data, `GET /api/purge/report` returns candidates, `GET /api/extensions` returns extension list, `POST /api/scan/trigger` returns accepted status. Use an in-memory SQLite database. Add a comment explaining the test setup.

### 2.5 — Add rate limiting to auth endpoints

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `slowapi` to `requirements.txt`. In `app.py`, configure `Limiter` with `"5/minute"` on `POST /login` and `POST /signup` endpoints. Return `429 Too Many Requests` with a descriptive message. Add a comment explaining the rate limit configuration.

### 2.6 — Add structured JSON logging

**Devin Prompt:**
> In `server_space_optimizer/app.py`, replace `logging.basicConfig()` with `structlog` or `python-json-logger`. Configure JSON output with fields: timestamp, level, logger, message, request_id, duration_ms. Add a middleware that assigns a unique `request_id` to each request. Add a comment explaining the structured logging setup.

---

## Phase 3 — Polish (4–8 Weeks)

Lower severity items for production hardening.

| # | Item | Gap Ref | Effort |
|---|------|---------|--------|
| 3.1 | Add API versioning (`/api/v1/`) | AD-1 | Medium |
| 3.2 | Add pagination to list endpoints | AD-2 | Small |
| 3.3 | Standardize error response envelope | EH-3, EH-4 | Small |
| 3.4 | Add end-to-end agent flow test | TE-2 | Large |
| 3.5 | Add pytest-cov with coverage thresholds | TE-3 | Small |
| 3.6 | Add request ID tracing | OB-3 | Small |
| 3.7 | Add SQLite backup automation | RE-4 | Small |

### 3.1 — Add API versioning

**Devin Prompt:**
> In `server_space_optimizer/api/`, create a versioned router structure: move all current routes under `/api/v1/`. Add a deprecated `/api/` alias that redirects to `/api/v1/`. Update frontend `app.js` AJAX calls to use `/api/v1/`. Add a comment explaining the versioning strategy.

### 3.2 — Add pagination to list endpoints

**Devin Prompt:**
> In `server_space_optimizer/api/routes.py`, add `page` (default 1) and `limit` (default 50) query parameters to `/api/extensions`, `/api/sub-app-configs`, `/api/purge/report`. Return `{data: [...], meta: {page, limit, total, total_pages}}`. Update frontend to handle pagination. Add a comment explaining the pagination envelope.

### 3.3 — Standardize error response envelope

**Devin Prompt:**
> Create a `server_space_optimizer/models/error_schemas.py` with `ErrorResponse(error: str, detail: str, status_code: int)`. Update all endpoints to return this schema for error cases. Ensure 4xx/5xx status codes match the error type. Add a comment explaining the standard error format.

### 3.4 — Add end-to-end agent flow test

**Devin Prompt:**
> In `tests/test_e2e_agent_flow.py`, create a test that: (1) starts the FastAPI app via TestClient, (2) sends a simulated agent POST to `/api/agent/report` with realistic payload, (3) queries `/api/dashboard` and verifies the agent's data appears, (4) queries `/api/chart-data` and verifies historical data is plotted, (5) queries `/api/extensions` and verifies file extension analytics. Use an in-memory SQLite DB. Add a comment explaining this validates the full Linux-to-Windows data pipeline.

### 3.5 — Add pytest-cov with coverage thresholds

**Devin Prompt:**
> In the `uc-volume-anomaly-detection` repo, add `pytest-cov` to `requirements.txt`. Add a `pyproject.toml` or `pytest.ini` section with `--cov=server_space_optimizer --cov-report=term-missing --cov-fail-under=60`. Run tests and document the current coverage baseline. Add a comment in the config explaining the coverage threshold.

### 3.6 — Add request ID tracing

**Devin Prompt:**
> In `server_space_optimizer/app.py`, add a middleware that generates a UUID `X-Request-ID` header for each request. Include this ID in all log messages for the request lifecycle. Return the header in responses. Add a comment explaining how to trace a request through logs.

### 3.7 — Add SQLite backup automation

**Devin Prompt:**
> Create `server_space_optimizer/scripts/backup_db.py` that: (1) uses `sqlite3.backup()` to create an online backup of `space_optimizer.db`, (2) saves to `backups/space_optimizer_YYYYMMDD_HHMMSS.db`, (3) retains only the last 7 backups, (4) can be called from cron. Add a cron example in the README. Add a comment explaining the backup strategy.
