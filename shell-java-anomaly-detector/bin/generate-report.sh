#!/bin/bash
# =============================================================================
# generate-report.sh — Generate incident insight reports from anomaly data
#
# Reads the detected anomalies JSON file, adds recommendations, and
# produces a consolidated incident report in both JSON and text formats.
#
# Ported from: src/agents/incident_insight.py (IncidentInsightAgent)
#              src/agents/recommendation_engine.py (RecommendationEngine)
#
# Usage:
#   ./generate-report.sh --anomalies output/anomalies.json \
#                        --output output/report.json \
#                        [--text output/report.txt]
# =============================================================================

set -euo pipefail

# Resolve the project root and source shared libraries
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

source "${SCRIPT_DIR}/lib/json_utils.sh"
source "${SCRIPT_DIR}/lib/recommendations.sh"

# ---- Parse CLI arguments ----
ANOMALIES_FILE=""
OUTPUT_FILE=""
TEXT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --anomalies) ANOMALIES_FILE="$2"; shift 2 ;;
        --output)    OUTPUT_FILE="$2"; shift 2 ;;
        --text)      TEXT_FILE="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 --anomalies <path> --output <path> [--text <path>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "${ANOMALIES_FILE}" ]]; then
    ANOMALIES_FILE="${PROJECT_ROOT}/output/anomalies.json"
fi
if [[ -z "${OUTPUT_FILE}" ]]; then
    OUTPUT_FILE="${PROJECT_ROOT}/output/report.json"
fi
if [[ -z "${TEXT_FILE}" ]]; then
    TEXT_FILE="${PROJECT_ROOT}/output/report.txt"
fi

mkdir -p "$(dirname "${OUTPUT_FILE}")"
mkdir -p "$(dirname "${TEXT_FILE}")"

echo "=== Generating Incident Report ==="
echo "  Anomalies input: ${ANOMALIES_FILE}"

# ---- Extract report metadata from anomalies using AWK ----
# Count anomalies by severity and collect unique services
report_data=$(awk '
BEGIN {
    critical = 0; high = 0; medium = 0; low = 0; total = 0
}
/"severity"/ {
    if (match($0, /"severity"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) {
        sev = m[1]
        total++
        if (sev == "CRITICAL") critical++
        else if (sev == "HIGH") high++
        else if (sev == "MEDIUM") medium++
        else low++
    }
}
/"service_name"/ {
    if (match($0, /"service_name"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) {
        services[m[1]] = 1
    }
}
/"anomaly_type"/ {
    if (match($0, /"anomaly_type"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) {
        types[m[1]] = 1
    }
}
END {
    # Count unique services
    svc_count = 0
    svc_list = ""
    for (s in services) {
        svc_count++
        if (svc_list != "") svc_list = svc_list "," s
        else svc_list = s
    }
    # Collect anomaly types
    type_list = ""
    for (t in types) {
        if (type_list != "") type_list = type_list "," t
        else type_list = t
    }
    printf "%d|%d|%d|%d|%d|%d|%s|%s\n", total, critical, high, medium, low, svc_count, svc_list, type_list
}
' "${ANOMALIES_FILE}")

# Parse the summary data
IFS='|' read -r total_anomalies critical high medium low svc_count svc_list type_list <<< "${report_data}"

echo "  Total anomalies: ${total_anomalies}"
echo "  CRITICAL: ${critical}, HIGH: ${high}, MEDIUM: ${medium}, LOW: ${low}"
echo "  Affected services: ${svc_count} (${svc_list})"

# ---- Build the summary text ----
summary="Detected ${total_anomalies} anomalies across ${svc_count} service(s)."
if [[ ${critical} -gt 0 ]]; then
    summary="${summary}\\n  - ${critical} CRITICAL severity anomaly/anomalies requiring immediate attention."
fi
if [[ ${high} -gt 0 ]]; then
    summary="${summary}\\n  - ${high} HIGH severity anomaly/anomalies."
fi

# ---- Collect all recommended actions based on anomaly types ----
all_actions=""
IFS=',' read -ra types_arr <<< "${type_list}"
for atype in "${types_arr[@]}"; do
    [[ -z "${atype}" ]] && continue
    while IFS= read -r action; do
        [[ -z "${action}" ]] && continue
        if [[ -z "${all_actions}" ]]; then
            all_actions="${action}"
        else
            # Avoid duplicates
            if ! echo "${all_actions}" | grep -qF "${action}"; then
                all_actions="${all_actions}|${action}"
            fi
        fi
    done < <(get_recommendations "${atype}" "HIGH")
done

# ---- Generate JSON report ----
report_id=$(generate_id "rpt")
generated_at=$(date -u '+%Y-%m-%dT%H:%M:%S')

# Build recommended_actions JSON array
actions_json="["
first_action=true
IFS='|' read -ra actions_list <<< "${all_actions}"
for action in "${actions_list[@]}"; do
    [[ -z "${action}" ]] && continue
    if [[ "${first_action}" == "true" ]]; then
        first_action=false
    else
        actions_json="${actions_json},"
    fi
    actions_json="${actions_json}\"$(json_escape "${action}")\""
done
actions_json="${actions_json}]"

# Build affected_services JSON array
services_json="["
first_svc=true
IFS=',' read -ra svcs <<< "${svc_list}"
for svc in "${svcs[@]}"; do
    [[ -z "${svc}" ]] && continue
    if [[ "${first_svc}" == "true" ]]; then
        first_svc=false
    else
        services_json="${services_json},"
    fi
    services_json="${services_json}\"${svc}\""
done
services_json="${services_json}]"

# Read the full anomalies array from the input file
anomalies_content=$(cat "${ANOMALIES_FILE}")

# Write the JSON report
cat > "${OUTPUT_FILE}" <<EOF
{
  "report_id": "${report_id}",
  "generated_at": "${generated_at}",
  "total_anomalies": ${total_anomalies},
  "critical_count": ${critical},
  "high_count": ${high},
  "medium_count": ${medium},
  "low_count": ${low},
  "affected_services": ${services_json},
  "summary": "$(echo "${summary}" | sed 's/"/\\"/g')",
  "recommended_actions": ${actions_json},
  "anomalies": ${anomalies_content}
}
EOF

echo "  JSON report saved to: ${OUTPUT_FILE}"

# ---- Generate human-readable text report ----
{
    # Determine severity header prefix
    severity_prefix=""
    if [[ ${critical} -gt 0 ]]; then
        severity_prefix="[CRITICAL]"
    elif [[ ${high} -gt 0 ]]; then
        severity_prefix="[HIGH]"
    fi

    echo "============================================="
    echo "${severity_prefix} Anomaly Report ${report_id}"
    echo "Generated: ${generated_at}"
    echo "============================================="
    echo ""
    echo -e "${summary}"
    echo ""

    # List each anomaly
    echo "--- Detected Anomalies ---"
    # Parse anomalies from JSON and print in text format
    awk '
    /"anomaly_id"/ {
        if (match($0, /"anomaly_id"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) id = m[1]
    }
    /"anomaly_type"/ {
        if (match($0, /"anomaly_type"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) atype = m[1]
    }
    /"severity"/ {
        if (match($0, /"severity"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) sev = m[1]
    }
    /"description"/ {
        if (match($0, /"description"[[:space:]]*:[[:space:]]*"([^"]+)"/, m)) {
            desc = m[1]
            printf "  [%s] %s - %s\n    %s\n\n", sev, atype, id, desc
        }
    }
    ' "${ANOMALIES_FILE}"

    # List recommended actions
    if [[ -n "${all_actions}" ]]; then
        echo "--- Recommended Actions ---"
        i=1
        IFS='|' read -ra act_list <<< "${all_actions}"
        for action in "${act_list[@]}"; do
            [[ -z "${action}" ]] && continue
            echo "  ${i}. ${action}"
            i=$((i + 1))
        done
    fi

    echo ""
    echo "============================================="
    echo "End of Report"
    echo "============================================="
} > "${TEXT_FILE}"

echo "  Text report saved to: ${TEXT_FILE}"
echo "=== Report Generation Complete ==="
