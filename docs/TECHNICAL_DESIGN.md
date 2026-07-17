# NAS Capacity Pulse — Technical Design Document

> Version 1.0 · Last updated: June 2026

---

## 1. System Overview

NAS Capacity Pulse is a distributed storage monitoring system composed of two tiers:

| Tier | Runs On | Technology | Role |
|------|---------|------------|------|
| **Agent Tier** | Each Linux/Unix server | POSIX shell (`bash`, `du`, `find`, `stat`, `curl`) | Scan NAS mounts and POST JSON to the dashboard |
| **Dashboard Tier** | Central Windows/Linux/macOS host | Python 3.11+, FastAPI, SQLite, Chart.js | Receive data, aggregate, forecast, serve web UI |

Communication is **one-way push**: agents POST to the dashboard over HTTP/HTTPS. The dashboard never SSHes into agents.

---

## 2. Component Architecture

```
 ┌──────────────────────────────────────────────────────────────┐
 │  AGENT TIER  (per Linux server)                              │
 │                                                              │
 │  space_agent.sh              OR     linux_agent.py           │
 │  ┌────────────────────────┐        ┌──────────────────────┐  │
 │  │ 1. Read agent.conf     │        │ Python alternative   │  │
 │  │ 2. Iterate SUB_APPS    │        │ using os.walk()      │  │
 │  │ 3. du / find / stat    │        │ and urllib.request    │  │
 │  │ 4. Build JSON payload  │        └──────────────────────┘  │
 │  │ 5. curl POST to /api/  │                                  │
 │  │    agent/report         │                                  │
 │  └────────────────────────┘                                  │
 └──────────────────────┬───────────────────────────────────────┘
                        │  HTTP POST (JSON)
                        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  DASHBOARD TIER                                              │
 │                                                              │
 │  ┌─────────────────────────────────────────────────────────┐ │
 │  │  FastAPI Application  (app.py)                          │ │
 │  │                                                         │ │
 │  │  Lifespan:                                              │ │
 │  │    startup  → load_config → init_database               │ │
 │  │            → ScanScheduler.start()                      │ │
 │  │    shutdown → ScanScheduler.stop()                      │ │
 │  │                                                         │ │
 │  │  Auth Layer:                                            │ │
 │  │    login/signup → auth_manager → cookie session token   │ │
 │  │                                                         │ │
 │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │ │
 │  │  │ API Router   │  │ Scheduler    │  │ Web UI       │  │ │
 │  │  │ /api/*       │  │ APScheduler  │  │ Jinja2       │  │ │
 │  │  │ (routes.py)  │  │ 60-min cycle │  │ + Chart.js   │  │ │
 │  │  └──────┬───────┘  └──────┬───────┘  └──────────────┘  │ │
 │  │         │                 │                              │ │
 │  │         ▼                 ▼                              │ │
 │  │  ┌──────────────────────────────────────────────────┐   │ │
 │  │  │  Business Logic Layer                            │   │ │
 │  │  │                                                  │   │ │
 │  │  │  IncrementalScanner   PurgeAnalyzer              │   │ │
 │  │  │  SpaceCalculator      GrowthPredictor            │   │ │
 │  │  │  PathResolver         CapacityPlanner            │   │ │
 │  │  └──────────────────────────┬───────────────────────┘   │ │
 │  │                             │                            │ │
 │  │                             ▼                            │ │
 │  │  ┌──────────────────────────────────────────────────┐   │ │
 │  │  │  SQLite Database  (space_optimizer.db)            │   │ │
 │  │  │                                                  │   │ │
 │  │  │  scan_results  │ file_metadata │ space_snapshots  │   │ │
 │  │  │  users         │ sub_app_configs                  │   │ │
 │  │  │  app_settings  │ sub_app_capacity_plans           │   │ │
 │  │  │  alert_logs                                       │   │ │
 │  │  └──────────────────────────────────────────────────┘   │ │
 │  └─────────────────────────────────────────────────────────┘ │
 └──────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagram

### 3.1 Agent → Dashboard Data Transfer

This is the core question: **How do Unix agents transfer data to a Windows dashboard?**

```
LINUX SERVER                           WINDOWS / CENTRAL HOST
─────────────                          ──────────────────────

1. cron fires space_agent.sh
   (or systemd timer)
        │
2. Agent reads agent.conf
   - SERVER_URL=http://10.0.1.5:8080
   - NAS_MOUNT=/mnt/nas_prod
   - SUB_APPS="billing:billing,logs:logs_*"
        │
3. For each SUB_APP:
   a. du -sb <path>      → total_size_bytes
   b. find <path> -type f | wc -l  → file_count
   c. find <path> -type d | wc -l  → dir_count
   d. find <path> -type f -print0  → per-file stats
      stat --format='%s %Y %X %W %n'
        │
4. Agent builds JSON payload:
   {
     "server_name": "prod-server-01",
     "server_host": "10.0.1.100",
     "sub_apps": [
       {
         "name": "billing",
         "total_size_bytes": 5368709120,
         "file_count": 1234,
         "dir_count": 56,
         "files": [
           {
             "path": "/mnt/nas_prod/billing/txn.csv",
             "size_bytes": 104857600,
             "last_modified": "2026-05-01T12:00:00",
             "last_accessed": "2026-05-28T09:30:00",
             "extension": ".csv"
           }, ...
         ]
       }
     ]
   }
        │
5. curl -X POST http://10.0.1.5:8080/api/agent/report \
     -H "Content-Type: application/json"            ──────►  6. FastAPI receives POST
     -d @/tmp/scan_payload.json                                  │
                                                           7. routes.py validates payload
                                                              - checks server_name
                                                              - iterates sub_apps[]
                                                                  │
                                                           8. For each sub_app:
                                                              a. Upsert FileMetadata rows
                                                              b. Insert ScanResult record
                                                              c. Insert SpaceSnapshot
                                                              d. Commit to SQLite
                                                                  │
                                                           9. Dashboard queries DB:
                                                              - Aggregates by server/sub_app
                                                              - Runs growth regression
                                                              - Computes purge candidates
                                                                  │
                                                           10. Web UI renders via Jinja2 +
                                                               Chart.js AJAX calls to /api/*
```

**Key points:**
- The agent uses only `curl` for network communication — works on minimal Linux installs.
- The dashboard listens on all interfaces (`0.0.0.0:8080`) so any machine on the network can reach it.
- For cross-network (agent on Linux, dashboard on Windows), ensure firewall allows TCP port 8080.
- For HTTPS, place a reverse proxy (nginx, Caddy) in front of FastAPI.
- No agent-side database — all state lives in the central SQLite database.

### 3.2 Scan Scheduler Internal Flow

```
┌──────────────────────────────────────────────────────────────┐
│  Application Startup (lifespan)                              │
│                                                              │
│  1. load_config("server_config/servers.yaml")                │
│  2. init_database("space_optimizer.db")                      │
│  3. ScanScheduler(config, session_factory)                   │
│  4. scheduler.start()                                        │
│     ├─ APScheduler.add_job(interval=60min)                   │
│     └─ _run_scan_cycle()  ← immediate first scan             │
│                                                              │
│  Every 60 minutes:                                           │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  _run_scan_cycle()                                   │    │
│  │                                                      │    │
│  │  for server in config.servers:                        │    │
│  │    for sub_app in server.sub_apps:                    │    │
│  │      paths = resolve_sub_app_paths(server, sub_app)   │    │
│  │      for path in paths:                               │    │
│  │        if first_scan:                                 │    │
│  │          _perform_full_scan(path)                     │    │
│  │        else:                                          │    │
│  │          _perform_incremental_scan(path, since=last)  │    │
│  │                                                      │    │
│  │  Result: ScanResult + SpaceSnapshot saved to DB       │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  Application Shutdown:                                       │
│  5. scheduler.stop()                                         │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Authentication Flow

```
  User Browser                    FastAPI (app.py)                  SQLite DB
  ────────────                    ──────────────                    ─────────

  GET /login ──────────────────► render login.html
                                 (product name + tagline)

  POST /login ─────────────────► authenticate_user(db, user, pass)
  {username, password}                │
                                      ├─ query User by username
                                      ├─ hash_password(input)
                                      ├─ compare with stored hash
                                      │
                              ┌───────┴───────┐
                              │ Match?        │
                              │ Yes           │ No
                              ▼               ▼
                       _make_session_token()  return error template
                       token = "user:hash16"
                              │
                       Set-Cookie: session_token=<token>
                       302 Redirect → /
                              │
  GET / ──────────────────────► _get_current_user(token)
  Cookie: session_token=...         │
                                    ├─ split token → username, hash_prefix
                                    ├─ query User by username
                                    ├─ verify user.password_hash[:16] == hash_prefix
                                    │
                                    ▼
                              render dashboard.html (logged in)

  GET /logout ────────────────► delete_cookie("session_token")
                                302 Redirect → /login
```

---

## 4. Database Schema

### Entity Relationship Diagram

```
┌────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  ScanResult    │    │  FileMetadata    │    │ SpaceSnapshot   │
│────────────────│    │──────────────────│    │─────────────────│
│ id (PK)        │    │ id (PK)          │    │ id (PK)         │
│ server_name    │    │ server_name      │    │ server_name     │
│ sub_app_name   │    │ sub_app_name     │    │ sub_app_name    │
│ scan_timestamp │    │ file_path        │    │ snapshot_ts     │
│ total_size     │    │ file_size_bytes  │    │ total_size      │
│ file_count     │    │ file_extension   │    │ file_count      │
│ dir_count      │    │ last_modified    │    └─────────────────┘
│ scan_type      │    │ last_accessed    │
│ duration_sec   │    │ created_at       │    ┌─────────────────┐
└────────────────┘    │ last_scanned     │    │ SubAppConfigDB  │
                      │ is_deleted       │    │─────────────────│
┌────────────────┐    └──────────────────┘    │ id (PK)         │
│  User          │                            │ server_name     │
│────────────────│    ┌──────────────────┐    │ sub_app_name    │
│ id (PK)        │    │ AppSettings      │    │ path            │
│ username (UQ)  │    │──────────────────│    │ patterns        │
│ email (UQ)     │    │ id (PK)          │    │ is_dedicated    │
│ password_hash  │    │ setting_key (UQ) │    └─────────────────┘
│ display_name   │    │ setting_value    │
│ created_at     │    │ updated_at       │    ┌─────────────────────┐
│ last_login     │    └──────────────────┘    │ SubAppCapacityPlan  │
│ is_active      │                            │─────────────────────│
└────────────────┘    ┌──────────────────┐    │ id (PK)             │
                      │  AlertLog        │    │ server_name         │
                      │──────────────────│    │ sub_app_name        │
                      │ id (PK)          │    │ daily_consumption   │
                      │ server_name      │    │ growth_rate_pct     │
                      │ sub_app_name     │    │ purge_schedule_json │
                      │ alert_type       │    │ monthly_alloc_gb    │
                      │ current_usage_gb │    │ alert_threshold_pct │
                      │ allocation_gb    │    │ contact_email       │
                      │ usage_pct        │    └─────────────────────┘
                      │ sent_to_email    │
                      │ sent_success     │
                      └──────────────────┘
```

### Table Summary

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `scan_results` | Audit trail of every scan execution | server_name, sub_app_name, total_size_bytes, scan_type |
| `file_metadata` | Per-file records for incremental scanning and purge analysis | file_path, file_size_bytes, file_extension, last_modified, is_deleted |
| `space_snapshots` | Hourly/daily aggregates for growth prediction | server_name, sub_app_name, total_size_bytes, snapshot_timestamp |
| `users` | Login credentials (SHA-256 hashed passwords) | username, email, password_hash, is_active |
| `sub_app_configs` | Dynamic server/sub-app mappings from Settings UI | server_name, sub_app_name, path, patterns |
| `app_settings` | Key-value store for cost rate, excluded mounts | setting_key, setting_value |
| `sub_app_capacity_plans` | Per-team capacity planning parameters | daily_consumption_gb, growth_rate_pct, purge_schedule_json, monthly_allocation_gb |
| `alert_logs` | Record of threshold alert emails sent | alert_type, usage_pct, sent_to_email, sent_success |

---

## 5. Application Flowchart

```
                    ┌─────────────────┐
                    │   User opens    │
                    │   browser to    │
                    │  :8080/login    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Has account?   │
                    └──┬──────────┬───┘
                  No   │          │ Yes
                       ▼          ▼
              ┌─────────────┐  ┌──────────────┐
              │  /signup    │  │  POST /login │
              │  form       │  │  username +  │
              │  username + │  │  password    │
              │  email +    │  └──────┬───────┘
              │  password   │         │
              └──────┬──────┘         │
                     │                │
                     ▼                ▼
              create_user()    authenticate_user()
                     │                │
                     │                ▼
                     │         ┌──────────────┐
                     │         │  Valid?       │
                     │         └──┬────────┬──┘
                     │       No   │        │ Yes
                     │            ▼        ▼
                     │     error msg   Set session cookie
                     │                 Redirect → /
                     ▼                      │
              Redirect → /login             │
                                            ▼
                              ┌──────────────────────────┐
                              │   DASHBOARD (/)           │
                              │   - Summary cards         │
                              │   - Server filter         │
                              │   - Pie + Bar charts      │
                              │   - Growth/Purge/Forecast │
                              │     combined chart        │
                              └──────────┬───────────────┘
                                         │
                        ┌────────────────┼────────────────┐
                        ▼                ▼                ▼
               ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
               │  /purge      │ │ /predictions │ │ /extensions  │
               │  Purge       │ │ Growth &     │ │ File type    │
               │  Report      │ │ Forecast     │ │ analytics    │
               │  - threshold │ │ - server dd  │ │ - extensions │
               │    filter    │ │ - sub-app dd │ │ - sizes      │
               │  - top 50    │ │ - cost+size  │ │ - recommend  │
               │  - delete    │ │   charts     │ │   actions    │
               │    buttons   │ │ - avg line   │ └──────────────┘
               │  - CSV export│ └──────────────┘
               └──────────────┘        │
                        │              │
                        ▼              ▼
               ┌──────────────────────────────────┐
               │  /settings                        │
               │  - Add/edit servers               │
               │  - Add/edit sub-apps (dropdowns)  │
               │  - Mount paths & patterns         │
               │  - Capacity plans                 │
               │  - Cost rate ($/GB/month)         │
               │  - Excluded mounts                │
               │  - Check & Send Alerts button     │
               └──────────────────────────────────┘
```

---

## 6. Incremental Scanning Algorithm

The incremental scanner is the core optimization that enables monitoring 10 TB+ servers without full re-scans.

```
scan_sub_app(server, sub_app, path):
    │
    ├── Query: last_scan = most recent ScanResult for (server, sub_app)
    │
    ├── IF last_scan is None:
    │       FULL SCAN:
    │       1. scan_directory_recursive(path, collect_file_info=True)
    │       2. DELETE existing FileMetadata for (server, sub_app)
    │       3. INSERT FileMetadata row for each file found
    │       4. INSERT ScanResult (type="full")
    │       5. INSERT SpaceSnapshot
    │       6. COMMIT
    │
    └── ELSE:
            INCREMENTAL SCAN:
            1. scan_files_since(path, since=last_scan.timestamp)
               → uses: find <path> -newer <timestamp_file> -type f
            2. For each changed file:
               a. UPSERT FileMetadata (update size, mtime, atime)
            3. Recompute totals from FileMetadata where is_deleted=0
            4. INSERT ScanResult (type="incremental")
            5. INSERT SpaceSnapshot
            6. COMMIT
```

---

## 7. Growth Prediction Model

```
Input:   SpaceSnapshot records for (server, sub_app) over last 90 days
Model:   Simple linear regression: size = slope × time + intercept
Output:  Predicted growth for 1 week, 1 month, 1 year, 5 years

Algorithm:
    1. Fetch snapshots WHERE timestamp >= now() - 90 days
    2. Convert timestamps to Unix epoch (float seconds)
    3. Compute linear regression (numpy):
       slope     = (n·Σxy - Σx·Σy) / (n·Σx² - (Σx)²)
       intercept = (Σy - slope·Σx) / n
       R²        = 1 - SS_res / SS_tot
    4. For each forecast period (7d, 30d, 365d, 1825d):
       predicted_total = slope × (now + period_seconds) + intercept
       growth          = predicted_total - current_size
       growth_pct      = (growth / current_size) × 100
    5. Attach R² as confidence score (0.0 = no fit, 1.0 = perfect)
```

---

## 8. Capacity Alert Pipeline

```
Check Allocations:
    │
    ├── For each SubAppCapacityPlan:
    │     1. Query current total_size_bytes from latest ScanResult
    │     2. Convert to GB
    │     3. Compute usage_pct = current_gb / monthly_allocation_gb × 100
    │     4. IF usage_pct >= alert_threshold_pct (default 80%):
    │          a. Check AlertLog for recent alert (24h dedup)
    │          b. IF no recent alert:
    │               - Send SMTP email to contact_email
    │               - INSERT AlertLog record
    │
    └── Triggered manually via "Check & Send Alerts" button in Settings
```

---

## 9. Technology Stack

| Layer | Technology | License |
|-------|-----------|---------|
| Web framework | FastAPI 0.100+ | MIT |
| ASGI server | Uvicorn | BSD |
| ORM | SQLAlchemy 2.0+ | MIT |
| Database | SQLite 3 | Public domain |
| Template engine | Jinja2 | BSD |
| Charts | Chart.js 4.x | MIT |
| CSS framework | Bootstrap 5.3 | MIT |
| Scheduler | APScheduler 3.x | MIT |
| Numeric | NumPy | BSD |
| TTS (demo only) | edge-tts | MIT |
| Agent | POSIX shell (`bash`, `curl`, `du`, `find`, `stat`, `awk`) | — |

All dependencies are open-source.

---

## 10. Deployment Options

### Option A: Direct Python (simplest)
```bash
pip install -r requirements.txt
python run.py
```

### Option B: Docker
```bash
docker build -t nas-capacity-pulse .
docker run -p 8080:8080 -v $(pwd)/data:/app/data nas-capacity-pulse
```

### Option C: Behind Reverse Proxy (production)
```
Client → nginx (443 HTTPS) → Uvicorn (8080 HTTP) → FastAPI → SQLite
```

### Agent Deployment
```bash
# Copy to each Linux server and schedule via cron
*/60 * * * * /opt/space_agent/space_agent.sh --config /opt/space_agent/agent.conf --once
```

---

## 11. Security Considerations

| Area | Current State | Recommendation |
|------|---------------|----------------|
| Password storage | SHA-256 hash | Upgrade to bcrypt/argon2 for brute-force resistance |
| Session tokens | `username:hash_prefix` cookie | Migrate to JWT with expiry and refresh tokens |
| Default password | Env var `DEFAULT_PASSWORD` | Enforce minimum complexity on signup |
| Transport | HTTP by default | Deploy HTTPS via reverse proxy (nginx/Caddy) |
| CSRF | Not implemented | Add CSRF tokens to forms |
| Rate limiting | Not implemented | Add rate limiting to login/signup endpoints |
| Input validation | Pydantic models on API | Add server-side HTML form validation |
| SQL injection | Prevented by SQLAlchemy ORM | No action needed — ORM parameterizes all queries |
