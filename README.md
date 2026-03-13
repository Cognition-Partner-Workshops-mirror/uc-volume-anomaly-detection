# Volume-Based Anomaly Detection for Early Issue Identification

## Overview

This project uses agentic AI to detect abnormal transaction volume patterns after releases, enabling early identification of issues before end-user impact occurs.

## Problem Statement

Without preconfigured alerts, volume-related issues often go unnoticed until external users report problems, increasing reputational and financial risk. Traditional threshold-based alerting misses gradual degradation and novel failure patterns.

## Architecture

```
┌──────────────────────┐     ┌───────────────────────────┐
│  Anomaly Detection   │────▶│  Service Health Assessment │
│  Agent               │     │  Agent                    │
└──────────────────────┘     └───────────┬───────────────┘
                                         │
┌──────────────────────┐     ┌───────────▼───────────────┐
│  Knowledge-Based     │◀────│  Incident Insight         │
│  Recommendation Agent│     │  Agent                    │
└──────────────────────┘     └───────────────────────────┘
```

### Agent Responsibilities

| Agent | Role |
|-------|------|
| **Anomaly Detection Agent** | Establishes baselines from historical data and identifies abnormal volume deviations |
| **Service Health Assessment Agent** | Correlates detected anomalies with service health signals (latency, error rates, CPU) |
| **Knowledge-Based Recommendation Agent** | Suggests corrective actions using prior incidents and runbooks |
| **Incident Insight Agent** | Consolidates findings into actionable summaries for support teams |

## Project Structure

```
├── src/
│   ├── agents/                       # Agent implementations
│   │   ├── anomaly_detector.py       # Baseline calculation and anomaly detection
│   │   ├── service_health.py         # Service health correlation
│   │   ├── recommendation_engine.py  # Knowledge-based recommendations
│   │   └── incident_insight.py       # Finding consolidation
│   ├── detectors/                    # Detection algorithms
│   │   ├── zscore_detector.py        # Z-score based detection
│   │   ├── seasonal_detector.py      # Seasonal decomposition
│   │   └── prophet_detector.py       # Prophet-based forecasting
│   ├── models/                       # Data models
│   │   ├── transaction.py            # Transaction volume models
│   │   ├── anomaly.py                # Anomaly event models
│   │   └── service_health.py         # Service health models
│   └── utils/                        # Shared utilities
│       ├── metrics_client.py         # Prometheus/metrics client
│       └── notification.py           # Alert notification
├── data/
│   ├── historical/                   # Historical transaction data
│   │   └── sample_transactions.csv   # 90-day sample transaction volumes
│   └── baselines/                    # Computed baselines
│       └── baseline_config.json      # Baseline configuration
├── config/
│   └── detection_rules.yaml          # Detection thresholds and rules
├── dashboards/
│   └── grafana_dashboard.json        # Grafana dashboard definition
├── tests/                            # Test suite
├── docs/                             # Documentation
├── requirements.txt
├── Dockerfile
└── .gitignore
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Generate sample historical data
python -m src.utils.generate_sample_data

# Run anomaly detection on sample data
python -m src.agents.anomaly_detector --data data/historical/sample_transactions.csv

# Start the monitoring service
python -m src.agents.anomaly_detector --mode=live
```

## Configuration

Set the following environment variables (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `METRICS_ENDPOINT` | Prometheus/metrics endpoint URL |
| `DETECTION_SENSITIVITY` | Anomaly sensitivity (1-10, default: 5) |
| `BASELINE_WINDOW_DAYS` | Days of history for baseline (default: 30) |
| `ALERT_WEBHOOK_URL` | Webhook URL for alert notifications |
| `GRAFANA_URL` | Grafana instance URL for dashboard links |

## Business Outcomes

- **Early Detection**: Reduced time to identify production issues
- **Operational Resilience**: Faster, more informed response to emerging problems
- **Customer Protection**: Minimized customer-visible impact

## Controls

Recommendations are advisory only. Final remediation decisions are owned by support teams. All detections and recommendations are logged for post-incident review.

## License

MIT
