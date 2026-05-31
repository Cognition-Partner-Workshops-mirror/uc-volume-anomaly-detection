/**
 * Volume Anomaly Detection Dashboard — Frontend JavaScript
 *
 * Handles API calls, dashboard rendering, chart creation,
 * anomaly/baseline table population, and report display.
 * Uses Chart.js (open-source) for all chart rendering.
 *
 * Ported from: server_space_optimizer/static/js/app.js
 */

// ===========================================================
// Global state for chart instances (destroyed before re-render)
// ===========================================================
let severityPieChart = null;
let typeBarChart = null;
let baselineLineChart = null;

// Cached dashboard data for cross-section use
let cachedData = null;

// ===========================================================
// Utility: fetch JSON from API with error handling
// ===========================================================
async function apiFetch(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API fetch failed:', error);
        return null;
    }
}

// ===========================================================
// Section navigation — show/hide dashboard sections
// ===========================================================
function showSection(sectionId) {
    // Hide all sections
    const sections = ['dashboard', 'anomalies', 'baselines', 'report'];
    sections.forEach(s => {
        const el = document.getElementById('section-' + s);
        if (el) el.style.display = 'none';
    });

    // Show the requested section
    const target = document.getElementById('section-' + sectionId);
    if (target) target.style.display = 'block';

    // Update nav link active state
    document.querySelectorAll('.navbar .nav-link').forEach(link => {
        link.classList.remove('active');
    });
    event.target.closest('.nav-link').classList.add('active');

    // Load section-specific data
    switch (sectionId) {
        case 'dashboard': loadDashboard(); break;
        case 'anomalies': loadAnomalies(); break;
        case 'baselines': loadBaselines(); break;
        case 'report':    loadReport(); break;
    }
}

// ===========================================================
// Dashboard: load summary data and render charts
// Ported from: refreshDashboard() in app.js (Python version)
// ===========================================================
async function loadDashboard() {
    const data = await apiFetch('/api/dashboard');
    if (!data) return;
    cachedData = data;

    // Update summary cards
    updateText('total-observations', data.total_observations || 0);
    updateText('total-baselines', data.total_baselines || 0);
    updateText('total-anomalies', data.total_anomalies || 0);
    updateText('critical-count', data.critical_count || 0);
    updateText('high-count', data.high_count || 0);

    // Render charts using the anomaly data
    renderSeverityPieChart(data.anomalies || []);
    renderTypeBarChart(data.anomalies || []);
    renderBaselineChart(data.baselines || []);
}

// ===========================================================
// Chart: Anomalies by Severity (pie chart)
// ===========================================================
function renderSeverityPieChart(anomalies) {
    // Count anomalies per severity level
    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    anomalies.forEach(a => {
        const sev = (a.severity || '').toUpperCase();
        if (sev in counts) counts[sev]++;
    });

    const ctx = document.getElementById('severity-pie-chart');
    if (!ctx) return;

    // Destroy previous chart instance to prevent canvas reuse errors
    if (severityPieChart) severityPieChart.destroy();

    severityPieChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Critical', 'High', 'Medium', 'Low'],
            datasets: [{
                data: [counts.CRITICAL, counts.HIGH, counts.MEDIUM, counts.LOW],
                backgroundColor: ['#e74c3c', '#f39c12', '#f1c40f', '#3498db'],
                borderWidth: 2,
                borderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'bottom' },
                title: { display: false }
            }
        }
    });
}

// ===========================================================
// Chart: Anomalies by Type (bar chart)
// ===========================================================
function renderTypeBarChart(anomalies) {
    // Count anomalies per type
    const counts = {};
    anomalies.forEach(a => {
        const t = a.anomaly_type || 'unknown';
        counts[t] = (counts[t] || 0) + 1;
    });

    const labels = Object.keys(counts);
    const values = Object.values(counts);

    // Map anomaly types to colors
    const colorMap = {
        'volume_spike': '#e74c3c',
        'volume_drop': '#3498db',
        'latency_spike': '#9b59b6',
        'error_rate_spike': '#f39c12'
    };
    const colors = labels.map(l => colorMap[l] || '#95a5a6');

    const ctx = document.getElementById('type-bar-chart');
    if (!ctx) return;

    if (typeBarChart) typeBarChart.destroy();

    typeBarChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels.map(l => l.replace(/_/g, ' ')),
            datasets: [{
                label: 'Count',
                data: values,
                backgroundColor: colors,
                borderRadius: 6,
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { stepSize: 1 } }
            }
        }
    });
}

// ===========================================================
// Chart: Baseline mean counts by hour (line chart)
// ===========================================================
function renderBaselineChart(baselines) {
    // Group baselines by service and plot mean_count by hour
    const series = {};
    baselines.forEach(b => {
        const key = b.service_name + '/' + b.endpoint;
        if (!series[key]) series[key] = {};
        series[key][b.hour_of_day] = b.mean_count;
    });

    const labels = Array.from({ length: 24 }, (_, i) => i + ':00');
    const datasets = [];
    const colors = ['#667eea', '#e74c3c', '#11998e', '#f39c12', '#9b59b6'];
    let colorIdx = 0;

    for (const [key, hourData] of Object.entries(series)) {
        const data = Array.from({ length: 24 }, (_, h) => hourData[h] || null);
        datasets.push({
            label: key,
            data: data,
            borderColor: colors[colorIdx % colors.length],
            backgroundColor: colors[colorIdx % colors.length] + '20',
            fill: true,
            tension: 0.3,
            pointRadius: 4
        });
        colorIdx++;
    }

    const ctx = document.getElementById('baseline-chart');
    if (!ctx) return;

    if (baselineLineChart) baselineLineChart.destroy();

    baselineLineChart = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            plugins: { legend: { position: 'bottom' } },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Mean Transaction Count' } },
                x: { title: { display: true, text: 'Hour of Day' } }
            }
        }
    });
}

// ===========================================================
// Anomalies table: load and render the detailed anomaly list
// ===========================================================
async function loadAnomalies() {
    const anomalies = await apiFetch('/api/anomalies');
    if (!anomalies) return;

    const tbody = document.getElementById('anomalies-tbody');
    if (!tbody) return;

    if (anomalies.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">No anomalies detected</td></tr>';
        return;
    }

    tbody.innerHTML = anomalies.map(a => {
        // Choose the CSS badge class based on severity
        const sevClass = 'badge-' + (a.severity || 'low').toLowerCase();
        // Choose type badge class
        let typeClass = 'badge-spike';
        if (a.anomaly_type === 'volume_drop') typeClass = 'badge-drop';
        if (a.anomaly_type === 'latency_spike') typeClass = 'badge-latency';

        return `<tr>
            <td><code>${a.anomaly_id || '--'}</code></td>
            <td><span class="${typeClass}">${(a.anomaly_type || '').replace(/_/g, ' ')}</span></td>
            <td><span class="${sevClass}">${a.severity || '--'}</span></td>
            <td>${a.service_name || '--'}</td>
            <td><code>${a.endpoint || '--'}</code></td>
            <td>${formatNumber(a.observed_value)}</td>
            <td>${formatNumber(a.expected_value)}</td>
            <td>${(a.deviation_score || 0).toFixed(2)}σ</td>
            <td>${a.detector || '--'}</td>
        </tr>`;
    }).join('');
}

// ===========================================================
// Baselines table: load and render the baseline data
// ===========================================================
async function loadBaselines() {
    const baselines = await apiFetch('/api/baselines');
    if (!baselines) return;

    const tbody = document.getElementById('baselines-tbody');
    if (!tbody) return;

    // Map day-of-week numbers to names
    const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    tbody.innerHTML = baselines.map(b => {
        return `<tr>
            <td>${b.service_name}</td>
            <td><code>${b.endpoint}</code></td>
            <td>${b.hour_of_day}:00</td>
            <td>${dayNames[b.day_of_week] || b.day_of_week}</td>
            <td>${formatNumber(b.mean_count)}</td>
            <td>${(b.std_count || 0).toFixed(2)}</td>
            <td>${(b.mean_latency_ms || 0).toFixed(1)}</td>
            <td>${b.sample_size || 0}</td>
        </tr>`;
    }).join('');
}

// ===========================================================
// Report: load and render the incident report
// ===========================================================
async function loadReport() {
    const report = await apiFetch('/api/report');
    if (!report) return;

    // Update report summary
    const summaryEl = document.getElementById('report-summary');
    if (summaryEl) {
        let html = `<p><strong>Report ID:</strong> ${report.report_id || '--'}</p>`;
        html += `<p><strong>Generated:</strong> ${report.generated_at || '--'}</p>`;
        html += `<p><strong>Total Anomalies:</strong> ${report.total_anomalies || 0} 
                   (Critical: ${report.critical_count || 0}, 
                    High: ${report.high_count || 0}, 
                    Medium: ${report.medium_count || 0}, 
                    Low: ${report.low_count || 0})</p>`;
        if (report.summary) {
            html += `<p><strong>Summary:</strong><br>${report.summary.replace(/\\n/g, '<br>')}</p>`;
        }
        summaryEl.innerHTML = html;
    }

    // Update recommended actions
    const actionsEl = document.getElementById('report-actions');
    if (actionsEl && report.recommended_actions) {
        actionsEl.innerHTML = report.recommended_actions.map(a =>
            `<li>${a}</li>`
        ).join('');
    }
}

// ===========================================================
// Utility: update text content of an element by ID
// ===========================================================
function updateText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ===========================================================
// Utility: format numbers with locale grouping
// ===========================================================
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    if (typeof num === 'number') {
        return num % 1 === 0 ? num.toLocaleString() : num.toFixed(2);
    }
    return String(num);
}

// ===========================================================
// Initialize: load dashboard data on page load
// ===========================================================
window.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
});
