#!/bin/bash
# =============================================================================
# csv_parser.sh — CSV parsing utilities for transaction data
#
# Reads the sample_transactions.csv file and extracts fields.
# The CSV format is:
#   timestamp,service_name,endpoint,count,error_count,avg_latency_ms,p99_latency_ms
#
# Ported from: src/agents/anomaly_detector.py (load_historical_data)
# =============================================================================

# Parse a CSV file and output tab-separated fields for shell processing.
# Skips the header row. Outputs:
#   timestamp\tservice_name\tendpoint\tcount\terror_count\tavg_latency_ms\tp99_latency_ms
# Arguments: csv_file_path
parse_transactions_csv() {
    local csv_file="$1"
    if [[ ! -f "${csv_file}" ]]; then
        echo "ERROR: CSV file not found: ${csv_file}" >&2
        return 1
    fi
    # Skip header, output tab-separated values
    awk -F',' 'NR > 1 {
        # Output: timestamp service_name endpoint count error_count avg_latency_ms p99_latency_ms
        printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", $1, $2, $3, $4, $5, $6, $7
    }' "${csv_file}"
}

# Extract hour-of-day from an ISO timestamp (e.g., "2026-01-15T09:00:00" → 9).
# Arguments: iso_timestamp
get_hour() {
    local ts="$1"
    # Extract the hour portion from ISO format YYYY-MM-DDTHH:MM:SS
    echo "${ts}" | awk -F'[T:]' '{ printf "%d\n", $2 }'
}

# Extract day-of-week (0=Mon..6=Sun) from an ISO timestamp.
# Uses the date command for accurate weekday computation.
# Arguments: iso_timestamp
get_day_of_week() {
    local ts="$1"
    # Convert ISO timestamp to epoch, then compute weekday (Python convention: 0=Mon)
    local date_part="${ts%%T*}"
    # date +%u returns 1=Monday..7=Sunday; we convert to 0=Monday..6=Sunday
    local dow
    dow=$(date -d "${date_part}" '+%u' 2>/dev/null)
    if [[ $? -ne 0 ]]; then
        echo "0"
        return
    fi
    echo $(( dow - 1 ))
}

# Build a service key from service_name and endpoint.
# Matches the Python format: "service_name/endpoint"
# Arguments: service_name endpoint
make_service_key() {
    echo "$1/$2"
}

# Count the number of unique service/endpoint combinations in a CSV file.
# Arguments: csv_file_path
count_series() {
    local csv_file="$1"
    awk -F',' 'NR > 1 { keys[$2"/"$3] = 1 } END { print length(keys) }' "${csv_file}"
}
