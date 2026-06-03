# NAS Capacity Pulse

> **Volume Anomaly Detection & Storage Forecaster**

Enterprise-grade NAS storage monitoring that breaks down space consumption at the **sub-application level** — something traditional tools like Grafana cannot do. Lightweight POSIX shell agents run on Linux servers and report to a central web dashboard accessible from any Windows/macOS/Linux workstation.

---

## Problem Statement

In large enterprises, NAS storage is shared across dozens of teams and services on the same server. Existing monitoring tools (Grafana + node_exporter, Prometheus, Zabbix) report disk usage **only at the server or filesystem level**. They cannot answer:

- *Which sub-application is consuming the most space?*
- *Which team's files are growing fastest?*
- *Which old files are safe to purge, and how much space would that reclaim?*
- *What will storage costs look like in 1 year or 5 years?*

Without this visibility, storage problems go unnoticed until disks fill up, causing outages, failed batch jobs, and emergency capacity purchases.

**NAS Capacity Pulse** solves this by providing **sub-app level granularity**, **purge eligibility reports**, **cost forecasting**, and **file extension analytics** — all from a single dashboard.

---

## Overview

| Feature | Description |
|---------|-------------|
| **Sub-App Breakdown** | Space usage per team/service, not just per server |
| **Incremental Scanning** | 60-minute refresh using only `find`/`stat` deltas — efficient on 10 TB+ servers |
| **Growth & Forecast** | Linear regression on historical snapshots; projects 1 week → 5 years |
| **Purge Eligibility** | Files ranked by age and size; user-initiated deletion with confirmation |
| **Cost Estimation** | Configurable $/GB/month rate; cost cards on dashboard and forecast page |
| **File Extension Analytics** | Unique extensions with optimization recommendations (compress, archive, delete) |
| **Capacity Planning** | Per-team daily consumption, growth rate, purge schedule, allocation alerts |
| **Shell Agent** | Pure POSIX bash — no Python/Java required on monitored servers |
| **User Auth** | Username/password login with SHA-256 hashing; SSO-ready |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     LINUX SERVERS (Monitored)                       │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │ space_agent  │  │ space_agent  │  │ space_agent  │   ...         │
│  │   .sh        │  │   .sh        │  │   .sh        │               │
│  │ (POSIX only) │  │ (POSIX only) │  │ (POSIX only) │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │ curl POST        │                 │                       │
│         │ (JSON)           │                 │                       │
└─────────┼──────────────────┼─────────────────┼───────────────────────┘
          │                  │                 │
          ▼                  ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│               CENTRAL DASHBOARD (Windows / Linux / macOS)           │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FastAPI + Uvicorn (Python)           Port 8080              │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐ │   │
│  │  │ REST API   │  │ Scan         │  │ Web UI (Jinja2 +     │ │   │
│  │  │ /api/*     │  │ Scheduler    │  │ Chart.js + Bootstrap)│ │   │
│  │  └────────────┘  │ (APScheduler)│  └──────────────────────┘ │   │
│  │                  └──────────────┘                            │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐ │   │
│  │  │ Incremental│  │ Purge        │  │ Growth Predictor     │ │   │
│  │  │ Scanner    │  │ Analyzer     │  │ (numpy regression)   │ │   │
│  │  └────────────┘  └──────────────┘  └──────────────────────┘ │   │
│  │                                                              │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  SQLite Database (space_optimizer.db)                 │   │   │
│  │  │  Tables: scan_results, file_metadata, space_snapshots│   │   │
│  │  │          users, sub_app_configs, app_settings,       │   │   │
│  │  │          sub_app_capacity_plans, alert_logs          │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow: Linux Agents → Windows Dashboard

1. **Shell agents** (`space_agent.sh`) run on each Linux server via cron or systemd timer.
2. Agents use only standard POSIX tools (`du`, `find`, `stat`, `awk`, `curl`) — no runtime dependencies.
3. Each agent scans its configured NAS mounts and sub-app directories.
4. Results are POSTed as JSON to the central dashboard's `/api/agent/report` endpoint via `curl`.
5. The dashboard runs on any OS (Windows, Linux, macOS) — it only needs Python 3.11+.
6. Communication is over HTTP/HTTPS (configurable). Firewalls must allow the dashboard port (default 8080).

---

## Agent Responsibilities

| Component | Role |
|-----------|------|
| **Shell Agent** (`space_agent.sh`) | Scans NAS mounts using `du`/`find`/`stat`; POSTs JSON to dashboard REST API. Runs via cron or systemd. No Python/Java needed. |
| **Python Agent** (`linux_agent.py`) | Alternative agent for servers with Python. Uses `os.walk()` and `requests`. |
| **Incremental Scanner** | Tracks file metadata in SQLite; only processes files changed since the last scan. Handles 10 TB+ servers efficiently. |
| **Scan Scheduler** | APScheduler-based 60-minute background job. Iterates all servers and sub-apps each cycle. |
| **Purge Analyzer** | Identifies files older than configurable thresholds (7/30/60/90/180/365 days). Ranks by size for maximum impact. |
| **Growth Predictor** | Linear regression on historical `SpaceSnapshot` records. Projects growth/cost for 1 week, 1 month, 1 year, 5 years. |
| **Capacity Planner** | Per-sub-app consumption estimates, purge schedules, and monthly allocation with 80% threshold email alerts. |
| **Auth Manager** | SHA-256 password hashing, cookie-based sessions. Default password from `DEFAULT_PASSWORD` env var. |

---

## Project Structure

```
├── server_space_optimizer/          # Main application package
│   ├── app.py                       # FastAPI app, auth routes, lifespan
│   ├── config.py                    # Pydantic config models, YAML loader
│   ├── api/
│   │   └── routes.py                # REST API endpoints (1850+ lines)
│   ├── auth/
│   │   └── auth_manager.py          # Login, signup, session management
│   ├── models/
│   │   ├── database.py              # SQLAlchemy ORM (8 tables)
│   │   └── schemas.py               # Pydantic request/response models
│   ├── scanner/
│   │   ├── incremental_scanner.py   # Delta-based file scanning
│   │   ├── space_calculator.py      # Directory traversal, size formatting
│   │   ├── path_resolver.py         # Resolve sub-app paths (dedicated/relative/pattern)
│   │   └── purge_analyzer.py        # Purge eligibility analysis
│   ├── predictor/
│   │   └── growth_predictor.py      # Linear regression forecasting
│   ├── scheduler/
│   │   └── scan_scheduler.py        # APScheduler 60-min scan cycles
│   ├── agent/
│   │   ├── space_agent.sh           # POSIX shell agent (no dependencies)
│   │   └── linux_agent.py           # Python-based agent alternative
│   ├── scripts/
│   │   └── generate_demo_data.py    # Demo data generator (1000+ files)
│   ├── static/
│   │   ├── css/styles.css           # Gradient dashboard styling
│   │   └── js/app.js                # Chart.js charts, AJAX, UI logic
│   └── templates/                   # Jinja2 HTML templates
│       ├── base.html                # Shared layout with navbar
│       ├── dashboard.html           # Main dashboard
│       ├── purge.html               # Purge eligibility report
│       ├── predictions.html         # Growth & forecast
│       ├── extensions.html          # File extension analytics
│       ├── settings.html            # Server/sub-app config UI
│       ├── login.html               # Login page
│       └── signup.html              # Signup page
├── server_config/
│   ├── servers.yaml                 # Server and sub-app configuration
│   └── agent.conf.example           # Shell agent config template
├── demo/
│   ├── NAS_Capacity_Pulse_Demo_Video.mp4   # Demo walkthrough video
│   └── NAS_Capacity_Pulse_Demo_Video.srt   # Optional subtitles
├── docs/
│   ├── KNOWLEDGE_BASE.md            # Architecture & data model reference
│   ├── GAP_ANALYSIS.md              # Engineering gap assessment
│   ├── REMEDIATION_ROADMAP.md       # Phased remediation plan
│   └── TECHNICAL_DESIGN.md          # Technical design & flowchart
├── tests/
│   ├── test_space_optimizer.py      # Core module tests (36 tests)
│   └── test_detectors.py            # Anomaly detector tests
├── src/                             # Original anomaly detection agents
│   ├── agents/                      # Detection, health, recommendation agents
│   ├── detectors/                   # Z-score, seasonal decomposition
│   ├── models/                      # Transaction, anomaly, health models
│   └── utils/                       # Metrics client, notifications
├── config/
│   └── detection_rules.yaml         # Anomaly detection thresholds
├── run.py                           # Application entry point
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Container build
└── .gitignore
```

---

## Business Outcomes

| Outcome | How NAS Capacity Pulse Delivers It |
|---------|-----------------------------------|
| **Cost Visibility** | Dollar-amount forecasting ($/GB/month) tied to actual growth trends. Teams can budget for capacity upgrades months in advance. |
| **Proactive Capacity Management** | Growth prediction (1 week → 5 years) prevents surprise disk-full outages that disrupt batch jobs and production services. |
| **Storage Accountability** | Sub-app level breakdown assigns storage costs to specific teams, enabling chargeback/showback models. |
| **Efficient Cleanup** | Purge eligibility reports surface the largest, oldest files first. Controlled deletion workflow prevents accidental data loss. |
| **Reduced Operational Overhead** | Lightweight shell agent requires zero setup on monitored servers — no Python, Java, or package manager needed. |
| **Compliance & Audit** | CSV export of purge reports, file extension analytics, and alert logs provide audit trails for storage governance. |
| **Alerting** | Automated email alerts when a team's usage reaches 80% of their allocated capacity. |

---

## Controls

| Control | Description |
|---------|-------------|
| **User-Initiated Deletion Only** | Files are never auto-deleted. Every purge action requires explicit user confirmation via the UI. |
| **Role-Based Access** | Login/signup with SHA-256 hashing. Sessions expire after 24 hours. |
| **Excluded System Mounts** | System paths (`/var`, `/opt`, `/home`, `/tmp`, `/etc`, `/boot`, etc.) are excluded from scanning by default. Configurable in Settings. |
| **Scan Isolation** | Each scan cycle is atomic per sub-app. Failures in one sub-app don't affect others. |
| **Alert Deduplication** | Threshold alerts have a 24-hour cooldown to prevent notification spam. |
| **Secrets from Environment** | Passwords and secret keys are sourced from environment variables (`DEFAULT_PASSWORD`, `SECRET_KEY`), not hardcoded. |

---

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Setup & Run

```bash
# 1. Clone the repository
git clone https://github.com/your-org/uc-volume-anomaly-detection.git
cd uc-volume-anomaly-detection

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Set environment variables for production
export SECRET_KEY="your-production-secret-key"
export DEFAULT_PASSWORD="your-default-signup-password"

# 4. Start the application (generates demo data automatically)
python run.py

# 5. Open the dashboard
#    http://localhost:8080
#    Default login: admin / welcome123 (or your DEFAULT_PASSWORD)
```

### Deploy Shell Agents on Linux Servers

```bash
# 1. Copy the agent script to each Linux server
scp server_space_optimizer/agent/space_agent.sh user@linux-server:/opt/space_agent/

# 2. Copy and edit the configuration
scp server_config/agent.conf.example user@linux-server:/opt/space_agent/agent.conf
# Edit agent.conf: set SERVER_URL, SERVER_NAME, NAS_MOUNT, SUB_APPS

# 3. Make executable and run
ssh user@linux-server
chmod +x /opt/space_agent/space_agent.sh

# Run once (for testing):
./space_agent.sh --config /opt/space_agent/agent.conf --once

# Schedule via cron (every 60 minutes):
echo "*/60 * * * * /opt/space_agent/space_agent.sh --config /opt/space_agent/agent.conf --once" | crontab -

# Or run as a daemon:
nohup ./space_agent.sh --config /opt/space_agent/agent.conf &
```

### Configuration

Edit `server_config/servers.yaml` to define your servers and sub-apps:

```yaml
scan_interval_minutes: 60
database_path: "space_optimizer.db"
host: "0.0.0.0"
port: 8080

servers:
  - server_name: "prod-server-01"
    server_host: "10.0.1.100"
    nas_mount_path: "/mnt/nas/production"
    sub_apps:
      - name: "billing-service"
        path: "billing"
      - name: "application-logs"
        patterns: ["logs_*", "audit_logs"]
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Session cookie signing key | `space-optimizer-dev-key` |
| `DEFAULT_PASSWORD` | Default password for new signups | `welcome123` |
| `CONFIG_PATH` | Path to servers.yaml config file | `server_config/servers.yaml` |
| `HOST` | Web server bind address | `0.0.0.0` |
| `PORT` | Web server port | `8080` |

---

## Use Case: Grafana vs NAS Capacity Pulse

| Capability | Grafana + node_exporter | NAS Capacity Pulse |
|------------|------------------------|--------------------|
| Server-level disk usage | Yes | Yes |
| **Sub-application breakdown** | **No** | **Yes** |
| **File extension analytics** | **No** | **Yes** |
| **Purge eligibility reports** | **No** | **Yes** |
| **Cost forecasting ($/GB)** | **No** | **Yes** |
| **Capacity planning per team** | **No** | **Yes** |
| Agent dependencies | Prometheus, node_exporter | **None** (POSIX shell only) |
| Setup complexity | High (Prometheus + Grafana stack) | Low (single Python process) |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard` | Dashboard summary (all servers, sub-apps, totals) |
| GET | `/api/servers` | List all configured servers |
| GET | `/api/server/{name}` | Server detail with sub-app breakdown |
| POST | `/api/scan/trigger` | Trigger immediate scan |
| GET | `/api/scan/status` | Current scan status and timing |
| GET | `/api/purge/report` | Purge eligibility analysis |
| DELETE | `/api/purge/delete/{id}` | Delete a specific file (user-initiated) |
| GET | `/api/predictions/{server}/{sub_app}` | Growth forecast |
| GET | `/api/extensions` | File extension analytics |
| GET | `/api/chart-data` | Time-series chart data (growth/purge/forecast) |
| POST | `/api/agent/report` | Receive scan data from shell agents |
| CRUD | `/api/sub-app-configs` | Manage sub-app configurations |
| CRUD | `/api/capacity-plans` | Manage capacity plans |
| GET | `/api/settings/*` | App settings (cost rate, exclusions) |

Full interactive API docs available at `http://localhost:8080/docs` (Swagger UI).

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run only space optimizer tests
pytest tests/test_space_optimizer.py -v
```

---

## License

MIT
