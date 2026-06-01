#!/bin/bash
# =============================================================================
# math_utils.sh — Statistical functions for anomaly detection
#
# Provides mean, standard deviation, z-score, and severity classification
# using AWK for floating-point arithmetic. All functions read from stdin
# or accept values as arguments.
#
# Ported from: src/detectors/zscore_detector.py, seasonal_detector.py
# =============================================================================

# Compute the arithmetic mean of a newline-separated list of numbers on stdin.
# Returns 0.0 if input is empty.
calc_mean() {
    awk '
    {
        sum += $1
        n++
    }
    END {
        if (n == 0) print 0.0
        else printf "%.6f\n", sum / n
    }'
}

# Compute the sample standard deviation (Bessel-corrected, N-1 denominator)
# of a newline-separated list of numbers on stdin.
# Returns 0.0 if fewer than 2 values are provided.
calc_std() {
    awk '
    {
        vals[NR] = $1
        sum += $1
        n++
    }
    END {
        if (n < 2) { print 0.0; exit }
        mean = sum / n
        ss = 0
        for (i = 1; i <= n; i++) {
            ss += (vals[i] - mean) * (vals[i] - mean)
        }
        printf "%.6f\n", sqrt(ss / (n - 1))
    }'
}

# Compute the z-score: (observed - mean) / std
# Arguments: observed_value mean std_dev
# Returns empty string if std is 0.
calc_zscore() {
    local observed="$1"
    local mean="$2"
    local std="$3"
    awk -v obs="${observed}" -v m="${mean}" -v s="${std}" \
        'BEGIN {
            if (s == 0) { print ""; exit }
            printf "%.6f\n", (obs - m) / s
        }'
}

# Return the absolute value of a number.
calc_abs() {
    local val="$1"
    awk -v v="${val}" 'BEGIN { printf "%.6f\n", (v < 0) ? -v : v }'
}

# Classify severity based on absolute z-score.
# Uses the same thresholds as Python ZScoreDetector._classify_severity:
#   abs_z >= critical * 2 → CRITICAL
#   abs_z >= critical     → HIGH
#   abs_z >= warning      → MEDIUM
#   else                  → LOW
# Arguments: abs_z warning_threshold critical_threshold
classify_severity_zscore() {
    local abs_z="$1"
    local warning="${2:-2.0}"
    local critical="${3:-3.0}"
    awk -v z="${abs_z}" -v w="${warning}" -v c="${critical}" \
        'BEGIN {
            if (z >= c * 2) print "CRITICAL"
            else if (z >= c) print "HIGH"
            else if (z >= w) print "MEDIUM"
            else print "LOW"
        }'
}

# Classify severity for seasonal detector.
# Uses the same thresholds as Python SeasonalDetector._classify_severity:
#   abs_z >= threshold * 2.5 → CRITICAL
#   abs_z >= threshold * 1.5 → HIGH
#   abs_z >= threshold       → MEDIUM
#   else                     → LOW
# Arguments: abs_z deviation_threshold
classify_severity_seasonal() {
    local abs_z="$1"
    local threshold="${2:-2.5}"
    awk -v z="${abs_z}" -v t="${threshold}" \
        'BEGIN {
            if (z >= t * 2.5) print "CRITICAL"
            else if (z >= t * 1.5) print "HIGH"
            else if (z >= t) print "MEDIUM"
            else print "LOW"
        }'
}

# Determine anomaly type based on z-score sign.
# Positive z → volume_spike, Negative z → volume_drop
# Arguments: z_score
get_anomaly_type() {
    local z="$1"
    awk -v z="${z}" \
        'BEGIN {
            if (z > 0) print "volume_spike"
            else print "volume_drop"
        }'
}
