#!/bin/bash
# =============================================================================
# uninstall.sh — Remove the Volume Anomaly Detection system
#
# Stops services, removes installed files, and cleans up systemd entries.
#
# Usage:
#   sudo ./uninstall.sh
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/anomaly-detector"
SERVICE_NAME="anomaly-dashboard"

echo "============================================="
echo " Volume Anomaly Detection — Uninstaller"
echo "============================================="

# ---- Stop and remove systemd service ----
if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    echo "Stopping service: ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    echo "  Service removed"
else
    echo "No systemd service found (skipping)"
fi

# ---- Remove installed files ----
if [[ -d "${INSTALL_DIR}" ]]; then
    echo "Removing files from ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
    echo "  Files removed"
else
    echo "Install directory not found: ${INSTALL_DIR} (skipping)"
fi

echo ""
echo "Uninstallation complete."
echo "Note: Java (JDK) was NOT removed. Remove manually if no longer needed."
