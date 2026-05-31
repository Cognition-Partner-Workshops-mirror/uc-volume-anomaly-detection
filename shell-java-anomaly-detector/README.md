# Volume Anomaly Detection — Shell/Java Edition

## Overview

A **Python-free** implementation of the Volume Anomaly Detection system, designed
for Linux servers that do not have Python installed. Uses **shell scripting** (Bash + AWK)
for the anomaly detection engine and a **Java-based web dashboard** for visualization.

This is a direct port of the Python codebase (`src/agents/`, `src/detectors/`, etc.)
and the Server Space Optimizer dashboard (`server_space_optimizer/`), reusing the
**same test data and detection algorithms** so results can be compared side by side.

## Architecture

```
┌───────────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│   Shell Scripts       │────▶│  JSON Files      │────▶│  Java HTTP Server │
│                       │     │  (output/)       │     │  (JDK built-in)   │
│  • build-baselines.sh │     │                  │     │                   │
│  • detect-anomalies.sh│     │  anomalies.json  │     │  /api/anomalies   │
│  • generate-report.sh │     │  baselines.json  │     │  /api/baselines   │
│  • space-monitor.sh   │     │  report.json     │     │  /api/dashboard   │
└───────────────────────┘     └──────────────────┘     └───────┬───────────┘
                                                               │
                                                        ┌──────▼──────────┐
                                                        │  Browser UI     │
                                                        │  (HTML/CSS/JS)  │
                                                        │  Chart.js       │
                                                        └─────────────────┘
```

## Requirements

- **Linux** (any distribution)
- **Bash 4+** (standard on all modern Linux)
- **AWK** (GNU awk or mawk — standard on all Linux)
- **JDK 11+** for the web dashboard (auto-installed by `install.sh`)
- **No Python required**

## Quick Start

```bash
# 1. Make scripts executable
chmod +x bin/*.sh bin/lib/*.sh webapp/build.sh install.sh

# 2. Run the anomaly detection pipeline
./bin/anomaly-detector.sh --data data/historical/sample_transactions.csv

# 3. Build the Java dashboard
cd webapp && ./build.sh && cd ..

# 4. Start the dashboard
java -jar webapp/build/AnomalyDashboard.jar \
  --port 8080 \
  --data-dir output \
  --web-dir webapp/web

# 5. Open browser: http://localhost:8080
```

## Installation (Production)

```bash
# Full installation with systemd service
sudo ./install.sh

# Or without systemd service (non-root)
./install.sh --no-service

# Uninstall
sudo ./uninstall.sh
```

## Project Structure

```
shell-java-anomaly-detector/
├── README.md                        # This file
├── install.sh                       # Automated installer
├── uninstall.sh                     # Clean removal script
├── bin/
│   ├── anomaly-detector.sh          # Main entry: orchestrates the pipeline
│   ├── build-baselines.sh           # Build seasonal baselines from CSV
│   ├── detect-anomalies.sh          # Z-score + seasonal anomaly detection
│   ├── generate-report.sh           # Incident report generator
│   ├── space-monitor.sh             # NAS space monitoring agent
│   └── lib/
│       ├── math_utils.sh            # Statistical functions (mean, std, z-score)
│       ├── csv_parser.sh            # CSV parsing utilities
│       ├── config.sh                # Configuration management
│       ├── json_utils.sh            # JSON output helpers
│       └── recommendations.sh       # Runbook recommendation engine
├── webapp/
│   ├── build.sh                     # Java compilation + JAR packaging
│   ├── src/com/anomaly/
│   │   └── AnomalyDashboard.java    # HTTP server + API handlers
│   └── web/
│       ├── index.html               # Dashboard UI
│       ├── style.css                # Gradient theme (matches Python UI)
│       └── app.js                   # Chart.js charts + API integration
├── config/
│   └── detection_rules.conf         # Detection thresholds (key=value)
├── data/
│   ├── historical/
│   │   └── sample_transactions.csv  # Same test data as Python version
│   └── baselines/                   # Generated baselines (JSON)
├── output/                          # Detection results (JSON + text)
└── docs/
    └── MIGRATION_WORKFLOW.md        # Detailed migration documentation
```

## Component Mapping (Python → Shell/Java)

| Python Component                    | Shell/Java Equivalent              |
|-------------------------------------|------------------------------------|
| `src/agents/anomaly_detector.py`    | `bin/anomaly-detector.sh`          |
| `src/detectors/zscore_detector.py`  | `bin/detect-anomalies.sh` (AWK)    |
| `src/detectors/seasonal_detector.py`| `bin/build-baselines.sh` (AWK)     |
| `src/agents/recommendation_engine.py`| `bin/lib/recommendations.sh`      |
| `src/agents/incident_insight.py`    | `bin/generate-report.sh`           |
| `server_space_optimizer/app.py`     | `webapp/src/.../AnomalyDashboard.java` |
| `server_space_optimizer/agent/space_agent.sh` | `bin/space-monitor.sh`    |
| `config/detection_rules.yaml`       | `config/detection_rules.conf`      |

## Detection Algorithms

### Z-Score Detection
Computes z-scores against seasonal baselines:
- **Warning**: z ≥ 2.0σ → MEDIUM severity
- **Critical**: z ≥ 3.0σ → HIGH severity
- **Extreme**: z ≥ 6.0σ → CRITICAL severity

### Seasonal Detection
Builds hour-by-day-of-week baselines from historical data:
- Groups observations by (hour_of_day, day_of_week)
- Computes mean and sample standard deviation per bucket
- Flags deviations ≥ 2.5σ from the seasonal expectation

### Latency Detection
Monitors average latency against baseline expectations,
flagging spikes that may indicate resource contention.

## Configuration

Edit `config/detection_rules.conf` to adjust thresholds:

```bash
ZSCORE_WARNING_THRESHOLD=2.0
ZSCORE_CRITICAL_THRESHOLD=3.0
SEASONAL_DEVIATION_THRESHOLD=2.5
SEASONAL_MIN_SAMPLES=4
DASHBOARD_PORT=8080
```

## Comparing with the Python Version

Both implementations use the **same CSV test data** and **same detection algorithms**.
To compare:

```bash
# Run Python version
cd /path/to/original
python -m src.agents.anomaly_detector --data data/historical/sample_transactions.csv

# Run Shell/Java version
cd shell-java-anomaly-detector
./bin/anomaly-detector.sh --data data/historical/sample_transactions.csv

# Compare output JSON files
diff <(jq -S . output/anomalies.json) <(jq -S . /path/to/python/output/anomalies.json)
```
