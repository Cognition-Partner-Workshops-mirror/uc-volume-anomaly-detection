#!/bin/bash
# =============================================================================
# config.sh — Configuration management for the shell-based anomaly detector
#
# Reads detection thresholds and service configuration from a simple
# key=value config file (no YAML parser needed).
#
# Ported from: config/detection_rules.yaml and .env.example
# =============================================================================

# Default configuration values (matching Python defaults)
ZSCORE_WARNING_THRESHOLD="${ZSCORE_WARNING_THRESHOLD:-2.0}"
ZSCORE_CRITICAL_THRESHOLD="${ZSCORE_CRITICAL_THRESHOLD:-3.0}"
SEASONAL_DEVIATION_THRESHOLD="${SEASONAL_DEVIATION_THRESHOLD:-2.5}"
SEASONAL_MIN_SAMPLES="${SEASONAL_MIN_SAMPLES:-4}"
BASELINE_WINDOW_DAYS="${BASELINE_WINDOW_DAYS:-30}"
DETECTION_SENSITIVITY="${DETECTION_SENSITIVITY:-5}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Alert configuration
ALERT_COOLDOWN_MINUTES="${ALERT_COOLDOWN_MINUTES:-15}"
ALERT_DEDUPLICATION_WINDOW="${ALERT_DEDUPLICATION_WINDOW:-30}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"

# Dashboard configuration
DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"
DASHBOARD_HOST="${DASHBOARD_HOST:-0.0.0.0}"

# Data paths (relative to project root)
DATA_DIR="${DATA_DIR:-data}"
OUTPUT_DIR="${OUTPUT_DIR:-output}"
BASELINES_DIR="${BASELINES_DIR:-data/baselines}"

# Load a configuration file in key=value format.
# Lines starting with # are treated as comments and ignored.
# Arguments: config_file_path
load_detection_config() {
    local config_file="$1"
    if [[ ! -f "${config_file}" ]]; then
        echo "WARN: Config file not found: ${config_file}, using defaults" >&2
        return 0
    fi
    # Read each line, skip comments and blank lines, export as env vars
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "${key}" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${key}" ]] && continue
        # Trim whitespace from key and value
        key=$(echo "${key}" | xargs)
        value=$(echo "${value}" | xargs)
        # Export the variable so child processes can access it
        export "${key}=${value}"
    done < "${config_file}"
}

# Print the current configuration to stdout for debugging.
print_config() {
    echo "=== Detection Configuration ==="
    echo "  ZSCORE_WARNING_THRESHOLD=${ZSCORE_WARNING_THRESHOLD}"
    echo "  ZSCORE_CRITICAL_THRESHOLD=${ZSCORE_CRITICAL_THRESHOLD}"
    echo "  SEASONAL_DEVIATION_THRESHOLD=${SEASONAL_DEVIATION_THRESHOLD}"
    echo "  SEASONAL_MIN_SAMPLES=${SEASONAL_MIN_SAMPLES}"
    echo "  BASELINE_WINDOW_DAYS=${BASELINE_WINDOW_DAYS}"
    echo "  DATA_DIR=${DATA_DIR}"
    echo "  OUTPUT_DIR=${OUTPUT_DIR}"
    echo "  DASHBOARD_PORT=${DASHBOARD_PORT}"
    echo "==============================="
}
