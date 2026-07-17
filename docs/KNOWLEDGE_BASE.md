# KNOWLEDGE_BASE.md — NAS Capacity Pulse

> Full architecture overview, data models, API surface map, business logic inventory, integration points, and build/deployment summary.
>
> *Punchline: Volume Anomaly Detection & Storage Forecaster*

---

## 1. Architecture Overview

### 1.1 System Components

NAS Capacity Pulse follows a **hub-and-spoke** architecture with lightweight Linux agents reporting to a central FastAPI dashboard accessible from any workstation (Windows, macOS, Linux).

```
┌──────────────────────┐     REST/JSON      ┌──────────────────────────────┐
│  Linux NAS Server(s)  │ ──── POST ────►   │   Central Dashboard (FastAPI) │
│  (space_agent.sh or   │                    │   + SQLite DB + Jinja2 UI     │
│   linux_agent.py)     │                    │   Port 8080                   │
└──────────────────────┘                    └──────────────────────────────┘
                                                      ▲
                                               Browser (Windows/macOS)
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Shell Agent** | Bash (`space_agent.sh`) | Runs on Linux servers using POSIX tools (`du`, `find`, `stat`, `curl`). No Python/Java dependency. |
| **Python Agent** | Python (`linux_agent.py`) | Optional alternative for servers with Python installed. Uses `os.walk()` and `urllib.request`. |
| **Web Dashboard** | FastAPI + Jinja2 + Bootstrap 5 | Serves REST API and server-rendered HTML pages on port 8080. |
| **Database** | SQLite via SQLAlchemy 2.0 ORM | 8 tables storing scan results, file metadata, snapshots, configs, user accounts, capacity plans, alert logs. |
| **Scheduler** | APScheduler (BackgroundScheduler) | Triggers incremental scans at configurable intervals (default 60 min). |
| **Charts** | Chart.js 4.x | Client-side rendering of line, pie, bar, and trend charts with server dropdown and avg volume line. |
| **Authentication** | Session cookies + SHA-256 password hashing | Username/password login with signup. Default password sourced from `DEFAULT_PASSWORD` env var. |
| **Capacity Planner** | Per-sub-app capacity models | Daily consumption, growth rate, purge schedule, monthly allocation, 80% threshold email alerts. |

### 1.2 Communication Patterns

- **Agent → Dashboard**: HTTP POST to `/api/agent/report` with JSON payload containing server name, sub-apps, and per-file metadata.
- **Browser → Dashboard**: Standard HTTP GET/POST/PUT/DELETE for all CRUD operations and page rendering.
- **Dashboard → SMTP**: Outbound email for capacity threshold alerts (when usage ≥ 80% of monthly allocation).
- **Dashboard → Filesystem**: Direct filesystem access for scanning local/mounted NAS paths during scheduled scans.

### 1.3 Infrastructure

- **Single-process deployment**: `uvicorn` ASGI server hosts everything (API + static files + templates).
- **No external dependencies**: SQLite is embedded; no Redis, no message queue, no separate worker processes.
- **Configuration**: Dual-source — YAML file (`server_config/servers.yaml`) and database (`sub_app_configs` table). Settings UI allows runtime configuration.
- **Secrets**: `SECRET_KEY` and `DEFAULT_PASSWORD` read from environment variables with dev-mode fallbacks. See `.env.example`.

---

## 2. Data Models

### 2.1 Domain: Scanning & Storage

| Model | Table | Key Fields | Purpose |
|-------|-------|-----------|---------|
| `ScanResult` | `scan_results` | `server_name`, `sub_app_name`, `scan_timestamp`, `total_size_bytes`, `total_file_count`, `total_dir_count`, `scan_type` (full/incremental), `scan_duration_seconds` | Audit trail of every scan execution |
| `FileMetadata` | `file_metadata` | `server_name`, `sub_app_name`, `file_path`, `file_size_bytes`, `file_extension`, `last_modified`, `last_accessed`, `created_at`, `last_scanned`, `is_deleted` | Per-file records for incremental scanning and purge analysis |
| `SpaceSnapshot` | `space_snapshots` | `server_name`, `sub_app_name`, `snapshot_timestamp`, `total_size_bytes`, `total_file_count` | Hourly/daily aggregates for linear regression growth prediction |

### 2.2 Domain: Configuration & Settings

| Model | Table | Key Fields | Purpose |
|-------|-------|-----------|---------|
| `SubAppConfigDB` | `sub_app_configs` | `server_name`, `sub_app_name`, `path`, `patterns`, `is_dedicated_mount` | Dynamic server/sub-app mappings from Settings UI (supplements YAML config) |
| `AppSettings` | `app_settings` | `setting_key` (unique), `setting_value` | Key-value store for cost rate ($/GB/month), excluded mounts list |
| `SubAppCapacityPlan` | `sub_app_capacity_plans` | `server_name`, `sub_app_name`, `daily_consumption_gb`, `growth_rate_pct`, `purge_schedule_json`, `monthly_allocation_gb`, `alert_threshold_pct`, `contact_email` | Per-team capacity planning parameters |

### 2.3 Domain: Users & Alerts

| Model | Table | Key Fields | Purpose |
|-------|-------|-----------|---------|
| `User` | `users` | `username` (unique), `email` (unique), `password_hash` (SHA-256), `display_name`, `is_active`, `last_login` | Login credentials and session metadata |
| `AlertLog` | `alert_logs` | `server_name`, `sub_app_name`, `alert_type`, `current_usage_gb`, `allocation_gb`, `usage_pct`, `sent_to_email`, `sent_success` | Record of capacity threshold alert emails (24h deduplication) |

---

## 3. API Surface Map

### 3.1 Dashboard & Server Endpoints

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/dashboard` | — | `DashboardSummary` | Aggregate dashboard: all servers, sub-apps, totals. Merges YAML + DB-configured servers. |
| GET | `/api/servers` | — | `[ServerSpaceInfo]` | List all servers with sub-app breakdown |
| GET | `/api/server/{name}` | — | `ServerSpaceInfo` | Single server details |
| GET | `/api/chart-data` | `?server=all` | `{labels, growth, purge, forecast, avg_volume}` | Time-series chart data for combined growth/purge/forecast chart. Server dropdown filtering. |

### 3.2 Scan Management

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| POST | `/api/scan/trigger` | `{force_full: bool}` | `ScanStatusResponse` | Trigger immediate scan (background task) |
| GET | `/api/scan/status` | — | `ScanStatusResponse` | Current scan status, last scan time, next scheduled |

### 3.3 Purge Analysis

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/purge/report` | `?server=&sub_app=&threshold_days=90&limit=50` | `PurgeReport` | Purge eligibility analysis (files ranked by size, largest first) |
| GET | `/api/purge/summary` | `?server=` | `[PurgeReport]` | Multi-threshold summary (7, 30, 60, 90, 180, 365 days) |
| DELETE | `/api/purge/delete/{file_id}` | — | `{success, message}` | User-initiated file deletion with confirmation |
| POST | `/api/purge/delete-bulk` | `{file_ids: [int]}` | `{deleted, failed}` | Bulk purge for selected files |
| GET | `/api/purge/history` | — | `{weekly, monthly, yearly, five_year}` | Actual purge history summaries |

### 3.4 Growth & Forecast

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/predictions/{server}/{sub_app}` | — | `ServerGrowthReport` | Growth forecast (1w/1m/1y/5y) with linear regression |
| GET | `/api/predictions/cost` | `?server=&sub_app=` | `{current_cost, forecasts}` | Cost projection using configured $/GB/month rate |

### 3.5 File Extension Analytics

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/extensions` | `?server=&sub_app=` | `[{extension, count, total_size, avg_size, recommendation}]` | Unique extensions with optimization recommendations |

### 3.6 Configuration CRUD

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/sub-app-configs` | `?server=` | `[SubAppConfigDB]` | List all sub-app configurations |
| POST | `/api/sub-app-configs` | `{server_name, sub_app_name, path, patterns}` | `SubAppConfigDB` | Create new sub-app config |
| PUT | `/api/sub-app-configs/{id}` | `{path, patterns, ...}` | `SubAppConfigDB` | Update sub-app config |
| DELETE | `/api/sub-app-configs/{id}` | — | `{success}` | Delete sub-app config |
| GET | `/api/servers/list` | — | `[string]` | Dropdown: distinct server names |
| GET | `/api/sub-apps/list` | `?server=` | `[string]` | Dropdown: distinct sub-app names per server |

### 3.7 Capacity Planning

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/capacity-plans` | `?server=` | `[SubAppCapacityPlan]` | List capacity plans |
| POST | `/api/capacity-plans` | `{server_name, sub_app_name, daily_consumption_gb, ...}` | `SubAppCapacityPlan` | Create capacity plan |
| PUT | `/api/capacity-plans/{id}` | `{...}` | `SubAppCapacityPlan` | Update capacity plan |
| DELETE | `/api/capacity-plans/{id}` | — | `{success}` | Delete capacity plan |
| GET | `/api/capacity-plans/status` | — | `[{sub_app, usage_gb, allocation_gb, usage_pct}]` | Current allocation usage status |
| POST | `/api/capacity-plans/check-alerts` | — | `{alerts_sent, details}` | Check thresholds and send email alerts |

### 3.8 Settings

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| GET | `/api/settings/cost-rate` | — | `{cost_per_gb_month}` | Current cost rate |
| PUT | `/api/settings/cost-rate` | `{cost_per_gb_month}` | `{success}` | Update cost rate |
| GET | `/api/settings/excluded-mounts` | — | `{mounts: [string]}` | Current excluded mount list |
| PUT | `/api/settings/excluded-mounts` | `{mounts: [string]}` | `{success}` | Update excluded mounts |

### 3.9 Agent Ingestion

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| POST | `/api/agent/report` | `{server_name, server_host, sub_apps: [{name, total_size_bytes, file_count, files: [...]}]}` | `{status, message}` | Receive scan data from remote shell agents |

### 3.10 Web UI Pages (HTML)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/login` | No | Login page with product branding |
| POST | `/login` | No | Login form submission |
| GET | `/signup` | No | Signup page |
| POST | `/signup` | No | Signup form submission |
| GET | `/logout` | No | Clear session cookie |
| GET | `/` | Yes | Main dashboard page |
| GET | `/purge` | Yes | Purge eligibility report page |
| GET | `/predictions` | Yes | Growth & forecast page |
| GET | `/extensions` | Yes | File extension analytics page |
| GET | `/settings` | Yes | Server/sub-app config and capacity planning page |

---

## 4. Business Logic Inventory

### 4.1 Incremental Scanning
- First scan per sub-app: full directory traversal via `scan_directory_recursive()`.
- Subsequent scans: delta-only via `scan_files_since()` — finds files modified after the last scan timestamp.
- File metadata (path, size, extension, mtime, atime, ctime) stored in `file_metadata` table.
- Files not found on local filesystem during scan are NOT auto-deleted — only user-initiated purge.

### 4.2 Path Resolution
Three modes for mapping sub-apps to filesystem paths:
1. **Relative path**: `path: "billing"` → joined with server's `nas_mount_path`.
2. **Dedicated mount**: `path: "/mnt/dedicated"` + `is_dedicated_mount: true` → used as-is.
3. **Glob patterns**: `patterns: ["logs_*"]` → expanded via `glob.glob()` under `nas_mount_path`.

### 4.3 Growth Prediction
- Simple linear regression on `space_snapshots` (last 90 days).
- Uses numpy for `slope`, `intercept`, `R²` computation.
- Extrapolates to 1 week, 1 month, 1 year, 5 years.
- R² score returned as `confidence` (0.0 = no trend, 1.0 = perfect fit).

### 4.4 Purge Analysis
- Queries `file_metadata` for files older than threshold (default 90 days).
- Sorted by `file_size_bytes` descending (largest impact first).
- Respects `is_deleted` flag — deleted files excluded.
- Multi-threshold summaries: 7, 30, 60, 90, 180, 365 days.

### 4.5 Capacity Planning
- Per-sub-app parameters: daily consumption (GB), growth rate (%), purge schedule (JSON), monthly allocation (GB).
- Alert threshold (default 80%): when `current_usage / monthly_allocation ≥ threshold`, email notification triggered.
- 24-hour deduplication prevents repeat alerts.

### 4.6 Cost Estimation
- Configurable rate stored in `app_settings` (default $0.023/GB/month).
- Applied to current usage and forecast periods.
- Displayed on dashboard summary cards and forecast page.

### 4.7 File Extension Analytics
- Aggregates `file_extension` from `file_metadata` table.
- Per-extension: count, total size, average size, format description.
- Optimization recommendations: compress old `.log` files, archive `.dat`, remove `.tmp`/`.bak`.

---

## 5. Integration Points

| Integration | Type | Details |
|-------------|------|---------|
| **Linux Shell Agent** | HTTP POST | `space_agent.sh` POSTs JSON to `/api/agent/report`. Uses `curl`. |
| **Python Agent** | HTTP POST | `linux_agent.py` uses `urllib.request`. |
| **SMTP Email** | Outbound | Capacity threshold alerts via `smtplib`. Configurable host/port/credentials. |
| **Filesystem** | Direct I/O | Scanner reads NAS mounts using `os.walk()`, `os.stat()`, `os.path.getsize()`. |
| **SQLite** | Embedded DB | Single-file database via SQLAlchemy ORM. No external DB server. |

---

## 6. Build & Deployment Summary

### Dependencies
```
fastapi, uvicorn, sqlalchemy, pydantic, pyyaml, numpy, apscheduler,
jinja2, python-multipart, itsdangerous, aiofiles
```

### Startup Sequence
1. `python run.py` → loads `server_config/servers.yaml`
2. Initializes SQLite database (creates tables if needed)
3. Generates demo data if no existing data found
4. Starts APScheduler (60-min interval scan)
5. Runs initial full scan on startup
6. Serves FastAPI on `0.0.0.0:8080`

### Agent Deployment
- Copy `space_agent.sh` + `agent.conf` to each Linux server
- Schedule via cron: `*/60 * * * * /opt/space_agent/space_agent.sh --config agent.conf --once`
- Or run as daemon: `nohup ./space_agent.sh --config agent.conf &`

### Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | `space-optimizer-dev-key` | Session cookie signing |
| `DEFAULT_PASSWORD` | `welcome123` | Default signup password |
| `HOST` | `0.0.0.0` | Web server bind address |
| `PORT` | `8080` | Web server port |
| `CONFIG_PATH` | `server_config/servers.yaml` | Config file path |
