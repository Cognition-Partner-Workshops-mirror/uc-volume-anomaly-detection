# Migration Workflow: Python → Shell/Java Anomaly Detection

## Reverse Engineering Analysis

This document captures the migration workflow from the Python-based anomaly detection
system to a shell-scripting + Java web-dashboard implementation. The goal is to run on
any Linux server without Python installed.

---

## 1. Source System Inventory (Python)

### 1.1 Anomaly Detection Pipeline

| Python Module                         | Purpose                                       |
|---------------------------------------|-----------------------------------------------|
| `src/agents/anomaly_detector.py`      | Orchestrator: loads CSV, builds baselines, runs detection |
| `src/agents/service_health.py`        | Correlates anomalies with upstream/downstream health |
| `src/agents/recommendation_engine.py` | Maps anomaly patterns → runbook corrective actions |
| `src/agents/incident_insight.py`      | Consolidates findings into human-readable reports |
| `src/detectors/zscore_detector.py`    | Z-score based volume and latency detection    |
| `src/detectors/seasonal_detector.py`  | Seasonal (hour×day-of-week) baseline decomposition |
| `src/models/transaction.py`           | Data classes: TransactionVolume, VolumeBaseline, VolumeTimeSeries |
| `src/models/anomaly.py`              | AnomalyEvent, AnomalyReport, AnomalySeverity, AnomalyType enums |
| `src/models/service_health.py`        | ServiceHealthSnapshot, ServiceMap, HealthStatus |

### 1.2 Server Space Optimizer (PR #2)

| Python Module                                     | Purpose                                    |
|---------------------------------------------------|--------------------------------------------|
| `server_space_optimizer/app.py`                   | FastAPI web app with auth, scan scheduling |
| `server_space_optimizer/api/routes.py`            | REST API: dashboard, purge, predictions    |
| `server_space_optimizer/agent/space_agent.sh`     | Shell agent for NAS scanning (already shell-based) |
| `server_space_optimizer/scanner/space_calculator.py` | Directory size calculation              |
| `server_space_optimizer/scanner/purge_analyzer.py`  | Purge eligibility analysis              |
| `server_space_optimizer/predictor/growth_predictor.py` | Linear regression growth forecasting  |
| `server_space_optimizer/models/database.py`       | SQLAlchemy ORM: ScanResult, FileMetadata, SpaceSnapshot |
| `server_space_optimizer/config.py`                | Pydantic config from YAML                  |

### 1.3 Configuration & Data

| File                               | Format | Purpose                          |
|------------------------------------|--------|----------------------------------|
| `config/detection_rules.yaml`      | YAML   | Detection thresholds, alert rules |
| `data/historical/sample_transactions.csv` | CSV | 30 rows of transaction volumes  |
| `data/baselines/baseline_config.json` | JSON | Pre-computed baseline stats      |
| `server_config/servers.yaml`       | YAML   | Server/NAS mount configuration   |

---

## 2. Algorithm Mapping: Python → Shell/AWK

### 2.1 Statistical Functions

| Python Function          | Shell/AWK Equivalent                              |
|--------------------------|---------------------------------------------------|
| `_mean(values)`          | `awk '{s+=$1} END{print s/NR}'`                  |
| `_std(values)`           | `awk '{s+=$1;ss+=$1*$1} END{v=(ss-s*s/NR)/(NR-1);print sqrt(v)}'` |
| `z_score = (x-μ)/σ`     | `awk -v x=VAL -v m=MEAN -v s=STD 'BEGIN{print (x-m)/s}'` |
| `abs(z_score)`           | `awk -v z=VAL 'BEGIN{print (z<0)?-z:z}'`         |

### 2.2 Baseline Building (SeasonalDetector.build_baselines)

Python groups observations by `(hour, weekday)` tuple and computes mean/std per bucket.
Shell equivalent:
1. Parse CSV with `awk` to extract hour-of-day and day-of-week from timestamp
2. Group into associative arrays keyed by `hour:dow`
3. Compute mean and sample standard deviation per group
4. Output as JSON for downstream consumption

### 2.3 Z-Score Detection (ZScoreDetector.detect)

Python: `z = (count - baseline.mean_count) / baseline.std_count`
Shell: Single `awk` invocation comparing observation against matching baseline.

### 2.4 Severity Classification

| Python Condition                              | Severity  |
|-----------------------------------------------|-----------|
| `abs_z >= critical_threshold * 2`             | CRITICAL  |
| `abs_z >= critical_threshold`                 | HIGH      |
| `abs_z >= warning_threshold`                  | MEDIUM    |
| `abs_z < warning_threshold`                   | LOW       |

Mapped directly to shell `if/elif` or `awk` conditionals.

### 2.5 Recommendation Engine

Python uses a list of `RunbookEntry` dataclasses with `anomaly_types` and
`severity_threshold`. Mapped to a shell configuration file with pattern matching.

---

## 3. Architecture Mapping: Python → Java Web Dashboard

### 3.1 Web Framework

| Python (FastAPI)                | Java Equivalent                              |
|---------------------------------|----------------------------------------------|
| `FastAPI()` app                 | `com.sun.net.httpserver.HttpServer` (JDK built-in) |
| `@app.get("/api/dashboard")`   | `HttpHandler` registered on `/api/dashboard` |
| Jinja2 templates                | Static HTML + JavaScript (SPA approach)      |
| SQLAlchemy ORM                  | SQLite via JDBC (built into JDK)             |
| Pydantic schemas                | Java POJOs with JSON serialization           |

### 3.2 Dashboard Pages

| Python Page                      | Java/HTML Equivalent                         |
|----------------------------------|----------------------------------------------|
| `dashboard.html` (Jinja2)       | `index.html` — static HTML loaded via JS     |
| `predictions.html`              | Predictions section in SPA                   |
| `purge.html`                    | Purge report section in SPA                  |
| `settings.html`                 | Settings section in SPA                      |
| Chart.js charts                  | Chart.js charts (same library, browser-side) |

### 3.3 Data Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Shell Scripts   │────▶│   JSON Files     │────▶│  Java HTTP       │
│  (detection,     │     │   (output/)      │     │  Server          │
│   baselines,     │     │                  │     │  (reads JSON,    │
│   space scan)    │     │                  │     │   serves API)    │
└─────────────────┘     └──────────────────┘     └──────────────────┘
                                                         │
                                                         ▼
                                                  ┌──────────────┐
                                                  │  Browser     │
                                                  │  Dashboard   │
                                                  │  (HTML/JS)   │
                                                  └──────────────┘
```

---

## 4. Migration Steps

### Step 1: Port Statistical Engine to Shell/AWK
- Implement `math_utils.sh` with mean, std, z-score functions
- Implement `csv_parser.sh` for reading transaction CSV data
- Validate output matches Python implementation

### Step 2: Port Baseline Builder
- Implement `build-baselines.sh` using AWK to group by (hour, dow)
- Output JSON baseline file matching Python's `VolumeBaseline` structure

### Step 3: Port Anomaly Detectors
- Implement `detect-anomalies.sh` with Z-score and seasonal detection
- Map severity classification logic

### Step 4: Port Recommendation Engine
- Convert runbook entries to shell config format
- Implement pattern matching in `recommendations.sh`

### Step 5: Port Report Generator
- Implement `generate-report.sh` for JSON and text output
- Match Python's `AnomalyReport` structure

### Step 6: Build Java Web Dashboard
- Implement HTTP server using JDK built-in classes
- Port REST API endpoints from FastAPI routes
- Create HTML/CSS/JS dashboard matching the Python UI
- Add SQLite integration via JDBC for persistent storage

### Step 7: Create Installation Package
- Write `install.sh` for automated setup
- Check/install Java (OpenJDK) if needed
- Set up systemd services for background operation
- Create `uninstall.sh` for clean removal

### Step 8: Testing & Comparison
- Run both Python and Shell/Java versions on same test data
- Compare anomaly detection results
- Compare dashboard visualizations side by side

---

## 5. Dependency Comparison

| Dependency           | Python Version          | Shell/Java Version           |
|----------------------|------------------------|------------------------------|
| Runtime              | Python 3.11+           | Bash 4+, JDK 11+            |
| Web framework        | FastAPI + Uvicorn      | JDK HttpServer (built-in)   |
| Database             | SQLAlchemy + SQLite    | JDBC + SQLite (built-in JDK)|
| Charts               | Chart.js (browser)     | Chart.js (browser)          |
| Config parsing       | PyYAML, Pydantic       | Shell `source`, Java Properties |
| HTTP client          | httpx                  | curl (shell), HttpURLConnection (Java) |
| Math/stats           | Python stdlib math     | AWK math functions          |
| Logging              | structlog              | Shell tee/logger, Java logging |

---

## 6. Risk Assessment

| Risk                          | Mitigation                                    |
|-------------------------------|-----------------------------------------------|
| AWK floating-point precision  | Use `printf "%.10f"` for critical calculations |
| Large CSV files (>1M rows)    | Stream processing with AWK, never load fully  |
| No Python on target           | Shell + JDK only; JDK is commonly available   |
| Missing JDK                   | `install.sh` auto-installs OpenJDK            |
| Shell portability             | Target Bash 4+; avoid bashisms where possible |
| SQLite JDBC driver            | Bundled in JDK since Java 9 (via java.sql)    |
