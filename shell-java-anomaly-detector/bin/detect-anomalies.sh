#!/bin/bash
# =============================================================================
# detect-anomalies.sh — Run anomaly detection against baselines
#
# Reads transaction observations from CSV, compares each against the
# seasonal baselines, and outputs detected anomalies as JSON.
# Implements both Z-score and seasonal detection algorithms.
#
# Ported from: src/agents/anomaly_detector.py (AnomalyDetectionAgent.analyze)
#              src/detectors/zscore_detector.py (ZScoreDetector.detect)
#              src/detectors/seasonal_detector.py (SeasonalDetector.detect)
#
# Usage:
#   ./detect-anomalies.sh --csv data/historical/sample_transactions.csv \
#                         --baselines data/baselines/baselines.json \
#                         --output output/anomalies.json \
#                         [--config config/detection_rules.conf]
# =============================================================================

set -euo pipefail

# Resolve the project root and source shared libraries
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

source "${SCRIPT_DIR}/lib/math_utils.sh"
source "${SCRIPT_DIR}/lib/csv_parser.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/json_utils.sh"
source "${SCRIPT_DIR}/lib/recommendations.sh"

# ---- Parse CLI arguments ----
CSV_FILE=""
BASELINES_FILE=""
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --csv)        CSV_FILE="$2"; shift 2 ;;
        --baselines)  BASELINES_FILE="$2"; shift 2 ;;
        --output)     OUTPUT_FILE="$2"; shift 2 ;;
        --config)     load_detection_config "$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 --csv <path> --baselines <path> --output <path> [--config <path>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "${CSV_FILE}" ]]; then
    echo "Error: --csv is required"; exit 1
fi
if [[ -z "${BASELINES_FILE}" ]]; then
    BASELINES_FILE="${PROJECT_ROOT}/data/baselines/baselines.json"
fi
if [[ -z "${OUTPUT_FILE}" ]]; then
    OUTPUT_FILE="${PROJECT_ROOT}/output/anomalies.json"
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "=== Anomaly Detection ==="
echo "  CSV input:      ${CSV_FILE}"
echo "  Baselines:      ${BASELINES_FILE}"
echo "  Output:         ${OUTPUT_FILE}"
echo "  Z-score warn:   ${ZSCORE_WARNING_THRESHOLD}"
echo "  Z-score crit:   ${ZSCORE_CRITICAL_THRESHOLD}"
echo "  Seasonal thresh: ${SEASONAL_DEVIATION_THRESHOLD}"

# ---- Main detection logic using AWK ----
# This single AWK script:
# 1. Reads the baselines JSON file (first pass)
# 2. Reads the CSV observations (second pass)
# 3. For each observation, looks up the matching baseline
# 4. Computes z-scores and checks thresholds
# 5. Outputs detected anomalies as JSON
gawk -F',' \
    -v warn="${ZSCORE_WARNING_THRESHOLD}" \
    -v crit="${ZSCORE_CRITICAL_THRESHOLD}" \
    -v seasonal_thresh="${SEASONAL_DEVIATION_THRESHOLD}" \
    -v baselines_file="${BASELINES_FILE}" \
'
# ---- Helper: classify z-score severity ----
function classify_zscore(abs_z) {
    if (abs_z >= crit * 2) return "CRITICAL"
    if (abs_z >= crit) return "HIGH"
    if (abs_z >= warn) return "MEDIUM"
    return "LOW"
}

# ---- Helper: classify seasonal severity ----
function classify_seasonal(abs_z) {
    if (abs_z >= seasonal_thresh * 2.5) return "CRITICAL"
    if (abs_z >= seasonal_thresh * 1.5) return "HIGH"
    if (abs_z >= seasonal_thresh) return "MEDIUM"
    return "LOW"
}

# ---- Helper: compute day-of-week from date parts (Sakamoto algorithm) ----
function compute_dow(yy, mm, dd,    t_arr) {
    split("0 3 2 5 0 3 5 1 6 4 2 4", t_arr, " ")
    if (mm < 3) yy--
    return (yy + int(yy/4) - int(yy/100) + int(yy/400) + t_arr[mm] + dd) % 7
}

# ---- Helper: generate a pseudo-random hex ID ----
function gen_id() {
    # Simple counter-based ID since we cannot read /dev/urandom in AWK
    _id_counter++
    return sprintf("anom-%04x%04x", _id_counter, NR)
}

BEGIN {
    _id_counter = 0
    anomaly_count = 0

    # ---- Parse baselines JSON file ----
    # Simple state-machine parser for the baselines JSON array.
    # Reads the JSON and extracts baseline records into associative arrays.
    baseline_idx = 0
    while ((getline line < baselines_file) > 0) {
        # Extract service_name
        if (match(line, /"service_name"[[:space:]]*:[[:space:]]*"([^"]+)"/, ma)) {
            bl_svc = ma[1]
        }
        if (match(line, /"endpoint"[[:space:]]*:[[:space:]]*"([^"]+)"/, ma)) {
            bl_ep = ma[1]
        }
        if (match(line, /"hour_of_day"[[:space:]]*:[[:space:]]*([0-9]+)/, ma)) {
            bl_hour = ma[1] + 0
        }
        if (match(line, /"day_of_week"[[:space:]]*:[[:space:]]*([0-9]+)/, ma)) {
            bl_dow = ma[1] + 0
        }
        if (match(line, /"mean_count"[[:space:]]*:[[:space:]]*([0-9.]+)/, ma)) {
            bl_mean_c = ma[1] + 0.0
        }
        if (match(line, /"std_count"[[:space:]]*:[[:space:]]*([0-9.]+)/, ma)) {
            bl_std_c = ma[1] + 0.0
        }
        if (match(line, /"mean_latency_ms"[[:space:]]*:[[:space:]]*([0-9.]+)/, ma)) {
            bl_mean_l = ma[1] + 0.0
        }
        if (match(line, /"std_latency_ms"[[:space:]]*:[[:space:]]*([0-9.]+)/, ma)) {
            bl_std_l = ma[1] + 0.0
        }
        if (match(line, /"sample_size"[[:space:]]*:[[:space:]]*([0-9]+)/, ma)) {
            bl_samples = ma[1] + 0
            # Store baseline keyed by service|endpoint|hour|dow
            bkey = bl_svc "|" bl_ep "|" bl_hour "|" bl_dow
            bl_mean_count[bkey] = bl_mean_c
            bl_std_count[bkey] = bl_std_c
            bl_mean_lat[bkey] = bl_mean_l
            bl_std_lat[bkey] = bl_std_l
            bl_sample_size[bkey] = bl_samples
            baseline_idx++
        }
    }
    close(baselines_file)
}

# ---- Process CSV observations (skip header) ----
NR == 1 { next }
{
    timestamp = $1
    service = $2
    endpoint = $3
    count = $4 + 0
    error_count = $5 + 0
    avg_latency = $6 + 0.0
    p99_latency = $7 + 0.0

    # Extract hour and day-of-week from timestamp
    split(timestamp, ts_parts, "T")
    split(ts_parts[2], time_parts, ":")
    hour = time_parts[1] + 0

    split(ts_parts[1], date_parts, "-")
    yr = date_parts[1] + 0
    mo = date_parts[2] + 0
    dy = date_parts[3] + 0
    dow_raw = compute_dow(yr, mo, dy)
    # Convert: 0=Sunday→6, 1=Monday→0, ..., 6=Saturday→5
    dow = (dow_raw == 0) ? 6 : dow_raw - 1

    # Look up matching baseline
    bkey = service "|" endpoint "|" hour "|" dow
    if (!(bkey in bl_mean_count)) next
    if (bl_std_count[bkey] == 0) next

    # ---- Z-Score volume detection ----
    z_score = (count - bl_mean_count[bkey]) / bl_std_count[bkey]
    abs_z = (z_score < 0) ? -z_score : z_score

    if (abs_z >= warn) {
        severity = classify_zscore(abs_z)
        atype = (z_score > 0) ? "volume_spike" : "volume_drop"
        direction = (z_score > 0) ? "above" : "below"
        desc = sprintf("%s/%s: volume %d is %.1f std devs %s expected %.0f (hour=%d, dow=%d)",
                       service, endpoint, count, abs_z, direction,
                       bl_mean_count[bkey], hour, dow)
        aid = gen_id()

        # Store anomaly for output
        anomaly_count++
        a_id[anomaly_count] = aid
        a_type[anomaly_count] = atype
        a_sev[anomaly_count] = severity
        a_svc[anomaly_count] = service
        a_ep[anomaly_count] = endpoint
        a_ts[anomaly_count] = timestamp
        a_obs[anomaly_count] = count
        a_exp[anomaly_count] = bl_mean_count[bkey]
        a_dev[anomaly_count] = abs_z
        a_desc[anomaly_count] = desc
        a_detector[anomaly_count] = "zscore"
    }

    # ---- Latency detection ----
    if (bl_std_lat[bkey] > 0) {
        lat_z = (avg_latency - bl_mean_lat[bkey]) / bl_std_lat[bkey]
        if (lat_z >= warn) {
            severity = classify_zscore(lat_z)
            desc = sprintf("%s/%s: latency %.0fms is %.1f std devs above expected %.0fms",
                           service, endpoint, avg_latency, lat_z, bl_mean_lat[bkey])
            aid = gen_id()

            anomaly_count++
            a_id[anomaly_count] = aid
            a_type[anomaly_count] = "latency_spike"
            a_sev[anomaly_count] = severity
            a_svc[anomaly_count] = service
            a_ep[anomaly_count] = endpoint
            a_ts[anomaly_count] = timestamp
            a_obs[anomaly_count] = avg_latency
            a_exp[anomaly_count] = bl_mean_lat[bkey]
            a_dev[anomaly_count] = lat_z
            a_desc[anomaly_count] = desc
            a_detector[anomaly_count] = "zscore_latency"
        }
    }

    # ---- Seasonal detection (separate threshold) ----
    seas_z = (count - bl_mean_count[bkey]) / bl_std_count[bkey]
    abs_seas = (seas_z < 0) ? -seas_z : seas_z

    if (abs_seas >= seasonal_thresh) {
        severity = classify_seasonal(abs_seas)
        atype = (seas_z > 0) ? "volume_spike" : "volume_drop"
        direction = (seas_z > 0) ? "above" : "below"
        desc = sprintf("Seasonal anomaly: %s/%s volume=%d is %.1f sigma %s seasonal baseline=%.0f (hour=%d, day=%d, samples=%d)",
                       service, endpoint, count, abs_seas, direction,
                       bl_mean_count[bkey], hour, dow, bl_sample_size[bkey])
        aid = gen_id()

        anomaly_count++
        a_id[anomaly_count] = aid
        a_type[anomaly_count] = atype
        a_sev[anomaly_count] = severity
        a_svc[anomaly_count] = service
        a_ep[anomaly_count] = endpoint
        a_ts[anomaly_count] = timestamp
        a_obs[anomaly_count] = count
        a_exp[anomaly_count] = bl_mean_count[bkey]
        a_dev[anomaly_count] = abs_seas
        a_desc[anomaly_count] = desc
        a_detector[anomaly_count] = "seasonal"
    }
}

END {
    # Output all detected anomalies as a JSON array
    printf "[\n"
    for (i = 1; i <= anomaly_count; i++) {
        if (i > 1) printf ",\n"
        printf "  {\n"
        printf "    \"anomaly_id\": \"%s\",\n", a_id[i]
        printf "    \"anomaly_type\": \"%s\",\n", a_type[i]
        printf "    \"severity\": \"%s\",\n", a_sev[i]
        printf "    \"service_name\": \"%s\",\n", a_svc[i]
        printf "    \"endpoint\": \"%s\",\n", a_ep[i]
        printf "    \"detected_at\": \"%s\",\n", a_ts[i]
        printf "    \"observed_value\": %.2f,\n", a_obs[i]
        printf "    \"expected_value\": %.2f,\n", a_exp[i]
        printf "    \"deviation_score\": %.4f,\n", a_dev[i]
        printf "    \"detector\": \"%s\",\n", a_detector[i]
        printf "    \"description\": \"%s\"\n", a_desc[i]
        printf "  }"
    }
    printf "\n]\n"

    # Print summary to stderr
    printf "Detected %d anomalies\n", anomaly_count > "/dev/stderr"
}
' "${CSV_FILE}" > "${OUTPUT_FILE}"

anomaly_count=$(grep -c '"anomaly_id"' "${OUTPUT_FILE}" 2>/dev/null || echo 0)
echo "  Detected ${anomaly_count} anomalies"
echo "  Results saved to: ${OUTPUT_FILE}"
echo "=== Detection Complete ==="
