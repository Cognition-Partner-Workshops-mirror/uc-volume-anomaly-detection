#!/bin/bash
# =============================================================================
# build.sh — Compile the Java web dashboard
#
# Compiles all Java source files and packages them into a runnable JAR.
# Requires JDK 11+ (uses com.sun.net.httpserver which is built into the JDK).
#
# Usage:
#   cd webapp && ./build.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/src"
BUILD_DIR="${SCRIPT_DIR}/build"
CLASSES_DIR="${BUILD_DIR}/classes"
JAR_FILE="${BUILD_DIR}/AnomalyDashboard.jar"

echo "=== Building Java Anomaly Dashboard ==="

# Check for Java compiler
if ! command -v javac &>/dev/null; then
    echo "ERROR: javac not found. Please install JDK 11+ first."
    echo "  On Ubuntu/Debian: sudo apt-get install -y default-jdk"
    echo "  On RHEL/CentOS:   sudo yum install -y java-11-openjdk-devel"
    exit 1
fi

# Show Java version
echo "  Java compiler: $(javac -version 2>&1)"

# Clean and create build directories
rm -rf "${CLASSES_DIR}"
mkdir -p "${CLASSES_DIR}"

# Find all Java source files
JAVA_FILES=$(find "${SRC_DIR}" -name '*.java')
FILE_COUNT=$(echo "${JAVA_FILES}" | wc -l | tr -d ' ')
echo "  Compiling ${FILE_COUNT} Java source files..."

# Compile all Java files to the classes directory
javac -d "${CLASSES_DIR}" ${JAVA_FILES}

echo "  Compilation successful"

# Create the manifest file for the runnable JAR
MANIFEST="${BUILD_DIR}/MANIFEST.MF"
cat > "${MANIFEST}" <<EOF
Manifest-Version: 1.0
Main-Class: com.anomaly.AnomalyDashboard
EOF

# Package into a JAR file
echo "  Packaging JAR: ${JAR_FILE}"
jar cfm "${JAR_FILE}" "${MANIFEST}" -C "${CLASSES_DIR}" .

echo "  JAR size: $(du -h "${JAR_FILE}" | cut -f1)"
echo ""
echo "=== Build Complete ==="
echo ""
echo "Run the dashboard with:"
echo "  java -jar ${JAR_FILE} --port 8080 --data-dir output --web-dir webapp/web"
