#!/bin/bash
# =============================================================================
# install.sh — Installation script for Volume Anomaly Detection (Shell/Java)
#
# Sets up the anomaly detection system on a Linux server without Python.
# Installs Java (OpenJDK) if not present, compiles the Java dashboard,
# and creates systemd service files for background operation.
#
# Usage:
#   chmod +x install.sh && sudo ./install.sh
#
# Or non-root (skips systemd service creation):
#   ./install.sh --no-service
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
INSTALL_DIR="/opt/anomaly-detector"
SERVICE_NAME="anomaly-dashboard"
NO_SERVICE=false

# ---- Parse arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-service) NO_SERVICE=true; shift ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--no-service] [--install-dir <path>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "============================================="
echo " Volume Anomaly Detection — Installer"
echo "============================================="
echo ""
echo "Install directory: ${INSTALL_DIR}"
echo ""

# ---- Step 1: Check/install Java ----
echo "[Step 1/5] Checking Java installation..."
if command -v java &>/dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1)
    echo "  Java found: ${JAVA_VERSION}"
else
    echo "  Java not found. Installing OpenJDK..."
    if command -v apt-get &>/dev/null; then
        # Debian/Ubuntu
        sudo apt-get update -qq
        sudo apt-get install -y default-jdk
    elif command -v yum &>/dev/null; then
        # RHEL/CentOS
        sudo yum install -y java-11-openjdk-devel
    elif command -v dnf &>/dev/null; then
        # Fedora
        sudo dnf install -y java-11-openjdk-devel
    else
        echo "ERROR: Could not determine package manager. Please install JDK 11+ manually."
        exit 1
    fi
    echo "  Java installed: $(java -version 2>&1 | head -1)"
fi

# Verify javac (compiler) is available
if ! command -v javac &>/dev/null; then
    echo "  WARNING: javac not found. Installing JDK development tools..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y default-jdk
    elif command -v yum &>/dev/null; then
        sudo yum install -y java-11-openjdk-devel
    fi
fi

# ---- Step 2: Check required shell tools ----
echo ""
echo "[Step 2/5] Checking required tools..."
MISSING_TOOLS=""
for tool in bash gawk date find du curl head wc; do
    if command -v "${tool}" &>/dev/null; then
        echo "  ${tool}: OK"
    else
        echo "  ${tool}: MISSING"
        MISSING_TOOLS="${MISSING_TOOLS} ${tool}"
    fi
done

if [[ -n "${MISSING_TOOLS}" ]]; then
    echo ""
    echo "Installing missing tools:${MISSING_TOOLS}..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y ${MISSING_TOOLS} 2>/dev/null || true
    elif command -v yum &>/dev/null; then
        sudo yum install -y ${MISSING_TOOLS} 2>/dev/null || true
    fi
fi

# ---- Step 3: Copy files to install directory ----
echo ""
echo "[Step 3/5] Installing files to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r "${SCRIPT_DIR}/bin" "${INSTALL_DIR}/"
cp -r "${SCRIPT_DIR}/webapp" "${INSTALL_DIR}/"
cp -r "${SCRIPT_DIR}/config" "${INSTALL_DIR}/"
cp -r "${SCRIPT_DIR}/data" "${INSTALL_DIR}/"
mkdir -p "${INSTALL_DIR}/output"

# Make shell scripts executable
chmod +x "${INSTALL_DIR}"/bin/*.sh
chmod +x "${INSTALL_DIR}"/bin/lib/*.sh
chmod +x "${INSTALL_DIR}"/webapp/build.sh

echo "  Files installed successfully"

# ---- Step 4: Build Java dashboard ----
echo ""
echo "[Step 4/5] Building Java dashboard..."
cd "${INSTALL_DIR}"
bash webapp/build.sh

# ---- Step 5: Create systemd service (optional) ----
if [[ "${NO_SERVICE}" == "false" ]] && [[ $(id -u) -eq 0 ]]; then
    echo ""
    echo "[Step 5/5] Creating systemd service..."

    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Volume Anomaly Detection Dashboard (Java)
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/java -jar ${INSTALL_DIR}/webapp/build/AnomalyDashboard.jar \
    --port 8080 \
    --data-dir ${INSTALL_DIR}/output \
    --baselines ${INSTALL_DIR}/data/baselines/baselines.json \
    --csv ${INSTALL_DIR}/data/historical/sample_transactions.csv \
    --web-dir ${INSTALL_DIR}/webapp/web
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    echo "  Service created: ${SERVICE_NAME}"
    echo "  Start with: sudo systemctl start ${SERVICE_NAME}"
    echo "  Enable on boot: sudo systemctl enable ${SERVICE_NAME}"
else
    echo ""
    echo "[Step 5/5] Skipping systemd service (non-root or --no-service)"
    echo "  Run manually:"
    echo "    cd ${INSTALL_DIR}"
    echo "    java -jar webapp/build/AnomalyDashboard.jar --port 8080 --data-dir output --web-dir webapp/web"
fi

echo ""
echo "============================================="
echo " Installation Complete"
echo "============================================="
echo ""
echo "Quick start:"
echo "  1. Run anomaly detection:"
echo "     ${INSTALL_DIR}/bin/anomaly-detector.sh --data ${INSTALL_DIR}/data/historical/sample_transactions.csv"
echo ""
echo "  2. Start web dashboard:"
echo "     java -jar ${INSTALL_DIR}/webapp/build/AnomalyDashboard.jar \\"
echo "       --port 8080 --data-dir ${INSTALL_DIR}/output \\"
echo "       --web-dir ${INSTALL_DIR}/webapp/web"
echo ""
echo "  3. Open browser: http://localhost:8080"
