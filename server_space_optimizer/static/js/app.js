/**
 * Server Space Optimizer - Frontend JavaScript
 *
 * Handles API calls, dashboard rendering, chart creation,
 * purge report display, and growth prediction visualization.
 * Uses Chart.js (open-source) for all chart rendering.
 * Supports forecasting: 1 week, 1 month, 1 year, and 5 years.
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
// Trigger a manual scan via the API (POST method)
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

    // Build server filter checkboxes (defined in dashboard.html)
    if (typeof buildServerFilterCheckboxes === 'function') {
        buildServerFilterCheckboxes(data.servers);
    }

    // Render charts BEFORE server cards (aggregate stats first)
    renderServerPieChart(data.servers);
    renderSubAppBarChart(data.servers);

    // Render server cards with sub-app breakdown
    renderServerCards(data.servers);

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
// Chart: Server space distribution pie chart (gradient palette)
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

    // Modern gradient-inspired color palette
    const colors = [
        '#667eea', '#38ef7d', '#e74c3c', '#f2994a', '#9b59b6',
        '#2193b0', '#f2c94c', '#11998e', '#764ba2', '#c0392b',
    ];

    serverPieChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: sizes,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 3,
                borderColor: '#fff',
                hoverOffset: 8,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '55%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: { font: { weight: '600' }, padding: 15 },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    titleFont: { weight: '700' },
                    bodyFont: { weight: '500' },
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            const server = servers[context.dataIndex];
                            return ` ${server.server_name}: ${server.total_size_human}`;
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
        '#667eea', '#38ef7d', '#e74c3c', '#f2994a', '#9b59b6',
        '#2193b0', '#f2c94c', '#11998e', '#764ba2', '#c0392b',
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
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            return ` ${formatSizeFromBytes(context.raw)}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: {
                        callback: function(value) {
                            return formatSizeFromBytes(value);
                        },
                    },
                },
                y: {
                    grid: { display: false },
                    ticks: { font: { weight: '600' } },
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
// Populate server dropdowns on purge and prediction pages.
// Uses /api/config/servers to include DB-added servers (not just YAML).
// ===========================================================
async function populateServerDropdowns() {
    // Fetch ALL known servers from the config/servers API which merges
    // both YAML-configured and DB-added (Settings UI) servers
    const serverData = await apiFetch('/api/config/servers');
    const serverNames = serverData ? serverData.servers : [];

    // Also fetch dashboard data for host info (used as display label)
    const data = cachedDashboardData || await apiFetch('/api/dashboard');
    if (data) cachedDashboardData = data;

    // Build a lookup map of server_name -> server_host from dashboard data
    const hostMap = {};
    if (data && data.servers) {
        data.servers.forEach(s => { hostMap[s.server_name] = s.server_host; });
    }

    // Populate all server select dropdowns on the page
    const selects = document.querySelectorAll(
        '#purge-server-select, #pred-server-select'
    );
    for (const select of selects) {
        while (select.options.length > 1) {
            select.remove(1);
        }
        for (const srvName of serverNames) {
            const option = document.createElement('option');
            option.value = srvName;
            const host = hostMap[srvName] || srvName;
            option.textContent = `${srvName} (${host})`;
            select.appendChild(option);
        }
    }
}

// ===========================================================
// Purge page: load and display purge report with top-50 default
// Accepts optional limit param (default 50, pass large number for all)
// ===========================================================
async function loadPurgeReport(limit) {
    const serverSelect = document.getElementById('purge-server-select');
    const subappSelect = document.getElementById('purge-subapp-select');
    const thresholdSelect = document.getElementById('purge-threshold');

    if (!serverSelect || !serverSelect.value) return;

    const server = serverSelect.value;
    const subApp = subappSelect ? subappSelect.value : '';
    const threshold = thresholdSelect ? thresholdSelect.value : '365';
    // Default to top 50 candidates unless a specific limit is given
    const maxResults = limit || 50;

    let url = `/api/servers/${encodeURIComponent(server)}/purge?threshold_days=${threshold}&limit=${maxResults}`;
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

    // Show "Load All" button if there are more candidates than shown
    const loadAllBtn = document.getElementById('btn-load-all');
    const showingLabel = document.getElementById('purge-showing-count');
    if (data.candidates && data.total_candidates > data.candidates.length) {
        if (loadAllBtn) loadAllBtn.style.display = 'inline-block';
        if (showingLabel) showingLabel.textContent = `Showing ${data.candidates.length} of ${data.total_candidates}`;
    } else {
        if (loadAllBtn) loadAllBtn.style.display = 'none';
        if (showingLabel) showingLabel.textContent = data.candidates ? `${data.candidates.length} files` : '';
    }

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
        // Color-code the days stale column based on severity
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
// Predictions page: handle server selection change.
// Uses /api/config/sub-app-names to include DB-added sub-apps.
// ===========================================================
async function onPredServerChange() {
    const serverSelect = document.getElementById('pred-server-select');
    const subappSelect = document.getElementById('pred-subapp-select');
    if (!serverSelect || !serverSelect.value || !subappSelect) return;

    // Clear existing sub-app options
    while (subappSelect.options.length > 1) {
        subappSelect.remove(1);
    }

    // Fetch sub-app names from the lookup API (includes DB-added sub-apps)
    const data = await apiFetch(
        '/api/config/sub-app-names?server_name=' +
        encodeURIComponent(serverSelect.value)
    );
    if (data && data.sub_apps) {
        data.sub_apps.forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            subappSelect.appendChild(option);
        });
    }
}

// ===========================================================
// Predictions page: load growth predictions and purge rate
// ===========================================================
async function loadPredictions() {
    const serverSelect = document.getElementById('pred-server-select');
    const subappSelect = document.getElementById('pred-subapp-select');
    if (!serverSelect || !serverSelect.value) return;

    const server = serverSelect.value;
    const subApp = subappSelect ? subappSelect.value : '';

    let predUrl = `/api/servers/${encodeURIComponent(server)}/predictions`;
    let purgeRateUrl = `/api/servers/${encodeURIComponent(server)}/purge-rate`;
    if (subApp) {
        predUrl += `?sub_app_name=${encodeURIComponent(subApp)}`;
        purgeRateUrl += `?sub_app_name=${encodeURIComponent(subApp)}`;
    }

    // Fetch growth predictions and purge rate in parallel
    const [predData, purgeRateData] = await Promise.all([
        apiFetch(predUrl),
        apiFetch(purgeRateUrl),
    ]);

    if (subApp && predData && predData.predictions) {
        // Single sub-app prediction view
        renderSinglePrediction(predData);
    } else if (predData && predData.predictions) {
        // All sub-apps prediction table
        renderAllPredictions(predData);
    }

    // Render the purge rate / net forecast section
    if (purgeRateData) {
        renderPurgeRateForecast(purgeRateData);
    }
}

// ===========================================================
// Render prediction cards for a single sub-app (4 periods)
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
        five_year: 'five-year',
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

    // Render historical trend chart with projection if data available
    if (data.historical_data && data.historical_data.length > 0) {
        renderTrendChart(data.historical_data, data.predictions);
    }
}

// ===========================================================
// Render purge rate and net space forecast section
// ===========================================================
function renderPurgeRateForecast(data) {
    const section = document.getElementById('purge-forecast-section');
    if (section) section.style.display = 'block';

    // Display purge rates
    updateElement('purge-rate-daily', data.daily_purge_rate_human + '/day');
    updateElement('purge-rate-monthly', data.monthly_purge_rate_human + '/month');

    // Display net forecasts for each period
    const netForecasts = data.net_forecasts || {};
    if (netForecasts.weekly) {
        updateElement('net-forecast-week', netForecasts.weekly.net_total_human);
    }
    if (netForecasts.monthly) {
        updateElement('net-forecast-month', netForecasts.monthly.net_total_human);
    }
    if (netForecasts.yearly) {
        updateElement('net-forecast-year', netForecasts.yearly.net_total_human);
    }
    if (netForecasts.five_year) {
        updateElement('net-forecast-5year', netForecasts.five_year.net_total_human);
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
        const fiveYear = report.predictions.find(p => p.period === 'five_year') || {};

        html += `
            <tr>
                <td><strong>${report.sub_app_name}</strong></td>
                <td>${report.current_size_human}</td>
                <td>${weekly.predicted_growth_human || '--'}</td>
                <td>${monthly.predicted_growth_human || '--'}</td>
                <td>${yearly.predicted_growth_human || '--'}</td>
                <td>${fiveYear.predicted_growth_human || '--'}</td>
                <td>${weekly.growth_rate_percent || 0}%</td>
                <td>${monthly.growth_rate_percent || 0}%</td>
                <td>${yearly.growth_rate_percent || 0}%</td>
                <td>${((weekly.confidence || 0) * 100).toFixed(0)}%</td>
            </tr>`;
    }

    tbody.innerHTML = html || '<tr><td colspan="10" class="text-center text-muted">No prediction data available</td></tr>';
}

// ===========================================================
// Chart: Historical space trend with multi-period projections
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

    // Build projection lines for multiple periods
    const lastSize = sizes[sizes.length - 1] || 0;
    const monthlyPred = predictions.find(p => p.period === 'monthly');
    const yearlyPred = predictions.find(p => p.period === 'yearly');

    // Add projected points for the next 12 months
    const projectedLabels = [];
    const projectedSizes = [];
    if (monthlyPred && monthlyPred.predicted_growth_bytes > 0) {
        const monthlyGrowth = monthlyPred.predicted_growth_bytes;
        for (let i = 1; i <= 12; i++) {
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
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.08)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: '#667eea',
                    borderWidth: 2.5,
                },
                {
                    label: 'Projected Growth',
                    data: projectedSeries,
                    borderColor: '#e74c3c',
                    borderDash: [6, 4],
                    backgroundColor: 'rgba(231, 76, 60, 0.06)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: '#e74c3c',
                    borderWidth: 2.5,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { font: { weight: '600' }, padding: 20 },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            if (context.raw === null) return '';
                            return ` ${context.dataset.label}: ${formatSizeFromBytes(context.raw)}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(0,0,0,0.04)' },
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.04)' },
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
// Dashboard: combined Growth / Purge / Forecast chart
// Shows past 1 year to future 5 years on a single line chart.
// Growth = green, Purge = red, Forecast = dotted blue.
// ===========================================================
let combinedChartInstance = null;

async function renderCombinedGrowthPurgeChart(serverName) {
    const url = serverName
        ? '/api/chart/growth-purge-forecast?server_name=' + encodeURIComponent(serverName)
        : '/api/chart/growth-purge-forecast';
    const data = await apiFetch(url);
    if (!data) return;

    const canvas = document.getElementById('combined-gpf-chart');
    if (!canvas) return;

    // Destroy previous chart instance if it exists
    if (combinedChartInstance) {
        combinedChartInstance.destroy();
        combinedChartInstance = null;
    }

    // Build unified labels from historical + forecast
    const allLabels = data.labels || [];

    // Growth line — historical values padded with nulls for forecast months
    const growthData = [];
    const growthLabels = data.growth.historical_labels || [];
    const growthVals = data.growth.historical_values || [];
    for (const lbl of allLabels) {
        const idx = growthLabels.indexOf(lbl);
        growthData.push(idx >= 0 ? growthVals[idx] : null);
    }

    // Purge lines — split into historical (solid red) and forecast (light red)
    const purgeHistLabels = data.purge.historical_labels || [];
    const purgeHistVals = data.purge.historical_values || [];
    const purgeForeLabels = data.purge.forecast_labels || [];
    const purgeForeVals = data.purge.forecast_values || [];
    const purgeHistData = [];   // solid red for past dates
    const purgeForeData = [];   // light red for future dates
    // Find the last historical purge label to bridge the two series
    const lastHistPurgeLabel = purgeHistLabels.length > 0
        ? purgeHistLabels[purgeHistLabels.length - 1] : null;
    let lastHistPurgeVal = null;
    for (const lbl of allLabels) {
        const hIdx = purgeHistLabels.indexOf(lbl);
        if (hIdx >= 0) {
            purgeHistData.push(purgeHistVals[hIdx]);
            lastHistPurgeVal = purgeHistVals[hIdx];
            purgeForeData.push(null);
        } else {
            purgeHistData.push(null);
            const fIdx = purgeForeLabels.indexOf(lbl);
            if (fIdx >= 0) {
                purgeForeData.push(purgeForeVals[fIdx]);
            } else {
                purgeForeData.push(null);
            }
        }
    }
    // Bridge: set the first forecast purge point to match the last
    // historical value so the two line segments connect visually
    if (lastHistPurgeLabel) {
        const bridgeIdx = allLabels.indexOf(lastHistPurgeLabel);
        if (bridgeIdx >= 0) {
            purgeForeData[bridgeIdx] = lastHistPurgeVal;
        }
    }

    // Forecast line — only for future months
    const foreLabels = data.forecast.labels || [];
    const foreVals = data.forecast.values || [];
    const forecastData = [];
    // Connect forecast to last growth point for visual continuity
    const lastGrowthIdx = growthData.length - 1;
    for (let i = 0; i < allLabels.length; i++) {
        const lbl = allLabels[i];
        if (i === growthData.length - 1 && growthData[i] !== null) {
            // Bridge point: set forecast = growth at the junction
            forecastData.push(growthData[i]);
            continue;
        }
        const fIdx = foreLabels.indexOf(lbl);
        forecastData.push(fIdx >= 0 ? foreVals[fIdx] : null);
    }

    combinedChartInstance = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: allLabels,
            datasets: [
                {
                    label: 'Growth (Actual)',
                    data: growthData,
                    borderColor: '#1a7a3a',
                    backgroundColor: 'rgba(26, 122, 58, 0.08)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 3,
                    pointBackgroundColor: '#1a7a3a',
                    borderWidth: 2.5,
                    spanGaps: false,
                },
                {
                    label: 'Purge (Actual)',
                    data: purgeHistData,
                    borderColor: '#e74c3c',
                    backgroundColor: 'rgba(231, 76, 60, 0.06)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 3,
                    pointBackgroundColor: '#e74c3c',
                    borderWidth: 2.5,
                    spanGaps: false,
                },
                {
                    label: 'Purge (Forecast)',
                    data: purgeForeData,
                    borderColor: '#f5a6a6',
                    backgroundColor: 'rgba(245, 166, 166, 0.06)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                    pointBackgroundColor: '#f5a6a6',
                    borderWidth: 2.5,
                    spanGaps: false,
                },
                {
                    label: 'Forecast (Projected)',
                    data: forecastData,
                    borderColor: '#b0b0b0',
                    borderDash: [8, 4],
                    backgroundColor: 'rgba(176, 176, 176, 0.06)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                    pointBackgroundColor: '#b0b0b0',
                    borderWidth: 2.5,
                    spanGaps: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { font: { weight: '600' }, padding: 20 },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            if (context.raw === null) return '';
                            return ` ${context.dataset.label}: ${formatSizeFromBytes(context.raw)}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    title: { display: true, text: 'Month', font: { weight: '600' } },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: { maxTicksLimit: 20 },
                },
                y: {
                    title: { display: true, text: 'Size', font: { weight: '600' } },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: {
                        callback: function(value) { return formatSizeFromBytes(value); },
                    },
                },
            },
        },
    });
}


// ===========================================================
// Purge page: purge history summary cards + chart
// Shows purgeable amounts at 1 week / 1 month / 1 year / 5 years
// ===========================================================
let purgeHistoryChartInstance = null;

async function loadPurgeHistorySummary(serverName) {
    const url = serverName
        ? '/api/purge-history-summary?server_name=' + encodeURIComponent(serverName)
        : '/api/purge-history-summary';
    const data = await apiFetch(url);
    if (!data) return;

    // Render summary cards
    const container = document.getElementById('purge-history-cards');
    if (container && data.summaries) {
        const colors = ['#e74c3c', '#f39c12', '#3498db', '#8e44ad'];
        const icons = ['bi-calendar-week', 'bi-calendar-month', 'bi-calendar', 'bi-calendar-range'];
        let html = '';
        data.summaries.forEach((s, i) => {
            html += `
            <div class="col-md-3 mb-3">
                <div class="card">
                    <div class="card-header text-white" style="background: ${colors[i]};">
                        <i class="bi ${icons[i]}"></i> ${s.label}
                    </div>
                    <div class="card-body text-center">
                        <h3 class="fw-bold" style="color: ${colors[i]};">${s.total_human}</h3>
                        <small class="text-muted">${s.file_count} files eligible (>${s.threshold_days} days old)</small>
                    </div>
                </div>
            </div>`;
        });
        container.innerHTML = html;
    }

    // Render monthly trend chart
    const canvas = document.getElementById('purge-history-chart');
    if (!canvas || !data.monthly_trend) return;
    if (purgeHistoryChartInstance) {
        purgeHistoryChartInstance.destroy();
        purgeHistoryChartInstance = null;
    }
    const labels = data.monthly_trend.map(m => m.month);
    const values = data.monthly_trend.map(m => m.purgeable_bytes);

    purgeHistoryChartInstance = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Purgeable Space (>90 days)',
                data: values,
                borderColor: '#e74c3c',
                backgroundColor: 'rgba(231, 76, 60, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#e74c3c',
                borderWidth: 2.5,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { font: { weight: '600' }, padding: 15 } },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: function(ctx) {
                            return ` Purgeable: ${formatSizeFromBytes(ctx.raw)}`;
                        },
                    },
                },
            },
            scales: {
                x: { title: { display: true, text: 'Month' }, grid: { color: 'rgba(0,0,0,0.04)' } },
                y: {
                    title: { display: true, text: 'Purgeable Space' },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: { callback: v => formatSizeFromBytes(v) },
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
