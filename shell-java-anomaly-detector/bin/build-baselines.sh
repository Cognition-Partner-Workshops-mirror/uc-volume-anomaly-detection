#!/bin/bash
# =============================================================================
# build-baselines.sh — Build seasonal baselines from historical CSV data
#
# Groups transaction observations by (hour_of_day, day_of_week) and computes
# mean and standard deviation for each bucket. Outputs a JSON baselines file.
#
# Ported from: src/detectors/seasonal_detector.py (SeasonalDetector.build_baselines)
#
# Usage:
#   ./build-baselines.sh --csv data/historical/sample_transactions.csv \
#                        --output data/baselines/baselines.json \
#                        [--min-samples 4]
# =============================================================================

set -euo pipefail

# Resolve the project root and source shared libraries
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=lib/math_utils.sh
source "${SCRIPT_DIR}/lib/math_utils.sh"
# shellcheck source=lib/csv_parser.sh
source "${SCRIPT_DIR}/lib/csv_parser.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/json_utils.sh
source "${SCRIPT_DIR}/lib/json_utils.sh"

# ---- Parse CLI arguments ----
CSV_FILE=""
OUTPUT_FILE=""
MIN_SAMPLES="${SEASONAL_MIN_SAMPLES}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --csv)       CSV_FILE="$2"; shift 2 ;;
        --output)    OUTPUT_FILE="$2"; shift 2 ;;
        --min-samples) MIN_SAMPLES="$2"; shift 2 ;;
        --config)    load_detection_config "$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 --csv <path> --output <path> [--min-samples N] [--config <path>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "${CSV_FILE}" ]]; then
    echo "Error: --csv is required"
    exit 1
fi
if [[ -z "${OUTPUT_FILE}" ]]; then
    OUTPUT_FILE="${PROJECT_ROOT}/data/baselines/baselines.json"
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "=== Building Seasonal Baselines ==="
echo "  CSV input:    ${CSV_FILE}"
echo "  Output:       ${OUTPUT_FILE}"
echo "  Min samples:  ${MIN_SAMPLES}"

# ---- Main baseline computation using AWK ----
# This AWK script groups observations by (service, endpoint, hour, dow)
# and computes mean and sample standard deviation for count and latency.
awk -F',' -v min_samples="${MIN_SAMPLES}" '
BEGIN {
    OFS = "\t"
}
NR == 1 { next }  # Skip CSV header row
{
    # Parse fields from CSV
    timestamp = $1
    service = $2
    endpoint = $3
    count = $4 + 0
    error_count = $5 + 0
    avg_latency = $6 + 0.0
    p99_latency = $7 + 0.0

    # Extract hour from ISO timestamp (format: YYYY-MM-DDTHH:MM:SS)
    split(timestamp, ts_parts, "T")
    split(ts_parts[2], time_parts, ":")
    hour = time_parts[1] + 0

    # Extract day-of-week using date arithmetic
    # Parse date parts for Zeller-like formula
    split(ts_parts[1], date_parts, "-")
    y = date_parts[1] + 0
    m = date_parts[2] + 0
    d = date_parts[3] + 0

    # Tomohiko Sakamoto algorithm for day of week (0=Sunday..6=Saturday)
    # We convert to Python convention: 0=Monday..6=Sunday
    if (m < 3) { y--; m += 12 }
    # Zeller formula: h = (d + floor(13*(m+1)/5) + y + floor(y/4) - floor(y/100) + floor(y/400)) % 7
    # Returns 0=Saturday..6=Friday in Zeller; we use Sakamoto instead
    t_arr[1]=0; t_arr[2]=3; t_arr[3]=2; t_arr[4]=5; t_arr[5]=0; t_arr[6]=3
    t_arr[7]=5; t_arr[8]=1; t_arr[9]=6; t_arr[10]=4; t_arr[11]=2; t_arr[12]=4
    orig_m = (m > 12) ? m - 12 : m
    orig_y = (m > 12) ? y + 1 : y
    if (orig_m < 3) orig_y--
    dow_raw = (orig_y + int(orig_y/4) - int(orig_y/100) + int(orig_y/400) + t_arr[orig_m] + d) % 7
    # dow_raw: 0=Sunday..6=Saturday → convert to 0=Monday..6=Sunday
    dow = (dow_raw == 0) ? 6 : dow_raw - 1

    # Build composite key
    key = service "|" endpoint "|" hour "|" dow

    # Accumulate values for mean/std calculation
    n[key]++
    sum_count[key] += count
    sum_count2[key] += count * count
    sum_lat[key] += avg_latency
    sum_lat2[key] += avg_latency * avg_latency
}
END {
    # Output JSON array of baseline objects
    first = 1
    printf "[\n"
    for (key in n) {
        if (n[key] < min_samples) continue

        split(key, parts, "|")
        svc = parts[1]
        ep = parts[2]
        hr = parts[3] + 0
        dw = parts[4] + 0
        cnt = n[key]

        # Mean
        mean_c = sum_count[key] / cnt
        mean_l = sum_lat[key] / cnt

        # Sample standard deviation (N-1 denominator)
        if (cnt > 1) {
            var_c = (sum_count2[key] - sum_count[key] * sum_count[key] / cnt) / (cnt - 1)
            var_l = (sum_lat2[key] - sum_lat[key] * sum_lat[key] / cnt) / (cnt - 1)
            std_c = sqrt(var_c > 0 ? var_c : 0)
            std_l = sqrt(var_l > 0 ? var_l : 0)
        } else {
            std_c = 0
            std_l = 0
        }

        if (!first) printf ",\n"
        first = 0

        printf "  {\n"
        printf "    \"service_name\": \"%s\",\n", svc
        printf "    \"endpoint\": \"%s\",\n", ep
        printf "    \"hour_of_day\": %d,\n", hr
        printf "    \"day_of_week\": %d,\n", dw
        printf "    \"mean_count\": %.2f,\n", mean_c
        printf "    \"std_count\": %.2f,\n", std_c
        printf "    \"mean_latency_ms\": %.2f,\n", mean_l
        printf "    \"std_latency_ms\": %.2f,\n", std_l
        printf "    \"sample_size\": %d\n", cnt
        printf "  }"
    }
    printf "\n]\n"
}
' "${CSV_FILE}" > "${OUTPUT_FILE}"

# Count baselines generated
baseline_count=$(grep -c '"service_name"' "${OUTPUT_FILE}" 2>/dev/null || echo 0)
echo "  Generated ${baseline_count} baselines"
echo "  Baselines saved to: ${OUTPUT_FILE}"
echo "=== Baseline Build Complete ==="
