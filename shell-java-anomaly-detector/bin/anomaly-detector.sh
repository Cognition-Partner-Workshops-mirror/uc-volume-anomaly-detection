#!/bin/bash
# =============================================================================
# anomaly-detector.sh — Main entry point for shell-based anomaly detection
#
# Orchestrates the full anomaly detection pipeline:
#   1. Build seasonal baselines from historical CSV data
#   2. Detect anomalies by comparing observations against baselines
#   3. Generate incident reports with recommendations
#   4. Optionally start the Java web dashboard
#
# This is the shell/Java equivalent of running:
#   python -m src.agents.anomaly_detector --data sample_transactions.csv
#
# Usage:
#   ./anomaly-detector.sh [--data <csv>] [--config <conf>] [--dashboard]
# =============================================================================

set -euo pipefail

# Resolve the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source configuration defaults
source "${SCRIPT_DIR}/lib/config.sh"

# ---- Parse CLI arguments ----
CSV_FILE=""
CONFIG_FILE=""
START_DASHBOARD=false
SKIP_BASELINES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --data)       CSV_FILE="$2"; shift 2 ;;
        --config)     CONFIG_FILE="$2"; shift 2 ;;
        --dashboard)  START_DASHBOARD=true; shift ;;
        --skip-baselines) SKIP_BASELINES=true; shift ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --data <csv>       Path to historical transaction CSV"
            echo "  --config <conf>    Path to detection configuration file"
            echo "  --dashboard        Start the Java web dashboard after detection"
            echo "  --skip-baselines   Skip baseline building (use existing baselines)"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Apply defaults for paths
if [[ -z "${CSV_FILE}" ]]; then
    CSV_FILE="${PROJECT_ROOT}/data/historical/sample_transactions.csv"
fi
if [[ -n "${CONFIG_FILE}" ]]; then
    load_detection_config "${CONFIG_FILE}"
fi

# Define output paths
BASELINES_FILE="${PROJECT_ROOT}/data/baselines/baselines.json"
ANOMALIES_FILE="${PROJECT_ROOT}/output/anomalies.json"
REPORT_JSON="${PROJECT_ROOT}/output/report.json"
REPORT_TEXT="${PROJECT_ROOT}/output/report.txt"

echo "============================================="
echo " Volume Anomaly Detection System (Shell/Java)"
echo "============================================="
echo ""
echo "Configuration:"
print_config
echo ""

# ---- Step 1: Build baselines ----
if [[ "${SKIP_BASELINES}" == "false" ]]; then
    echo ""
    echo "[Step 1/3] Building seasonal baselines..."
    bash "${SCRIPT_DIR}/build-baselines.sh" \
        --csv "${CSV_FILE}" \
        --output "${BASELINES_FILE}" \
        --min-samples "${SEASONAL_MIN_SAMPLES}"
else
    echo ""
    echo "[Step 1/3] Skipping baseline build (using existing baselines)"
fi

# ---- Step 2: Detect anomalies ----
echo ""
echo "[Step 2/3] Running anomaly detection..."
bash "${SCRIPT_DIR}/detect-anomalies.sh" \
    --csv "${CSV_FILE}" \
    --baselines "${BASELINES_FILE}" \
    --output "${ANOMALIES_FILE}"

# ---- Step 3: Generate reports ----
echo ""
echo "[Step 3/3] Generating incident reports..."
bash "${SCRIPT_DIR}/generate-report.sh" \
    --anomalies "${ANOMALIES_FILE}" \
    --output "${REPORT_JSON}" \
    --text "${REPORT_TEXT}"

echo ""
echo "============================================="
echo " Pipeline Complete"
echo "============================================="
echo ""
echo "Output files:"
echo "  Baselines:     ${BASELINES_FILE}"
echo "  Anomalies:     ${ANOMALIES_FILE}"
echo "  JSON Report:   ${REPORT_JSON}"
echo "  Text Report:   ${REPORT_TEXT}"
echo ""

# Display the text report summary
if [[ -f "${REPORT_TEXT}" ]]; then
    echo "--- Report Summary ---"
    head -20 "${REPORT_TEXT}"
    echo "..."
    echo "(Full report in ${REPORT_TEXT})"
fi

# ---- Step 4: Start dashboard (optional) ----
if [[ "${START_DASHBOARD}" == "true" ]]; then
    echo ""
    echo "Starting Java web dashboard on port ${DASHBOARD_PORT}..."
    WEBAPP_DIR="${PROJECT_ROOT}/webapp"
    if [[ -f "${WEBAPP_DIR}/build/AnomalyDashboard.jar" ]]; then
        java -jar "${WEBAPP_DIR}/build/AnomalyDashboard.jar" \
            --port "${DASHBOARD_PORT}" \
            --data-dir "${PROJECT_ROOT}/output" \
            --baselines "${BASELINES_FILE}" \
            --csv "${CSV_FILE}"
    else
        echo "Dashboard not built yet. Run: cd webapp && ./build.sh"
        echo "Then re-run with --dashboard flag."
    fi
fi
