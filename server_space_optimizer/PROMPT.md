# Server Space Optimizer - Project Prompt

## Overview
Build a **Server Space Optimizer** tool that monitors Linux NAS mount space usage
across multiple servers, providing a web dashboard accessible from Windows machines.
The system uses lightweight Linux agents that collect filesystem metrics and report
to a central FastAPI web application.

## Core Requirements

### 1. Space Calculation per Sub-Application
- Calculate the space occupied in Linux NAS mounts, broken down by sub-application
- Sub-apps can have:
  - **Dedicated paths or mounts** (e.g., `/mnt/nas1/app-billing`)
  - **Specific patterns or subfolders** within a common/shared NAS (e.g., `logs_*`, `data_202*`)
  - **Relative paths** under a server's main NAS mount point

### 2. Incremental 60-Minute Refresh
- Scan interval defaults to 60 minutes
- **Incremental scanning**: Only process files that have been added, deleted, or modified
  since the last scan, rather than re-scanning the entire server
- Critical for performance on ~10TB servers
- Uses `os.scandir()` for efficient directory traversal with cached `DirEntry.stat()`

### 3. Multi-Server Support
- Support any number of Linux servers, each configured via YAML
- Pass server info (hostname, NAS mount path, sub-apps) through configuration
- Each server can have its own set of sub-applications

### 4. Purge Eligibility Report
- Holistic view of old files eligible for cleanup
- Configurable age thresholds (default: 90, 180, 365 days)
- Files ranked by size (largest first) for maximum cleanup impact
- Export to CSV for review

### 5. Growth Predictions & Space Forecasting
- **Growth Rate**: Weekly, monthly, yearly growth predictions using linear regression
  on historical space snapshots
- **Purge Rate**: Estimate of daily/monthly space that can be reclaimed via purging
- **Net Space Forecast**: Growth minus purge potential, projected for:
  - After 1 week
  - After 1 month
  - After 1 year
  - After 5 years

### 6. Web Dashboard (Windows-accessible)
- Professional web UI built with Bootstrap 5, Chart.js, and modern gradient styling
- Viewable from Windows machines via any browser (the server runs on Linux)
- Pages:
  - **Dashboard**: Summary cards, server/sub-app breakdown, pie/bar charts
  - **Purge Report**: Filterable table with CSV export
  - **Growth & Forecast**: 4-period forecast cards, purge rate, trend charts

### 7. Linux Agent Architecture (No Python Required)
- Agents run on each Linux/Unix server using **only standard POSIX tools**
  (du, find, stat, curl, awk, date) — no Python, Java, or runtime needed
- Primary agent: `space_agent.sh` (shell script), works on any Unix server
- Optional Python agent (`linux_agent.py`) for servers where Python is available
- Agents scan local NAS mounts and POST results as JSON to the central API
- The REST API endpoint (`/api/agent/report`) is backend-agnostic — works with
  FastAPI, Tomcat, Spring Boot, Node.js, or any HTTP server that accepts JSON
- Can be deployed as a cron job, systemd timer, or continuous daemon
- For Tomcat environments: wrap the shell script in a servlet that
  shells out and forwards JSON, or use a Java HttpClient to POST directly

## Technology Stack (All Open-Source)
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, SQLite
- **Frontend**: Bootstrap 5, Chart.js, Bootstrap Icons, Google Fonts (Inter)
- **Scanner**: `os.scandir()` with stack-based traversal
- **Prediction**: NumPy linear regression on historical snapshots
- **Configuration**: YAML-based server/sub-app definitions
- **Deployment**: Docker (optional), systemd service

## Configuration Example (YAML)
```yaml
scan_interval_minutes: 60
purge_thresholds_days: [90, 180, 365]
database_path: "space_optimizer.db"
host: "0.0.0.0"
port: 8080
servers:
  - server_name: "prod-server-1"
    server_host: "192.168.1.10"
    nas_mount_path: "/mnt/nas_prod"
    sub_apps:
      - name: "billing"
        path: "billing/data"
      - name: "logging"
        patterns: ["logs_*", "audit_*"]
      - name: "archive"
        path: "/mnt/nas_archive"
        is_dedicated_mount: true
  - server_name: "prod-server-2"
    server_host: "192.168.1.11"
    nas_mount_path: "/mnt/nas_shared"
    sub_apps:
      - name: "analytics"
        path: "analytics"
      - name: "reports"
        path: "reports"
```

## Architecture
```
┌─────────────────────────────────────────────────────────┐
│                   Windows Browser                       │
│              (Dashboard, Purge, Forecast)                │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP (port 8080)
┌──────────────────────▼──────────────────────────────────┐
│         Central Server (FastAPI / Tomcat / etc.)         │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
│  │Dashboard│  │ Purge API│  │Predict API│  │Agent API│  │
│  └─────────┘  └──────────┘  └──────────┘  └─────────┘  │
│                        │                                 │
│              ┌─────────▼─────────┐                       │
│              │   SQLite Database  │                       │
│              └───────────────────┘                       │
└──────────────────────┬──────────────────────────────────┘
                       │ POST /api/agent/report (JSON)
    ┌──────────────────┼──────────────────────┐
    │                  │                      │
┌───▼────┐       ┌─────▼────┐          ┌──────▼─────┐
│Agent 1 │       │ Agent 2  │          │ Agent N    │
│Shell   │       │ Shell    │          │ Python     │
│(curl)  │       │(cron)    │          │(optional)  │
│/mnt/nas│       │/mnt/nas  │          │/mnt/nas    │
└────────┘       └──────────┘          └────────────┘
  No Python        No Python           Has Python
  required!        required!           installed
```

## Key Design Decisions
- **No runtime dependency on agents**: Shell-based agent uses only du/find/stat/curl
  so it works on any Linux/Unix server without Python or Java installed
- **Incremental over full scans**: First scan is full; subsequent scans only process
  deltas to keep 60-minute cycles fast on 10TB+ filesystems
- **UTC timestamps throughout**: All datetime values use UTC to avoid timezone mismatches
  between file mtimes and scan timestamps
- **Background scan execution**: Scan trigger API returns immediately and runs the scan
  in a FastAPI BackgroundTask so the UI can poll for status
- **POST for mutations**: Scan trigger uses POST method; all read endpoints use GET
- **Backend-agnostic agent protocol**: Agents communicate via plain JSON over HTTP,
  compatible with FastAPI, Tomcat, Spring Boot, or any REST server
- **Cron-friendly**: Shell agent supports `--once` flag for single-scan mode,
  perfect for cron jobs (`*/60 * * * * /opt/space_agent/space_agent.sh --config /opt/space_agent/agent.conf --once`)
