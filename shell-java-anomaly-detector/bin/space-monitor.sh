#!/bin/bash
# =============================================================================
# space-monitor.sh — NAS space monitoring agent (shell-only)
#
# Lightweight version of the space_agent.sh from the Python server_space_optimizer.
# Scans directories, computes sizes, and outputs JSON results that the Java
# dashboard can display.
#
# Ported from: server_space_optimizer/agent/space_agent.sh
#
# Usage:
#   ./space-monitor.sh --mount /mnt/nas_prod --output output/space_scan.json
#   ./space-monitor.sh --config config/servers.conf
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

source "${SCRIPT_DIR}/lib/json_utils.sh"

# ---- Defaults ----
MOUNT_PATH=""
OUTPUT_FILE="${PROJECT_ROOT}/output/space_scan.json"
CONFIG_FILE=""
SERVER_NAME="$(hostname)"

# ---- Parse CLI arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mount)   MOUNT_PATH="$2"; shift 2 ;;
        --output)  OUTPUT_FILE="$2"; shift 2 ;;
        --config)  CONFIG_FILE="$2"; shift 2 ;;
        --server-name) SERVER_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 --mount <path> --output <path> [--server-name <name>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$(dirname "${OUTPUT_FILE}")"

# ---- Helper: get directory size in bytes ----
get_dir_size() {
    local dir="$1"
    du -sb "${dir}" 2>/dev/null | awk '{print $1}' || echo 0
}

# ---- Helper: count files ----
count_files() {
    find "$1" -type f 2>/dev/null | wc -l | tr -d ' '
}

# ---- Helper: count directories ----
count_dirs() {
    find "$1" -type d 2>/dev/null | wc -l | tr -d ' '
}

# ---- Helper: format bytes to human-readable ----
format_bytes() {
    local bytes=$1
    if [[ ${bytes} -ge 1073741824 ]]; then
        awk "BEGIN {printf \"%.2f GB\", ${bytes}/1073741824}"
    elif [[ ${bytes} -ge 1048576 ]]; then
        awk "BEGIN {printf \"%.2f MB\", ${bytes}/1048576}"
    elif [[ ${bytes} -ge 1024 ]]; then
        awk "BEGIN {printf \"%.2f KB\", ${bytes}/1024}"
    else
        echo "${bytes} B"
    fi
}

# ---- Scan a single directory and produce JSON ----
scan_directory() {
    local dir_path="$1"
    local app_name="$2"

    if [[ ! -d "${dir_path}" ]]; then
        echo "WARN: Directory not found: ${dir_path}" >&2
        return
    fi

    local size
    size=$(get_dir_size "${dir_path}")
    local files
    files=$(count_files "${dir_path}")
    local dirs
    dirs=$(count_dirs "${dir_path}")
    local size_human
    size_human=$(format_bytes "${size}")
    local scan_ts
    scan_ts=$(date -u '+%Y-%m-%dT%H:%M:%S')

    printf '{
  "server_name": "%s",
  "sub_app_name": "%s",
  "directory_path": "%s",
  "total_size_bytes": %s,
  "total_size_human": "%s",
  "file_count": %s,
  "dir_count": %s,
  "scan_timestamp": "%s"
}' "${SERVER_NAME}" "${app_name}" "${dir_path}" \
   "${size}" "${size_human}" "${files}" "${dirs}" "${scan_ts}"
}

echo "=== Space Monitoring Scan ==="

if [[ -n "${MOUNT_PATH}" ]]; then
    # Single directory scan
    echo "  Scanning: ${MOUNT_PATH}"
    scan_directory "${MOUNT_PATH}" "default" > "${OUTPUT_FILE}"
    echo "  Results saved to: ${OUTPUT_FILE}"
elif [[ -n "${CONFIG_FILE}" && -f "${CONFIG_FILE}" ]]; then
    # Multi-directory scan from config file
    echo "  Config: ${CONFIG_FILE}"
    # Config format: name=path (one per line)
    echo "[" > "${OUTPUT_FILE}"
    first=true
    while IFS='=' read -r name path; do
        [[ "${name}" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${name}" ]] && continue
        name=$(echo "${name}" | xargs)
        path=$(echo "${path}" | xargs)

        echo "  Scanning ${name}: ${path}"
        if [[ "${first}" == "true" ]]; then
            first=false
        else
            echo "," >> "${OUTPUT_FILE}"
        fi
        scan_directory "${path}" "${name}" >> "${OUTPUT_FILE}"
    done < "${CONFIG_FILE}"
    echo "" >> "${OUTPUT_FILE}"
    echo "]" >> "${OUTPUT_FILE}"
    echo "  Results saved to: ${OUTPUT_FILE}"
else
    echo "Error: Either --mount or --config is required"
    exit 1
fi

echo "=== Scan Complete ==="
