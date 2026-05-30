#!/bin/bash
# =============================================================================
# Server Space Optimizer - Linux Shell Agent
#
# Lightweight NAS space scanner that runs on any Linux/Unix server without
# requiring Python, Java, or any runtime beyond standard POSIX tools.
# Uses: du, find, stat, curl, awk, date
#
# Reports scan metrics as JSON to the central dashboard via REST API (POST).
# Compatible with any backend: FastAPI, Tomcat, Spring Boot, Node.js, etc.
#
# Usage:
#   chmod +x space_agent.sh
#   ./space_agent.sh --config /path/to/agent.conf
#
# Configuration file (agent.conf) format:
#   SERVER_URL=http://dashboard-host:8080
#   SERVER_NAME=prod-server-1
#   SERVER_HOST=192.168.1.10
#   NAS_MOUNT=/mnt/nas_prod
#   SCAN_INTERVAL=60          # minutes between scans
#   SUB_APPS="billing:billing/data,logging:logs,archive:/mnt/archive:dedicated"
#
# Sub-app format: name:path[,name:path:dedicated]
#   - name:path         -> relative to NAS_MOUNT
#   - name:path:dedicated -> absolute path (dedicated mount)
#
# Can also be installed as a cron job or systemd timer:
#   */60 * * * * /opt/space_agent/space_agent.sh --config /opt/space_agent/agent.conf --once
#
# Or deployed as a Tomcat-compatible WAR by wrapping in a servlet that
# shells out to this script and forwards the JSON output.
# =============================================================================

set -euo pipefail

# Defaults
CONFIG_FILE=""
RUN_ONCE=false
LOG_FILE="/var/log/space_agent.log"
MAX_FILES_REPORT=5000

# ---- Logging helper ----
log() {
    local level="$1"
    shift
    local msg="$*"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "${ts} [space-agent] ${level} - ${msg}" | tee -a "${LOG_FILE}" 2>/dev/null || echo "${ts} [space-agent] ${level} - ${msg}"
}

# ---- Parse CLI arguments ----
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            --once)
                RUN_ONCE=true
                shift
                ;;
            --log)
                LOG_FILE="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: $0 --config <path> [--once] [--log <path>]"
                echo ""
                echo "Options:"
                echo "  --config <path>  Path to agent configuration file"
                echo "  --once           Run a single scan and exit (for cron use)"
                echo "  --log <path>     Log file path (default: /var/log/space_agent.log)"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    if [[ -z "${CONFIG_FILE}" ]]; then
        echo "Error: --config is required"
        exit 1
    fi
}

# ---- Load configuration from file ----
load_config() {
    if [[ ! -f "${CONFIG_FILE}" ]]; then
        log "ERROR" "Config file not found: ${CONFIG_FILE}"
        exit 1
    fi
    # Source the config file (key=value format)
    # shellcheck disable=SC1090
    source "${CONFIG_FILE}"

    # Validate required fields
    : "${SERVER_URL:?SERVER_URL is required in config}"
    : "${SERVER_NAME:?SERVER_NAME is required in config}"
    : "${NAS_MOUNT:?NAS_MOUNT is required in config}"

    # Apply defaults
    SERVER_HOST="${SERVER_HOST:-$(hostname)}"
    SCAN_INTERVAL="${SCAN_INTERVAL:-60}"
    SUB_APPS="${SUB_APPS:-}"
    # Default excluded system mounts if not configured
    EXCLUDED_MOUNTS="${EXCLUDED_MOUNTS:-/var,/opt,/home,/optware,/tmp,/etc,/boot,/proc,/sys,/dev,/run}"
}

# ---- Check if a path falls under any excluded mount ----
is_excluded_path() {
    local check_path="$1"
    local IFS=','
    for excluded in ${EXCLUDED_MOUNTS}; do
        # Strip whitespace
        excluded="$(echo "${excluded}" | xargs)"
        if [[ "${check_path}" == "${excluded}"* ]]; then
            log "DEBUG" "Path excluded: ${check_path} (matches ${excluded})"
            return 0
        fi
    done
    return 1
}

# ---- Get total size of a directory in bytes ----
get_dir_size_bytes() {
    local dir_path="$1"
    # Use du -sb for total byte count; fall back to du -sk * 1024
    if du -sb "${dir_path}" 2>/dev/null | awk '{print $1}'; then
        return
    fi
    # Fallback for systems without -b flag (e.g., macOS)
    echo $(( $(du -sk "${dir_path}" 2>/dev/null | awk '{print $1}') * 1024 ))
}

# ---- Count files in a directory ----
get_file_count() {
    local dir_path="$1"
    find "${dir_path}" -type f 2>/dev/null | wc -l | tr -d ' '
}

# ---- Count directories ----
get_dir_count() {
    local dir_path="$1"
    find "${dir_path}" -type d 2>/dev/null | wc -l | tr -d ' '
}

# ---- Format bytes to human-readable size ----
format_size() {
    local bytes=$1
    if [[ ${bytes} -ge 1099511627776 ]]; then
        awk "BEGIN {printf \"%.2f TB\", ${bytes}/1099511627776}"
    elif [[ ${bytes} -ge 1073741824 ]]; then
        awk "BEGIN {printf \"%.2f GB\", ${bytes}/1073741824}"
    elif [[ ${bytes} -ge 1048576 ]]; then
        awk "BEGIN {printf \"%.2f MB\", ${bytes}/1048576}"
    elif [[ ${bytes} -ge 1024 ]]; then
        awk "BEGIN {printf \"%.2f KB\", ${bytes}/1024}"
    else
        echo "${bytes} B"
    fi
}

# ---- Build JSON file list for a sub-app (largest files first) ----
build_file_list_json() {
    local dir_path="$1"
    local max_files="${2:-${MAX_FILES_REPORT}}"
    local first=true

    echo "["

    # Find files, get stat info, sort by size descending, limit count
    # stat format: size_bytes|mtime_epoch|atime_epoch|path
    find "${dir_path}" -type f -print0 2>/dev/null | \
        xargs -0 stat --format='%s|%Y|%X|%n' 2>/dev/null | \
        sort -t'|' -k1 -rn | \
        head -n "${max_files}" | \
    while IFS='|' read -r size_bytes mtime atime filepath; do
        # Convert epoch timestamps to ISO format
        local mtime_iso
        local atime_iso
        mtime_iso=$(date -u -d "@${mtime}" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "1970-01-01T00:00:00")
        atime_iso=$(date -u -d "@${atime}" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "1970-01-01T00:00:00")

        if [ "${first}" = true ]; then
            first=false
        else
            echo ","
        fi

        # Escape backslashes and double quotes in file path for valid JSON
        local safe_path
        safe_path=$(echo "${filepath}" | sed 's/\\/\\\\/g; s/"/\\"/g')

        printf '{"path":"%s","size_bytes":%s,"last_modified":"%s","last_accessed":"%s","created_at":"%s"}' \
            "${safe_path}" "${size_bytes}" "${mtime_iso}" "${atime_iso}" "${mtime_iso}"
    done

    echo "]"
}

# ---- Scan a single sub-app and POST results ----
scan_sub_app() {
    local app_name="$1"
    local app_path="$2"
    local report_url="${SERVER_URL}/api/agent/report"

    if [[ ! -d "${app_path}" ]]; then
        log "WARN" "Directory not found: ${app_name} (${app_path})"
        return 1
    fi

    log "INFO" "Scanning sub-app=${app_name} path=${app_path}"

    # Gather metrics using standard Unix tools
    local total_size
    total_size=$(get_dir_size_bytes "${app_path}")
    local file_count
    file_count=$(get_file_count "${app_path}")
    local dir_count
    dir_count=$(get_dir_count "${app_path}")
    local scan_ts
    scan_ts=$(date -u '+%Y-%m-%dT%H:%M:%S')

    log "INFO" "Sub-app ${app_name}: ${file_count} files, $(format_size "${total_size}")"

    # Build the file list JSON (largest files for purge analysis)
    local files_json
    files_json=$(build_file_list_json "${app_path}" "${MAX_FILES_REPORT}")

    # Construct JSON payload
    local json_payload
    json_payload=$(cat <<EOF
{
    "server_name": "${SERVER_NAME}",
    "server_host": "${SERVER_HOST}",
    "sub_app_name": "${app_name}",
    "directory_path": "${app_path}",
    "total_size_bytes": ${total_size},
    "file_count": ${file_count},
    "dir_count": ${dir_count},
    "scan_timestamp": "${scan_ts}",
    "scan_type": "shell_agent",
    "errors": [],
    "files": ${files_json}
}
EOF
    )

    # POST to the central dashboard API via curl
    local http_code
    http_code=$(curl -s -o /dev/null -w '%{http_code}' \
        -X POST \
        -H "Content-Type: application/json" \
        -d "${json_payload}" \
        --connect-timeout 30 \
        --max-time 120 \
        "${report_url}" 2>/dev/null) || true

    if [[ "${http_code}" == "200" || "${http_code}" == "201" ]]; then
        log "INFO" "Report accepted for ${app_name} (HTTP ${http_code})"
    else
        log "ERROR" "Failed to report ${app_name} (HTTP ${http_code})"
    fi
}

# ---- Parse SUB_APPS string and scan each one ----
scan_all_sub_apps() {
    log "INFO" "Starting scan cycle: server=${SERVER_NAME} (${SERVER_HOST})"
    local scan_start
    scan_start=$(date +%s)

    # Check if NAS_MOUNT itself is under an excluded system path
    if is_excluded_path "${NAS_MOUNT}"; then
        log "WARN" "NAS_MOUNT ${NAS_MOUNT} is under an excluded path; skipping scan"
        return
    fi

    if [[ -z "${SUB_APPS}" ]]; then
        # No sub-apps configured; scan entire NAS mount as one entry
        scan_sub_app "default" "${NAS_MOUNT}"
    else
        # Parse comma-separated sub-app definitions
        IFS=',' read -ra APP_LIST <<< "${SUB_APPS}"
        for app_def in "${APP_LIST[@]}"; do
            IFS=':' read -ra parts <<< "${app_def}"
            local app_name="${parts[0]}"
            local app_path="${parts[1]:-${app_name}}"
            local app_type="${parts[2]:-relative}"

            local resolved_path
            if [[ "${app_type}" == "dedicated" ]]; then
                resolved_path="${app_path}"
            else
                resolved_path="${NAS_MOUNT}/${app_path}"
            fi

            # Skip paths under excluded system mounts
            if is_excluded_path "${resolved_path}"; then
                log "WARN" "Skipping excluded sub-app path: ${resolved_path}"
                continue
            fi

            scan_sub_app "${app_name}" "${resolved_path}"
        done
    fi

    local scan_end
    scan_end=$(date +%s)
    local duration=$(( scan_end - scan_start ))
    log "INFO" "Scan cycle complete in ${duration}s"
}

# ---- Health check against central server ----
health_check() {
    local health_url="${SERVER_URL}/health"
    local result
    result=$(curl -s --connect-timeout 10 "${health_url}" 2>/dev/null) || true

    if echo "${result}" | grep -q '"status"'; then
        log "INFO" "Dashboard server reachable: ${SERVER_URL}"
        return 0
    else
        log "WARN" "Dashboard server unreachable: ${SERVER_URL}"
        return 1
    fi
}

# ---- Main entry point ----
main() {
    parse_args "$@"
    load_config

    log "INFO" "Agent started: server=${SERVER_NAME}, host=${SERVER_HOST}, mount=${NAS_MOUNT}, interval=${SCAN_INTERVAL}m"

    # Initial health check
    health_check || true

    if [[ "${RUN_ONCE}" == true ]]; then
        # Single scan mode (for cron jobs)
        scan_all_sub_apps
        log "INFO" "Single scan complete, exiting"
        exit 0
    fi

    # Continuous daemon mode
    while true; do
        scan_all_sub_apps
        log "INFO" "Sleeping ${SCAN_INTERVAL} minutes until next scan..."
        sleep $(( SCAN_INTERVAL * 60 ))
    done
}

main "$@"
