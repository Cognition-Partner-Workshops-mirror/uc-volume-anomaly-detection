#!/bin/bash
# =============================================================================
# json_utils.sh — JSON output helpers for shell scripts
#
# Since jq may not be available, these functions build JSON strings
# using printf and awk. All output is valid JSON.
# =============================================================================

# Escape a string for safe inclusion in a JSON value.
# Handles backslashes, double quotes, and control characters.
# Arguments: raw_string
json_escape() {
    local str="$1"
    # Escape backslashes first, then double quotes, then control chars
    echo "${str}" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g'
}

# Generate a UUID-like identifier (8 hex chars) for anomaly IDs.
# Uses /dev/urandom for randomness.
generate_id() {
    local prefix="${1:-anom}"
    local hex
    hex=$(head -c 4 /dev/urandom | od -A n -t x1 | tr -d ' \n')
    echo "${prefix}-${hex}"
}

# Build a JSON anomaly event object.
# Arguments: anomaly_id type severity service endpoint observed expected
#            deviation description
build_anomaly_json() {
    local id="$1"
    local atype="$2"
    local severity="$3"
    local service="$4"
    local endpoint="$5"
    local observed="$6"
    local expected="$7"
    local deviation="$8"
    local description="$9"
    local detected_at
    detected_at=$(date -u '+%Y-%m-%dT%H:%M:%S')

    # Escape the description for JSON safety
    description=$(json_escape "${description}")

    printf '{
  "anomaly_id": "%s",
  "anomaly_type": "%s",
  "severity": "%s",
  "service_name": "%s",
  "endpoint": "%s",
  "detected_at": "%s",
  "observed_value": %s,
  "expected_value": %.2f,
  "deviation_score": %.4f,
  "description": "%s",
  "correlated_services": [],
  "recommended_actions": []
}\n' "${id}" "${atype}" "${severity}" "${service}" "${endpoint}" \
   "${detected_at}" "${observed}" "${expected}" "${deviation}" "${description}"
}

# Build a JSON baseline object.
# Arguments: service endpoint hour dow mean_count std_count mean_latency std_latency sample_size
build_baseline_json() {
    printf '{
  "service_name": "%s",
  "endpoint": "%s",
  "hour_of_day": %d,
  "day_of_week": %d,
  "mean_count": %.2f,
  "std_count": %.2f,
  "mean_latency_ms": %.2f,
  "std_latency_ms": %.2f,
  "sample_size": %d
}\n' "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"
}

# Wrap an array of JSON objects (one per line) into a JSON array.
# Reads JSON objects from stdin, outputs a valid JSON array.
wrap_json_array() {
    awk '
    BEGIN { printf "[" }
    NR > 1 { printf "," }
    { printf "\n  %s", $0 }
    END { printf "\n]\n" }
    '
}

# Build a JSON report object.
# Arguments: report_id time_start time_end summary anomalies_file
build_report_json() {
    local report_id="$1"
    local time_start="$2"
    local time_end="$3"
    local summary="$4"
    local anomalies_file="$5"
    local generated_at
    generated_at=$(date -u '+%Y-%m-%dT%H:%M:%S')

    summary=$(json_escape "${summary}")

    local anomalies_json="[]"
    if [[ -f "${anomalies_file}" ]]; then
        anomalies_json=$(cat "${anomalies_file}")
    fi

    printf '{
  "report_id": "%s",
  "generated_at": "%s",
  "time_window_start": "%s",
  "time_window_end": "%s",
  "summary": "%s",
  "anomalies": %s,
  "recommended_actions": []
}\n' "${report_id}" "${generated_at}" "${time_start}" "${time_end}" \
   "${summary}" "${anomalies_json}"
}
