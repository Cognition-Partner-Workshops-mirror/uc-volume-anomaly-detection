/**
 * Server Space Optimizer - Frontend JavaScript
 *
 * Handles API calls, dashboard rendering, chart creation,
 * purge report display, and growth prediction visualization.
 * Uses Chart.js (open-source) for all chart rendering.
 */

// ===========================================================
// Global state for chart instances (destroyed before re-render)
// ===========================================================
let serverPieChart = null;
let subappBarChart = null;
let trendChart = null;

// Cache for dashboard data used across pages
let cachedDashboardData = null;

// ===========================================================
// Utility: fetch JSON from API with error handling (GET)
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
// Utility: POST request to API with error handling
// ===========================================================
async function apiPost(url) {
    try {
        const response = await fetch(url, { method: 'POST' });
        if (!response.ok) {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API POST failed:', error);
        return null;
    }
}

// ===========================================================
// Format numbers with commas for display
// ===========================================================
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toLocaleString();
}

// ===========================================================
// Format datetime string to local display format
// ===========================================================
function formatDateTime(isoString) {
    if (!isoString) return 'Never';
    const date = new Date(isoString);
    return date.toLocaleString();
}

// ===========================================================
// Scan status polling - updates the navbar status badge
// ===========================================================
async function updateScanStatus() {
    const data = await apiFetch('/api/scan/status');
    const badge = document.getElementById('scan-status');
    if (!data || !badge) return;

    if (data.is_scanning) {
        badge.className = 'badge scanning';
        badge.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Scanning...';
    } else {
        badge.className = 'badge bg-secondary';
        const lastScan = data.last_scan_time
            ? formatDateTime(data.last_scan_time)
            : 'Never';
        badge.innerHTML = `<i class="bi bi-clock"></i> Last: ${lastScan}`;
    }
}

// ===========================================================
// Trigger a manual scan via the API
// ===========================================================
async function triggerScan(forceFull = false) {
    const btn = document.getElementById('btn-trigger-scan');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Starting...';
    }

    // Use POST method to match the backend endpoint
    const url = `/api/scan/trigger?force_full=${forceFull}`;
    const result = await apiPost(url);

    if (result && result.status === 'started') {
        // Poll for status updates while scanning
        const pollInterval = setInterval(async () => {
            await updateScanStatus();
            const status = await apiFetch('/api/scan/status');
            if (status && !status.is_scanning) {
                clearInterval(pollInterval);
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Scan Now';
                }
                // Refresh the current page data after scan completes
                refreshDashboard();
            }
        }, 5000);
    } else {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Scan Now';
        }
    }
}

// ===========================================================
// Dashboard page: load and render all dashboard data
// ===========================================================
async function refreshDashboard() {
    const data = await apiFetch('/api/dashboard');
    if (!data) return;

    cachedDashboardData = data;

    // Update summary cards
    updateElement('total-servers', formatNumber(data.total_servers));
    updateElement('total-sub-apps', formatNumber(data.total_sub_apps));
    updateElement('total-space', data.total_size_human);
    updateElement('total-files', formatNumber(data.total_file_count));
    updateElement('last-scan-time', formatDateTime(data.last_scan_time));

    // Render server cards with sub-app breakdown
    renderServerCards(data.servers);

    // Render charts
    renderServerPieChart(data.servers);
    renderSubAppBarChart(data.servers);

    // Update scan status
    updateScanStatus();
}

// ===========================================================
// Safely update an element's text content by ID
// ===========================================================
function updateElement(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ===========================================================
// Render server cards with sub-app space breakdown
// ===========================================================
function renderServerCards(servers) {
    const container = document.getElementById('server-cards');
    if (!container) return;

    if (!servers || servers.length === 0) {
        container.innerHTML = `
            <div class="col-12 text-center py-5">
                <i class="bi bi-inbox display-1 text-muted"></i>
                <p class="mt-2 text-muted">No server data available. Configure servers and run a scan.</p>
            </div>`;
        return;
    }

    let html = '';
    for (const server of servers) {
        // Build the sub-app list rows
        let subAppRows = '';
        const maxSize = Math.max(...server.sub_apps.map(s => s.total_size_bytes), 1);

        for (const subApp of server.sub_apps) {
            const pct = maxSize > 0 ? (subApp.total_size_bytes / maxSize * 100) : 0;
            // Color-code the progress bar based on relative size
            let barColor = 'bg-success';
            if (pct > 70) barColor = 'bg-danger';
            else if (pct > 40) barColor = 'bg-warning';

            subAppRows += `
                <div class="sub-app-item">
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between">
                            <span class="sub-app-name">${subApp.sub_app_name}</span>
                            <span class="sub-app-size">${subApp.total_size_human}</span>
                        </div>
                        <div class="sub-app-files">${formatNumber(subApp.file_count)} files | ${formatNumber(subApp.dir_count)} directories</div>
                        <div class="progress space-progress">
                            <div class="progress-bar ${barColor}" style="width: ${pct.toFixed(1)}%"></div>
                        </div>
                    </div>
                </div>`;
        }

        html += `
            <div class="col-md-6">
                <div class="card server-card">
                    <div class="card-header">
                        <h5><i class="bi bi-hdd-network"></i> ${server.server_name}</h5>
                        <div class="server-meta">
                            <span><i class="bi bi-globe"></i> ${server.server_host}</span> |
                            <span><i class="bi bi-folder2-open"></i> ${server.nas_mount_path}</span> |
                            <span><i class="bi bi-hdd"></i> Total: ${server.total_size_human}</span>
                        </div>
                    </div>
                    <div class="card-body">
                        ${subAppRows || '<p class="text-muted text-center">No sub-apps configured</p>'}
                    </div>
                    <div class="card-footer bg-white text-muted small">
                        <i class="bi bi-clock"></i> Last scan: ${formatDateTime(server.last_scan_time)}
                        | Type: ${server.scan_type}
                    </div>
                </div>
            </div>`;
    }

    container.innerHTML = html;
}

// ===========================================================
// Chart: Server space distribution pie chart
// ===========================================================
function renderServerPieChart(servers) {
    const canvas = document.getElementById('server-pie-chart');
    if (!canvas) return;

    // Destroy existing chart before re-creating
    if (serverPieChart) {
        serverPieChart.destroy();
    }

    const labels = servers.map(s => s.server_name);
    const sizes = servers.map(s => s.total_size_bytes);

    // Color palette for the pie chart segments
    const colors = [
        '#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6',
        '#1abc9c', '#e67e22', '#34495e', '#16a085', '#c0392b',
    ];

    serverPieChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: sizes,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const server = servers[context.dataIndex];
                            return `${server.server_name}: ${server.total_size_human}`;
                        },
                    },
                },
            },
        },
    });
}

// ===========================================================
// Chart: Sub-app space breakdown bar chart
// ===========================================================
function renderSubAppBarChart(servers) {
    const canvas = document.getElementById('subapp-bar-chart');
    if (!canvas) return;

    if (subappBarChart) {
        subappBarChart.destroy();
    }

    // Flatten all sub-apps across servers with server prefix
    const labels = [];
    const sizes = [];
    const bgColors = [];
    const colors = [
        '#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6',
        '#1abc9c', '#e67e22', '#34495e', '#16a085', '#c0392b',
    ];

    let colorIdx = 0;
    for (const server of servers) {
        for (const subApp of server.sub_apps) {
            labels.push(`${server.server_name} / ${subApp.sub_app_name}`);
            sizes.push(subApp.total_size_bytes);
            bgColors.push(colors[colorIdx % colors.length]);
            colorIdx++;
        }
    }

    subappBarChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Space Used (bytes)',
                data: sizes,
                backgroundColor: bgColors,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return formatSizeFromBytes(context.raw);
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        callback: function(value) {
                            return formatSizeFromBytes(value);
                        },
                    },
                },
            },
        },
    });
}

// ===========================================================
// Human-readable size formatting from bytes (client-side)
// ===========================================================
function formatSizeFromBytes(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(2)} ${units[i]}`;
}

// ===========================================================
// Populate server dropdowns on purge and prediction pages
// ===========================================================
async function populateServerDropdowns() {
    const data = cachedDashboardData || await apiFetch('/api/dashboard');
    if (!data) return;
    cachedDashboardData = data;

    // Populate all server select dropdowns on the page
    const selects = document.querySelectorAll(
        '#purge-server-select, #pred-server-select'
    );
    for (const select of selects) {
        // Clear existing options except the first placeholder
        while (select.options.length > 1) {
            select.remove(1);
        }
        for (const server of data.servers) {
            const option = document.createElement('option');
            option.value = server.server_name;
            option.textContent = `${server.server_name} (${server.server_host})`;
            select.appendChild(option);
        }
    }
}

// ===========================================================
// Purge page: load and display purge report
// ===========================================================
async function loadPurgeReport() {
    const serverSelect = document.getElementById('purge-server-select');
    const subappSelect = document.getElementById('purge-subapp-select');
    const thresholdSelect = document.getElementById('purge-threshold');

    if (!serverSelect || !serverSelect.value) return;

    const server = serverSelect.value;
    const subApp = subappSelect ? subappSelect.value : '';
    const threshold = thresholdSelect ? thresholdSelect.value : '365';

    let url = `/api/servers/${encodeURIComponent(server)}/purge?threshold_days=${threshold}`;
    if (subApp) {
        url += `&sub_app_name=${encodeURIComponent(subApp)}`;
    }

    const data = await apiFetch(url);
    if (!data) return;

    // Show the summary cards
    const summary = document.getElementById('purge-summary');
    if (summary) summary.style.display = 'flex';

    updateElement('purge-total-candidates', formatNumber(data.total_candidates));
    updateElement('purge-reclaimable-space', data.total_reclaimable_human);
    updateElement('purge-threshold-display', `${data.threshold_days} days`);

    // Populate the purge candidates table
    const tbody = document.getElementById('purge-table-body');
    if (!tbody) return;

    if (!data.candidates || data.candidates.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-muted py-4">
                    No purge candidates found for the selected criteria
                </td>
            </tr>`;
        return;
    }

    let html = '';
    data.candidates.forEach((candidate, idx) => {
        // Color-code the days stale column
        let staleClass = '';
        if (candidate.days_since_modified > 365) staleClass = 'stale-critical';
        else if (candidate.days_since_modified > 180) staleClass = 'stale-danger';
        else staleClass = 'stale-warning';

        html += `
            <tr>
                <td>${idx + 1}</td>
                <td class="file-path-cell" title="${candidate.file_path}">${candidate.file_path}</td>
                <td><strong>${candidate.file_size_human}</strong></td>
                <td>${candidate.sub_app_name}</td>
                <td>${formatDateTime(candidate.last_modified)}</td>
                <td>${formatDateTime(candidate.last_accessed)}</td>
                <td class="${staleClass}">${candidate.days_since_modified}d</td>
            </tr>`;
    });

    tbody.innerHTML = html;
}

// ===========================================================
// Export purge candidates table to CSV for download
// ===========================================================
function exportPurgeCsv() {
    const table = document.getElementById('purge-table');
    if (!table) return;

    let csv = '';
    const rows = table.querySelectorAll('tr');
    rows.forEach(row => {
        const cols = row.querySelectorAll('td, th');
        const rowData = Array.from(cols).map(col => {
            // Escape double quotes and wrap in quotes
            const text = col.textContent.trim().replace(/"/g, '""');
            return `"${text}"`;
        });
        csv += rowData.join(',') + '\n';
    });

    // Trigger download of the CSV file
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `purge_report_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
}

// ===========================================================
// Predictions page: handle server selection change
// ===========================================================
async function onPredServerChange() {
    const serverSelect = document.getElementById('pred-server-select');
    const subappSelect = document.getElementById('pred-subapp-select');
    if (!serverSelect || !serverSelect.value || !subappSelect) return;

    // Populate sub-app dropdown based on selected server
    const data = cachedDashboardData || await apiFetch('/api/dashboard');
    if (!data) return;

    // Clear existing sub-app options
    while (subappSelect.options.length > 1) {
        subappSelect.remove(1);
    }

    const server = data.servers.find(s => s.server_name === serverSelect.value);
    if (server) {
        for (const subApp of server.sub_apps) {
            const option = document.createElement('option');
            option.value = subApp.sub_app_name;
            option.textContent = subApp.sub_app_name;
            subappSelect.appendChild(option);
        }
    }
}

// ===========================================================
// Predictions page: load and render growth predictions
// ===========================================================
async function loadPredictions() {
    const serverSelect = document.getElementById('pred-server-select');
    const subappSelect = document.getElementById('pred-subapp-select');
    if (!serverSelect || !serverSelect.value) return;

    const server = serverSelect.value;
    const subApp = subappSelect ? subappSelect.value : '';

    let url = `/api/servers/${encodeURIComponent(server)}/predictions`;
    if (subApp) {
        url += `?sub_app_name=${encodeURIComponent(subApp)}`;
    }

    const data = await apiFetch(url);
    if (!data) return;

    if (subApp && data.predictions) {
        // Single sub-app prediction view
        renderSinglePrediction(data);
    } else if (data.predictions) {
        // All sub-apps prediction table
        renderAllPredictions(data);
    }
}

// ===========================================================
// Render prediction cards for a single sub-app
// ===========================================================
function renderSinglePrediction(data) {
    const cards = document.getElementById('prediction-cards');
    const chartContainer = document.getElementById('trend-chart-container');

    if (cards) cards.style.display = 'flex';
    if (chartContainer) chartContainer.style.display = 'block';

    // Map prediction periods to their UI elements
    const periodMap = {
        weekly: 'weekly',
        monthly: 'monthly',
        yearly: 'yearly',
    };

    for (const pred of data.predictions) {
        const key = periodMap[pred.period];
        if (!key) continue;

        updateElement(`pred-${key}-growth`, pred.predicted_growth_human);
        updateElement(`pred-${key}-rate`, `${pred.growth_rate_percent}%`);
        updateElement(`pred-${key}-total`, pred.predicted_total_human);
        updateElement(`pred-${key}-conf`, `${(pred.confidence * 100).toFixed(0)}%`);
        updateElement(`pred-${key}-dp`, pred.data_points_used);
    }

    // Render historical trend chart if data available
    if (data.historical_data && data.historical_data.length > 0) {
        renderTrendChart(data.historical_data, data.predictions);
    }
}

// ===========================================================
// Render prediction table for all sub-apps on a server
// ===========================================================
function renderAllPredictions(data) {
    const tableContainer = document.getElementById('prediction-table-container');
    const tbody = document.getElementById('prediction-table-body');
    if (!tableContainer || !tbody) return;

    tableContainer.style.display = 'block';

    let html = '';
    for (const report of data.predictions) {
        // Find each period's prediction
        const weekly = report.predictions.find(p => p.period === 'weekly') || {};
        const monthly = report.predictions.find(p => p.period === 'monthly') || {};
        const yearly = report.predictions.find(p => p.period === 'yearly') || {};

        html += `
            <tr>
                <td><strong>${report.sub_app_name}</strong></td>
                <td>${report.current_size_human}</td>
                <td>${weekly.predicted_growth_human || '--'}</td>
                <td>${monthly.predicted_growth_human || '--'}</td>
                <td>${yearly.predicted_growth_human || '--'}</td>
                <td>${weekly.growth_rate_percent || 0}%</td>
                <td>${monthly.growth_rate_percent || 0}%</td>
                <td>${yearly.growth_rate_percent || 0}%</td>
                <td>${((weekly.confidence || 0) * 100).toFixed(0)}%</td>
            </tr>`;
    }

    tbody.innerHTML = html || '<tr><td colspan="9" class="text-center text-muted">No prediction data available</td></tr>';
}

// ===========================================================
// Chart: Historical space usage trend with prediction overlay
// ===========================================================
function renderTrendChart(historicalData, predictions) {
    const canvas = document.getElementById('trend-chart');
    if (!canvas) return;

    if (trendChart) {
        trendChart.destroy();
    }

    // Build the historical data series
    const labels = historicalData.map(d => {
        const date = new Date(d.timestamp);
        return date.toLocaleDateString();
    });
    const sizes = historicalData.map(d => d.size_bytes);

    // Build prediction extension line (from last point forward)
    const lastSize = sizes[sizes.length - 1] || 0;
    const yearlyPred = predictions.find(p => p.period === 'yearly');
    const monthlyPred = predictions.find(p => p.period === 'monthly');

    // Add projected points for the next 3 months
    const projectedLabels = [];
    const projectedSizes = [];
    if (monthlyPred && monthlyPred.predicted_growth_bytes > 0) {
        const monthlyGrowth = monthlyPred.predicted_growth_bytes;
        for (let i = 1; i <= 3; i++) {
            const futureDate = new Date();
            futureDate.setMonth(futureDate.getMonth() + i);
            projectedLabels.push(futureDate.toLocaleDateString());
            projectedSizes.push(lastSize + monthlyGrowth * i);
        }
    }

    const allLabels = [...labels, ...projectedLabels];
    // Historical data padded with nulls for projected period
    const historicalSeries = [...sizes, ...new Array(projectedLabels.length).fill(null)];
    // Projected data starts from last historical point
    const projectedSeries = [
        ...new Array(labels.length - 1).fill(null),
        lastSize,
        ...projectedSizes,
    ];

    trendChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: allLabels,
            datasets: [
                {
                    label: 'Historical Usage',
                    data: historicalSeries,
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                },
                {
                    label: 'Projected Growth',
                    data: projectedSeries,
                    borderColor: '#e74c3c',
                    borderDash: [5, 5],
                    backgroundColor: 'rgba(231, 76, 60, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (context.raw === null) return '';
                            return `${context.dataset.label}: ${formatSizeFromBytes(context.raw)}`;
                        },
                    },
                },
            },
            scales: {
                y: {
                    ticks: {
                        callback: function(value) {
                            return formatSizeFromBytes(value);
                        },
                    },
                },
            },
        },
    });
}

// ===========================================================
// Initialize: poll scan status every 30 seconds
// ===========================================================
setInterval(updateScanStatus, 30000);
// Run initial status check
updateScanStatus();
