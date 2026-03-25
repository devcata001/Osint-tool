/**
 * Trace Handle Frontend
 * Handles form submission, API interaction, and result rendering
 */

// ==================== DOM Elements ====================

const osintForm = document.getElementById('osintForm');
const inputField = document.getElementById('inputField');
const helperText = document.getElementById('helperText');
const loadingIndicator = document.getElementById('loadingIndicator');
const resultsSection = document.getElementById('resultsSection');
const errorSection = document.getElementById('errorSection');
const infoSection = document.getElementById('infoSection');
const summaryDiv = document.getElementById('summary');
const resultsTableDiv = document.getElementById('resultsTable');
const recommendationsDiv = document.getElementById('recommendations');
const copyBtn = document.getElementById('copyBtn');
const resetBtn = document.getElementById('resetBtn');
const tooltip = document.getElementById('tooltip');

const radios = document.querySelectorAll('input[name="input_type"]');

// ==================== Event Listeners ====================

osintForm.addEventListener('submit', handleFormSubmit);
copyBtn.addEventListener('click', copyResults);
resetBtn.addEventListener('click', resetForm);

radios.forEach(radio => {
    radio.addEventListener('change', updateHelperText);
});

inputField.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        osintForm.dispatchEvent(new Event('submit'));
    }
});

// ==================== Form Handler ====================

async function handleFormSubmit(e) {
    e.preventDefault();

    const input = inputField.value.trim();
    const inputType = document.querySelector('input[name="input_type"]:checked').value;

    if (!input) {
        showError('Please enter a value to check');
        return;
    }

    // Disable button and show loading
    const checkBtn = osintForm.querySelector('.btn-check');
    checkBtn.disabled = true;
    showLoading();
    hideError();
    hideResults();

    try {
        const response = await fetch('/api/check', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                input: input,
                input_type: inputType
            })
        });

        const contentType = (response.headers.get('content-type') || '').toLowerCase();
        if (!contentType.includes('application/json')) {
            const rawText = await response.text();
            console.error('Non-JSON backend response:', rawText.slice(0, 500));
            showError(`Backend returned a non-JSON response (HTTP ${response.status}). Check reverse proxy/API routing for /api/check.`);
            return;
        }

        let data = null;
        try {
            data = await response.json();
        } catch (_err) {
            showError(`Backend returned invalid JSON (HTTP ${response.status}). Check server logs.`);
            return;
        }

        if (!response.ok || !data.success) {
            showError(data.error || 'An error occurred');
        } else {
            renderResults(data);
            showResults();
        }
    } catch (error) {
        console.error('Request failed:', error);
        showError('Failed to connect to the server. Please try again.');
    } finally {
        checkBtn.disabled = false;
        hideLoading();
    }
}

// ==================== Result Rendering ====================

function renderResults(data) {
    const inputType = data.input_type;

    // Render summary
    renderSummary(data);

    // Render results table
    renderResultsTable(data);

    // Render recommendations
    renderRecommendations(data);

    // Store data for copy function
    window.currentResults = data;
}

function renderSummary(data) {
    const inputType = data.input_type;
    let summaryHTML = '';

    summaryHTML += `<p style="text-align: center; margin-bottom: 1rem;"><strong>Checking:</strong> ${escapeHtml(data.input)}</p>`;

    if (inputType === 'username') {
        const summary = data.summary || { total_checks: 0, matches_found: 0 };
        const confidenceScore = typeof data.confidence_score === 'number' ? data.confidence_score : 0;
        const riskSummary = data.risk_summary || 'Unknown';
        const uncertainCount = summary.uncertain_count || 0;
        const unsupportedCount = summary.unsupported_count || 0;
        const avgResponseTimeMs = summary.avg_response_time_ms || 0;
        const proxyEnabled = Boolean(summary.proxy_enabled);
        summaryHTML += `
            <div class="summary-row">
                <span class="summary-label">Platforms Checked</span>
                <span class="summary-value">${summary.total_checks}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Matches Found</span>
                <span class="summary-value ${summary.matches_found > 2 ? 'danger' : ''}">${summary.matches_found}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Confidence Score</span>
                <span class="summary-value ${confidenceScore >= 0.8 ? 'danger' : 'success'}">${(confidenceScore * 100).toFixed(0)}%</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Risk Level</span>
                <span class="summary-value ${riskSummary.includes('High') ? 'danger' : 'success'}">${escapeHtml(riskSummary)}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Uncertain Checks</span>
                <span class="summary-value ${uncertainCount > 0 ? 'warning' : 'success'}">${uncertainCount}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Unsupported Checks</span>
                <span class="summary-value ${unsupportedCount > 0 ? 'warning' : 'success'}">${unsupportedCount}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Avg Probe Time</span>
                <span class="summary-value">${Number(avgResponseTimeMs).toFixed(1)} ms</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Proxy Route</span>
                <span class="summary-value ${proxyEnabled ? 'warning' : 'success'}">${proxyEnabled ? 'Enabled' : 'Disabled'}</span>
            </div>
        `;
    } else if (inputType === 'email') {
        const exposedTypes = Array.isArray(data.exposed_data_types) ? data.exposed_data_types : [];
        const riskClass = data.risk_level === 'Critical' ? 'danger' : data.risk_level === 'High' ? 'warning' : 'success';
        summaryHTML += `
            <div class="summary-row">
                <span class="summary-label">Breaches Found</span>
                <span class="summary-value ${riskClass}">${data.breach_count}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Risk Level</span>
                <span class="summary-value ${riskClass}">${escapeHtml(data.risk_level)}</span>
            </div>
            ${exposedTypes.length > 0 ? `
            <div class="summary-row">
                <span class="summary-label">Exposed Data Types</span>
                <span class="summary-value">${escapeHtml(exposedTypes.join(', '))}</span>
            </div>
            ` : ''}
        `;
    } else if (inputType === 'phone') {
        const validClass = data.valid ? 'success' : 'danger';
        summaryHTML += `
            <div class="summary-row">
                <span class="summary-label">Format Validation</span>
                <span class="summary-value ${validClass}">${data.valid ? 'Valid' : 'Invalid'}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">Risk Level</span>
                <span class="summary-value">${escapeHtml(data.risk_level)}</span>
            </div>
        `;
    }

    summaryDiv.innerHTML = summaryHTML;
}

function renderResultsTable(data) {
    const inputType = data.input_type;
    const rows = Array.isArray(data.results) ? data.results : [];
    let cardsHTML = '';

    if (inputType === 'username' && rows.length > 0) {
        cardsHTML = `
            <div class="results-cards">
                ${rows.map(result => {
            const statusText = result.status || (result.exists ? 'Found' : 'Not Found');
            const statusClass = statusText === 'Found'
                ? 'badge-success'
                : statusText === 'Uncertain'
                    ? 'badge-warning'
                    : statusText === 'Unsupported'
                        ? 'badge-warning'
                        : 'badge-low';
            const confidenceClass = `badge-${String(result.confidence || 'low').toLowerCase()}`;
            const linkHtml = `<a href="${result.url}" target="_blank" rel="noopener noreferrer" class="platform-link">Open Profile →</a>`;
            const httpStatus = result.http_status || 0;
            const detectionMethod = result.detection_method || 'n/a';
            const responseTimeMs = Number(result.response_time_ms || 0).toFixed(1);
            const errorText = result.error || '';

            return `
                        <article class="result-card">
                            <div class="result-card-header">
                                <h4 class="result-title">${escapeHtml(result.platform)}</h4>
                                <div class="result-badges">
                                    <span class="badge ${statusClass}">${statusText}</span>
                                    <span class="badge ${confidenceClass}">${escapeHtml(result.confidence || 'Low')}</span>
                                </div>
                            </div>
                            <div class="result-meta"><span>Username:</span> <code>${escapeHtml(result.username)}</code></div>
                            <div class="result-meta"><span>HTTP:</span> ${httpStatus || 'n/a'} | <span>Method:</span> ${escapeHtml(detectionMethod)} | <span>RTT:</span> ${responseTimeMs} ms</div>
                            ${errorText ? `<div class="result-meta"><span>Error:</span> ${escapeHtml(errorText)}</div>` : ''}
                            <div class="result-link">${linkHtml}</div>
                        </article>
                        `;
        }).join('')}
            </div>
        `;
    } else if (inputType === 'email' && rows.length > 0) {
        cardsHTML = `
            <div class="results-cards">
                    ${rows.map(result => `
                        <article class="result-card">
                            <div class="result-card-header">
                                <h4 class="result-title">${escapeHtml(result.breach_name)}</h4>
                                <div class="result-badges">
                                    <span class="badge badge-danger">Compromised</span>
                                </div>
                            </div>
                            <div class="result-meta"><span>Date:</span> ${escapeHtml(result.breach_date)}</div>
                            <div class="result-meta"><span>Records:</span> ${escapeHtml(result.record_count)}</div>
                            ${result.link ? `<div class="result-link"><a href="${result.link}" target="_blank" rel="noopener noreferrer" class="platform-link">View Breach →</a></div>` : ''}
                        </article>
                    `).join('')}
            </div>
        `;
    } else if (rows.length > 0) {
        cardsHTML = `
            <div class="results-cards">
                    ${rows.map(result => `
                        <article class="result-card">
                            <div class="result-card-header">
                                <h4 class="result-title">${escapeHtml(result.check || result.platform || 'Check')}</h4>
                                <div class="result-badges">
                                    <span class="badge badge-${(result.confidence || result.confidence_score || 'low').toString().toLowerCase()}">${escapeHtml((result.confidence || result.confidence_score || 'N/A').toString())}</span>
                                </div>
                            </div>
                            <div class="result-meta">${escapeHtml(result.result || result.username || 'N/A')}</div>
                        </article>
                    `).join('')}
            </div>
        `;
    } else {
        cardsHTML = '<p style="padding: 2rem; text-align: center; color: var(--color-text-light);">No results found.</p>';
    }

    resultsTableDiv.innerHTML = cardsHTML;
}

function renderRecommendations(data) {
    if (!data.recommendations || data.recommendations.length === 0) {
        recommendationsDiv.innerHTML = '';
        return;
    }

    const recommendations = data.recommendations.filter(r => r && r.trim());

    if (recommendations.length === 0) {
        recommendationsDiv.innerHTML = '';
        return;
    }

    const recHTML = `
        <h3>📋 Recommendations</h3>
        <ul>
            ${recommendations.map(rec => `<li>${escapeHtml(rec)}</li>`).join('')}
        </ul>
    `;

    recommendationsDiv.innerHTML = recHTML;
}

// ==================== UI State Management ====================

function showLoading() {
    loadingIndicator.classList.remove('hidden');
}

function hideLoading() {
    loadingIndicator.classList.add('hidden');
}

function showResults() {
    resultsSection.classList.remove('hidden');
    infoSection.classList.add('hidden');
}

function hideResults() {
    resultsSection.classList.add('hidden');
}

function showError(message) {
    errorSection.classList.remove('hidden');
    document.getElementById('errorMessage').textContent = message;
    infoSection.classList.add('hidden');
}

function hideError() {
    errorSection.classList.add('hidden');
}

function resetForm() {
    osintForm.reset();
    inputField.focus();
    hideResults();
    hideError();
    infoSection.classList.remove('hidden');
    updateHelperText();
}

function updateHelperText() {
    const inputType = document.querySelector('input[name="input_type"]:checked').value;
    const messages = {
        username: 'Enter a username to check across platforms (GitHub, X, Reddit, Instagram, Telegram, etc.)',
        email: 'Enter an email address to check for data breach appearances'
    };
    helperText.textContent = messages[inputType] || messages.username;
}

// ==================== Copy Results ====================

function copyResults() {
    if (!window.currentResults) return;

    const data = window.currentResults;
    let text = `OSINT Check Results\n`;
    text += `====================\n\n`;
    text += `Input Type: ${data.input_type}\n`;
    text += `Input: ${data.input}\n\n`;

    if (data.input_type === 'username') {
        text += `Platforms Checked: ${data.summary.total_checks}\n`;
        text += `Matches Found: ${data.summary.matches_found}\n`;
        text += `Confidence Score: ${(data.confidence_score * 100).toFixed(0)}%\n`;
        text += `Risk Level: ${data.risk_summary}\n\n`;
        text += `Results:\n`;
        data.results.forEach(result => {
            text += `- ${result.platform}: ${result.username} (${result.confidence})\n`;
            text += `  ${result.url}\n`;
        });
    } else if (data.input_type === 'email') {
        text += `Breaches Found: ${data.breach_count}\n`;
        text += `Risk Level: ${data.risk_level}\n\n`;
        text += `Breaches:\n`;
        data.results.forEach(result => {
            text += `- ${result.breach_name} (${result.breach_date})\n`;
            text += `  Records: ${result.record_count}\n`;
        });
    }

    text += `\n\nRecommendations:\n`;
    data.recommendations.forEach(rec => {
        text += `- ${rec}\n`;
    });

    // Copy to clipboard
    navigator.clipboard.writeText(text).then(() => {
        // Show temporary confirmation
        const originalText = copyBtn.textContent;
        copyBtn.textContent = '✓ Copied';
        setTimeout(() => {
            copyBtn.textContent = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

// ==================== Utilities ====================

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

// ==================== Tooltip Handler ====================

document.addEventListener('mouseover', (e) => {
    if (e.target.hasAttribute('data-tooltip')) {
        const tooltipText = e.target.getAttribute('data-tooltip');
        tooltip.textContent = tooltipText;
        tooltip.classList.remove('hidden');

        const rect = e.target.getBoundingClientRect();
        tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
        tooltip.style.top = (rect.top - tooltip.offsetHeight - 8) + 'px';
    }
});

document.addEventListener('mouseout', (e) => {
    if (e.target.hasAttribute('data-tooltip')) {
        tooltip.classList.add('hidden');
    }
});

// ==================== Initialization ====================

document.addEventListener('DOMContentLoaded', () => {
    inputField.focus();
    updateHelperText();
});
