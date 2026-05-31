#!/bin/bash
# =============================================================================
# recommendations.sh — Knowledge-based recommendation engine
#
# Maps anomaly types and severities to corrective actions from a runbook.
# Ported from: src/agents/recommendation_engine.py (DEFAULT_RUNBOOK)
# =============================================================================

# Get recommended actions for a given anomaly type and severity.
# Outputs one action per line.
# Arguments: anomaly_type severity
# anomaly_type: volume_drop | volume_spike | latency_spike | error_rate_spike
# severity: LOW | MEDIUM | HIGH | CRITICAL
get_recommendations() {
    local anomaly_type="$1"
    local severity="$2"

    # Convert severity to numeric rank for threshold comparison
    local severity_rank
    severity_rank=$(severity_to_rank "${severity}")

    case "${anomaly_type}" in
        volume_drop)
            # Runbook: severity_threshold = HIGH (rank 2)
            if [[ ${severity_rank} -ge 2 ]]; then
                echo "Check upstream service health and connectivity"
                echo "Verify load balancer configuration"
                echo "Review recent deployment changes"
                echo "Check DNS resolution for dependent services"
            fi
            ;;
        volume_spike)
            # Runbook: severity_threshold = HIGH (rank 2)
            if [[ ${severity_rank} -ge 2 ]]; then
                echo "Check for retry storms from downstream services"
                echo "Verify rate limiting is active"
                echo "Review auto-scaling policies"
                echo "Check for batch job or cron job overlap"
            fi
            ;;
        latency_spike)
            # Runbook: severity_threshold = MEDIUM (rank 1)
            if [[ ${severity_rank} -ge 1 ]]; then
                echo "Check database connection pool utilization"
                echo "Review slow query logs"
                echo "Check for resource contention (CPU, memory, disk I/O)"
                echo "Verify cache hit rates"
            fi
            ;;
        error_rate_spike)
            # Runbook: severity_threshold = MEDIUM (rank 1)
            if [[ ${severity_rank} -ge 1 ]]; then
                echo "Review application error logs for root cause"
                echo "Check dependent service availability"
                echo "Verify configuration changes from recent deployments"
                echo "Check certificate expiration dates"
            fi
            ;;
    esac
}

# Convert severity string to numeric rank.
# Matches Python: LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3
# Arguments: severity_string
severity_to_rank() {
    case "$1" in
        LOW)      echo 0 ;;
        MEDIUM)   echo 1 ;;
        HIGH)     echo 2 ;;
        CRITICAL) echo 3 ;;
        *)        echo 0 ;;
    esac
}

# Get the runbook description for an anomaly type.
# Arguments: anomaly_type
get_runbook_description() {
    case "$1" in
        volume_drop)
            echo "Significant volume drop may indicate upstream failure or routing issue"
            ;;
        volume_spike)
            echo "Unexpected volume spike may indicate retry storms or misconfigured batch jobs"
            ;;
        latency_spike)
            echo "Latency increase often correlates with database or resource contention"
            ;;
        error_rate_spike)
            echo "Error rate spikes typically indicate dependency failures or bad deployments"
            ;;
        *)
            echo "Unknown anomaly type"
            ;;
    esac
}

# Build JSON array of recommendation objects for an anomaly.
# Arguments: anomaly_type severity [correlated_services...]
build_recommendations_json() {
    local anomaly_type="$1"
    local severity="$2"
    shift 2
    local correlated=("$@")

    local first=true
    local priority=1
    local confidence=0.8

    echo "["

    # Runbook-based recommendations
    while IFS= read -r action; do
        [[ -z "${action}" ]] && continue
        if [[ "${first}" == "true" ]]; then
            first=false
        else
            echo ","
        fi
        printf '  {"action": "%s", "confidence": %.1f, "source": "runbook", "priority": %d}' \
            "${action}" "${confidence}" "${priority}"
        confidence=$(awk "BEGIN { printf \"%.1f\", ${confidence} - 0.1 }")
        priority=$((priority + 1))
    done < <(get_recommendations "${anomaly_type}" "${severity}")

    # Correlation-based recommendations
    for svc in "${correlated[@]}"; do
        [[ -z "${svc}" ]] && continue
        if [[ "${first}" == "true" ]]; then
            first=false
        else
            echo ","
        fi
        printf '  {"action": "Investigate correlated service: %s", "confidence": 0.7, "source": "heuristic", "priority": 0}' \
            "${svc}"
    done

    echo ""
    echo "]"
}
