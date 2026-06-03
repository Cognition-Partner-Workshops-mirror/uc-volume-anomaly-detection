# KNOWLEDGE_BASE.md — Volume Anomaly Detection & Storage Forecaster (VADSF)

> Full architecture overview, data models, API surface map, business logic inventory, integration points, and build/deployment summary.

---

## 1. Architecture Overview

### 1.1 System Components

VADSF follows a **hub-and-spoke** architecture with Linux agents reporting to a central FastAPI dashboard accessible from Windows machines.

```
┌──────────────────────┐     REST/JSON      ┌──────────────────────────────┐
│  Linux NAS Server(s)  │ ──── POST ────►   │   Central Dashboard (FastAPI) │
│  (space_agent.sh or   │                    │   + SQLite DB + Jinja2 UI     │
│   linux_agent.py)     │                    │   Port 8080                   │
└──────────────────────┘                    └──────────────────────────────┘
                                                      ▲
                                               Browser (Windows)
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Shell Agent** | Bash (`space_agent.sh`) | Runs on Linux servers using POSIX tools (`du`, `find`, `stat`, `curl`). No Python dependency. |
| **Python Agent** | Python (`linux_agent.py`) | Optional alternative for servers with Python installed. |
| **Web Dashboard** | FastAPI + Jinja2 + Bootstrap 5 | Serves REST API and server-rendered HTML pages. |
| **Database** | SQLite via SQLAlchemy ORM | Stores scan results, file metadata, snapshots, configs, user accounts. |
| **Scheduler** | APScheduler (BackgroundScheduler) | Triggers incremental scans at configurable intervals (default 60 min). |
| **Charts** | Chart.js 4.x | Client-side line, pie, bar, and trend charts. |
| **Authentication** | Session cookies + SHA-256 password hashing | Username/password login with signup. |

### 1.2 Communication Patterns

- **Agent → Dashboard**: HTTP POST to `/api/agent/report` with JSON payload containing file metadata.
- **Browser → Dashboard**: Standard HTTP GET/POST/PUT/DELETE for all CRUD operations and page rendering.
- **Dashboard → SMTP**: Outbound email for capacity threshold alerts.
- **Dashboard → Filesystem**: Direct filesystem access for scanning local/mounted NAS paths during scheduled scans.

### 1.3 Infrastructure

- **Single-process deployment**: `uvicorn` ASGI server hosts everything (API + static files + templates).
- **No external dependencies**: SQLite is embedded; no Redis, no message queue, no separate worker processes.
- **Configuration**: Dual-source — YAML file (`server_config/servers.yaml`) and database (`sub_app_configs` table).

---

## 2. Data Models

### 2.1 Domain: Scanning & Storage

| Entity | Table | Key Fields | Purpose |
|--------|-------|------------|---------|
| `ScanResult` | `scan_results` | `server_name`, `sub_app_name`, `scan_timestamp`, `total_size_bytes`, `total_file_count`, `scan_type`, `scan_duration_seconds` | Records each scan execution with aggregate results. |
| `FileMetadata` | `file_metadata` | `server_name`, `sub_app_name`, `file_path`, `file_size_bytes`, `file_extension`, `last_modified`, `last_accessed`, `created_at`, `is_deleted` | Per-file metadata enabling incremental scanning. Only new/changed files are re-evaluated. |
| `SpaceSnapshot` | `space_snapshots` | `server_name`, `sub_app_name`, `snapshot_timestamp`, `total_size_bytes`, `total_file_count` | Hourly/daily aggregate snapshots used for growth prediction and trend analysis. |

### 2.2 Domain: Configuration

| Entity | Table | Key Fields | Purpose |
|--------|-------|------------|---------|
| `SubAppConfigDB` | `sub_app_configs` | `server_name`, `sub_app_name`, `path`, `patterns`, `is_dedicated_mount` | Dynamic sub-app configs added via Settings UI. Merged with YAML config at runtime. |
| `AppSettings` | `app_settings` | `setting_key`, `setting_value` | Key-value store for cost rate, excluded mounts, SMTP settings. |
| `SubAppCapacityPlan` | `sub_app_capacity_plans` | `server_name`, `sub_app_name`, `daily_consumption_gb`, `growth_rate_pct`, `purge_schedule_json`, `monthly_allocation_gb`, `alert_threshold_pct`, `contact_email` | Per-team capacity planning with purge schedules and allocation alerts. |

### 2.3 Domain: Users & Alerting

| Entity | Table | Key Fields | Purpose |
|--------|-------|------------|---------|
| `User` | `users` | `username`, `email`, `password_hash`, `display_name`, `is_active` | User accounts for login. SHA-256 hashed passwords. Default: `welcome123`. |
| `AlertLog` | `alert_logs` | `server_name`, `sub_app_name`, `alert_type`, `current_usage_gb`, `allocation_gb`, `usage_pct`, `sent_to_email`, `sent_success` | Tracks threshold alert emails to prevent duplicate notifications (24h cooldown). |

### 2.4 Pydantic Schemas (API Layer)

| Schema | Used By | Fields |
|--------|---------|--------|
| `SubAppSpaceInfo` | Dashboard, server space | `sub_app_name`, `total_size_bytes`, `total_size_human`, `file_count`, `dir_count` |
| `ServerSpaceInfo` | Dashboard | `server_name`, `server_host`, `nas_mount_path`, `total_size_bytes`, `sub_apps[]` |
| `PurgeCandidate` | Purge report | `file_path`, `file_size_bytes`, `last_modified`, `last_accessed`, `days_since_modified` |
| `PurgeReport` | Purge report | `threshold_days`, `total_candidates`, `total_reclaimable_bytes`, `candidates[]` |
| `GrowthPrediction` | Growth forecast | `period`, `predicted_growth_bytes`, `growth_rate_percent`, `confidence`, `data_points_used` |
| `ServerGrowthReport` | Growth forecast | `server_name`, `sub_app_name`, `current_size_bytes`, `predictions[]`, `historical_data[]` |
| `ScanStatusResponse` | Scan status | `is_scanning`, `last_scan_time`, `next_scan_time`, `scan_interval_minutes` |
| `DashboardSummary` | Dashboard | `total_servers`, `total_sub_apps`, `total_size_bytes`, `servers[]` |

### 2.5 Configuration Models (Pydantic)

| Model | Source | Fields |
|-------|--------|--------|
| `SubAppConfig` | YAML + API | `name`, `path`, `patterns[]`, `is_dedicated_mount` |
| `ServerConfig` | YAML + API | `server_name`, `server_host`, `nas_mount_path`, `sub_apps[]` |
| `AppConfig` | YAML + env | `scan_interval_minutes`, `purge_thresholds_days`, `database_path`, `servers[]`, `excluded_mounts[]`, `cost_per_gb_month`, `secret_key` |

---

## 3. API Surface Map

All endpoints are prefixed with `/api/`.

### 3.1 Dashboard & Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/dashboard` | Dashboard summary: all servers, sub-apps, aggregate stats. Merges YAML + DB configs. |
| `GET` | `/api/chart/growth-purge-forecast` | Combined time-series: growth (past 1yr), purge, forecast (future 5yrs). |
| `GET` | `/api/cost-estimation` | Current/projected storage costs at configured $/GB rate. |

### 3.2 Server & Space

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{server_name}/space` | Space breakdown for a specific server. |
| `GET` | `/api/servers/{server_name}/history` | Historical space trend data for a server. |

### 3.3 Purge Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{server_name}/purge` | Purge-eligible files for a server, filtered by threshold. |
| `GET` | `/api/purge-history-summary` | Purge eligibility at 1w/1m/1y/5y horizons + monthly trend. |

### 3.4 Growth & Forecasting

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{server_name}/predictions` | Growth predictions (weekly/monthly/yearly/5yr) using linear regression. |
| `GET` | `/api/servers/{server_name}/purge-rate` | Daily/monthly purge rate and net space forecast. |

### 3.5 Scanning

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scan/status` | Current scan status, next scan time, interval. |
| `POST` | `/api/scan/trigger` | Trigger an immediate scan (runs in background). |
| `POST` | `/api/agent/report` | Receive scan data from remote Linux agents. |

### 3.6 File Extensions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/extensions` | Unique file extensions, format descriptions, optimization recommendations. |

### 3.7 Configuration Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/config/sub-apps` | List all sub-app configurations from DB. |
| `POST` | `/api/config/sub-apps` | Create a new sub-app configuration. |
| `PUT` | `/api/config/sub-apps/{id}` | Update an existing sub-app configuration. |
| `DELETE` | `/api/config/sub-apps/{id}` | Delete a sub-app configuration. |
| `GET` | `/api/config/servers` | List all known server names (YAML + DB merged). |
| `GET` | `/api/config/sub-app-names` | List sub-app names for a given server. |
| `GET` | `/api/config/excluded-mounts` | Get system-excluded mount paths. |
| `PUT` | `/api/config/excluded-mounts` | Update excluded mount paths. |

### 3.8 Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get all application settings (cost rate, SMTP, etc). |
| `PUT` | `/api/settings/{key}` | Update a single setting. |

### 3.9 Capacity Planning & Alerting

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/capacity-plans` | List all capacity plans. |
| `POST` | `/api/capacity-plans` | Create a new capacity plan. |
| `PUT` | `/api/capacity-plans/{id}` | Update a capacity plan. |
| `DELETE` | `/api/capacity-plans/{id}` | Delete a capacity plan. |
| `GET` | `/api/capacity-plans/status` | Current usage vs allocation for all plans. |
| `POST` | `/api/capacity-plans/check-alerts` | Check thresholds and send email alerts. |
| `GET` | `/api/alert-logs` | List alert history. |

### 3.10 Authentication (Page Routes)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/login` | Login page. |
| `POST` | `/login` | Authenticate user. |
| `GET` | `/signup` | Signup page. |
| `POST` | `/signup` | Create new user account. |
| `GET` | `/logout` | Log out and redirect to login. |

### 3.11 UI Pages

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard (requires auth). |
| `GET` | `/purge` | Purge eligibility report. |
| `GET` | `/predictions` | Growth & forecast page. |
| `GET` | `/extensions` | File extensions analytics. |
| `GET` | `/settings` | Settings (sub-app configs, capacity plans, cost rate). |

---

## 4. Key Business Logic Inventory

### 4.1 Incremental Scanning (`scanner/incremental_scanner.py`)

- **Full scan**: Walks entire directory tree, records every file's metadata.
- **Incremental scan**: Only processes files modified since `last_scan_time` using `os.stat().st_mtime`.
- **Deleted file detection**: Marks files as `is_deleted=1` if they no longer exist on disk.
- **Mount exclusion**: Skips system paths listed in `excluded_mounts` configuration.

### 4.2 Growth Prediction (`predictor/growth_predictor.py`)

- Uses **linear regression** on `SpaceSnapshot` history to estimate growth rate.
- Calculates predictions for 4 periods: 1 week, 1 month, 1 year, 5 years.
- Computes **confidence scores** based on R-squared of the regression fit.
- Falls back to zero growth if insufficient data points exist.

### 4.3 Purge Analysis (`scanner/purge_analyzer.py`)

- Queries `FileMetadata` for files older than configurable thresholds (7/30/60/90/180/365 days).
- Returns top-N candidates sorted by file size (default top 50).
- Supports CSV export for full report download.
- Calculates reclaimable space per threshold.

### 4.4 Combined Growth/Purge/Forecast Chart (`api/routes.py`)

- **Historical growth**: Aggregates `SpaceSnapshot` records by month for the past 12 months.
- **Purge eligible**: Estimates purgeable bytes at each historical month (files > 90 days old).
- **Forecast**: Projects 60 months forward using linear regression slope from recent snapshots.
- Returns all three series with unified labels for the dashboard Chart.js visualization.

### 4.5 Capacity Planning & Alerting

- Each sub-app has a **capacity plan**: daily consumption, growth rate, purge schedule, monthly allocation.
- **Purge schedule** is JSON: e.g., `[{"pct": 50, "after_days": 7}, {"pct": 50, "after_days": 30}]`.
- **80% threshold alert**: When current usage exceeds `alert_threshold_pct` of `monthly_allocation_gb`, an email is sent.
- **Deduplication**: Alerts are suppressed for 24 hours after last alert for the same sub-app.
- **SMTP integration**: Sends via `smtplib.SMTP` with configurable host/port/credentials.

### 4.6 Dual Configuration Merging

- Servers can be defined in **YAML** (`server_config/servers.yaml`) and/or added via **Settings UI** (stored in `SubAppConfigDB`).
- The dashboard endpoint merges both sources: first processes YAML servers, then appends any DB-only servers/sub-apps.
- All dropdowns across pages use `/api/config/servers` and `/api/config/sub-app-names` to ensure consistency.

### 4.7 Cost Estimation

- Configurable cost rate (default $0.023/GB/month).
- Calculates current monthly cost and projects for 1 week, 1 month, 1 year, 5 years.
- Factors in predicted growth from linear regression.

---

## 5. Integration Points

| Integration | Protocol | Configuration | Purpose |
|-------------|----------|---------------|---------|
| **SMTP Email** | SMTP/SMTPS | `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` in `app_settings` | Threshold alert notifications. |
| **SQLite Database** | Filesystem | `database_path` in `AppConfig` (default: `space_optimizer.db`) | All persistent storage. |
| **YAML Config** | Filesystem | `server_config/servers.yaml` | Static server/sub-app definitions. |
| **Linux Agent** | HTTP REST | Agent POSTs to `/api/agent/report` | Remote file metadata ingestion. |
| **cron/systemd** | OS service | `space_agent.sh --once` for cron, or daemon mode | Scheduling agent scans on remote servers. |

---

## 6. Build & Deployment Summary

### 6.1 Dependencies

All dependencies are open-source:
- **FastAPI** + **Uvicorn**: ASGI web framework and server.
- **SQLAlchemy**: ORM for SQLite database.
- **Pydantic**: Data validation and serialization.
- **APScheduler**: In-process background task scheduling.
- **PyYAML**: YAML configuration parsing.
- **Jinja2**: Server-side HTML template rendering.
- **Chart.js** (CDN): Client-side charting library.
- **Bootstrap 5** (CDN): CSS framework.

### 6.2 Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Generate demo data (optional)
python -m server_space_optimizer.scripts.generate_demo_data

# Start the server
python -m uvicorn server_space_optimizer.app:app --host 0.0.0.0 --port 8080
```

### 6.3 Shell Agent Deployment

```bash
# Copy to target Linux server
scp space_agent.sh agent.conf user@server:/opt/space-agent/

# One-time scan (for cron)
./space_agent.sh --once

# Continuous daemon mode
./space_agent.sh &
```

### 6.4 Default Credentials

- **Username**: `admin`
- **Password**: `welcome123`
- Any new user signing up defaults to `welcome123` if no password is provided.
