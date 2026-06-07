/**
 * LeadFlow AI — Dashboard JavaScript
 * Handles all UI interactions, API calls, and real-time updates.
 */

// ═══════════════════════════════════════════════════════════════════════════════
//  STATE & CONFIG
// ═══════════════════════════════════════════════════════════════════════════════

const API = '/api';
const state = {
    currentSection: 'overview',
    leadsPage: 1,
    emailsPage: 1,
    repliesPage: 1,
    perPage: 50,
};

// ═══════════════════════════════════════════════════════════════════════════════
//  INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModals();
    initActions();
    loadOverview();
});

// ═══════════════════════════════════════════════════════════════════════════════
//  NAVIGATION
// ═══════════════════════════════════════════════════════════════════════════════

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const section = item.dataset.section;
            switchSection(section);
        });
    });

    // Mobile menu toggle
    const toggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');
    if (toggle) {
        toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    }
}

function switchSection(section) {
    // Update nav
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`[data-section="${section}"]`);
    if (navItem) navItem.classList.add('active');

    // Update sections
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    const sectionEl = document.getElementById(`section-${section}`);
    if (sectionEl) sectionEl.classList.add('active');

    // Update title
    const titles = {
        overview: 'Overview', leads: 'Lead Management', campaigns: 'Campaigns',
        emails: 'Email Log', replies: 'Reply Tracking', accounts: 'Gmail Accounts',
    };
    document.getElementById('page-title').textContent = titles[section] || section;

    state.currentSection = section;

    // Load section data
    const loaders = {
        overview: loadOverview,
        leads: loadLeads,
        campaigns: loadCampaigns,
        emails: loadEmails,
        replies: loadReplies,
        accounts: loadAccounts,
    };
    if (loaders[section]) loaders[section]();

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  API HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

let _apiKeyCache = null;
let _apiKeyChecked = false;

async function getApiKey() {
    if (_apiKeyChecked) return _apiKeyCache || '';
    
    let key = localStorage.getItem('leadflow_api_key');
    if (key) {
        _apiKeyCache = key;
        _apiKeyChecked = true;
        return key;
    }
    
    // Test without API key first
    try {
        const res = await fetch(`${API}/stats`, { headers: {} });
        if (res.ok) {
            _apiKeyCache = '';
            _apiKeyChecked = true;
            return '';
        }
    } catch (e) {}
    
    // Need API key
    key = prompt("Enter API Key (leave blank if none configured):");
    if (key) localStorage.setItem('leadflow_api_key', key);
    _apiKeyCache = key || '';
    _apiKeyChecked = true;
    return _apiKeyCache;
}

async function apiGet(path) {
    try {
        const apiKey = await getApiKey();
        const res = await fetch(`${API}${path}`, {
            headers: apiKey ? { 'X-API-Key': apiKey } : {}
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (err) {
        console.error(`GET ${path} failed:`, err);
        showToast('error', 'Request Failed', err.message);
        return null;
    }
}

async function apiPost(path, data = {}, isForm = true) {
    try {
        const apiKey = await getApiKey();
        let options = { 
            method: 'POST',
            headers: apiKey ? { 'X-API-Key': apiKey } : {}
        };
        if (isForm && !(data instanceof FormData)) {
            const fd = new FormData();
            Object.entries(data).forEach(([k, v]) => { if (v !== null && v !== undefined) fd.append(k, v); });
            options.body = fd;
        } else if (data instanceof FormData) {
            options.body = data;
        } else {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
        const res = await fetch(`${API}${path}`, options);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return await res.json();
    } catch (err) {
        console.error(`POST ${path} failed:`, err);
        showToast('error', 'Request Failed', err.message);
        return null;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  OVERVIEW
// ═══════════════════════════════════════════════════════════════════════════════

async function loadOverview() {
    const data = await apiGet('/stats');
    if (!data) return;

    const o = data.overview;
    const r = data.rates;

    // Stat cards
    animateValue('val-total-leads', o.total_leads);
    animateValue('val-total-sent', o.total_sent);
    animateValue('val-total-replies', o.total_replies);
    document.getElementById('val-reply-rate').textContent = `${r.reply_rate}%`;

    // Rate bars
    document.getElementById('val-bounce-rate').textContent = `${r.bounce_rate}%`;
    document.getElementById('bar-bounce').style.width = `${Math.min(r.bounce_rate, 100)}%`;

    document.getElementById('val-interested-rate').textContent = `${r.interested_rate}%`;
    document.getElementById('bar-interested').style.width = `${Math.min(r.interested_rate, 100)}%`;

    document.getElementById('val-pending').textContent = o.total_pending;
    const pendingPct = o.total_leads > 0 ? (o.total_pending / o.total_leads * 100) : 0;
    document.getElementById('bar-pending').style.width = `${Math.min(pendingPct, 100)}%`;

    // Pipeline chart
    renderPipeline(data.lead_status_breakdown);
}

function renderPipeline(breakdown) {
    const chart = document.getElementById('pipeline-chart');
    if (!chart) return;

    const stages = [
        { key: 'new', label: 'New', color: 'var(--color-blue)' },
        { key: 'enriched', label: 'Enriched', color: 'var(--color-cyan)' },
        { key: 'email_generated', label: 'Generated', color: 'var(--color-purple)' },
        { key: 'emailed', label: 'Emailed', color: 'var(--color-amber)' },
        { key: 'followup_1_sent', label: 'FU-1', color: '#fb923c' },
        { key: 'followup_2_sent', label: 'FU-2', color: '#f97316' },
        { key: 'replied', label: 'Replied', color: 'var(--color-green)' },
        { key: 'bounced', label: 'Bounced', color: 'var(--color-red)' },
    ];

    const maxVal = Math.max(1, ...stages.map(s => breakdown[s.key] || 0));

    chart.innerHTML = stages.map(s => {
        const val = breakdown[s.key] || 0;
        const height = Math.max(4, (val / maxVal) * 140);
        return `
            <div class="pipeline-bar-group">
                <div class="pipeline-bar" style="height:${height}px; background:${s.color}">
                    <span class="pipeline-bar-value">${val}</span>
                </div>
                <span class="pipeline-label">${s.label}</span>
            </div>
        `;
    }).join('');
}

function animateValue(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const start = parseInt(el.textContent) || 0;
    const duration = 600;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + (target - start) * eased);
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  LEADS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadLeads() {
    const status = document.getElementById('lead-status-filter')?.value || '';
    const params = new URLSearchParams({ page: state.leadsPage, per_page: state.perPage });
    if (status) params.set('status', status);

    const data = await apiGet(`/leads?${params}`);
    if (!data) return;

    const tbody = document.getElementById('leads-tbody');
    if (!data.leads.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No leads found. Upload a CSV to get started.</td></tr>';
        return;
    }

    tbody.innerHTML = data.leads.map(l => `
        <tr>
            <td style="color:var(--text-primary);font-weight:500">${esc(l.first_name)} ${esc(l.last_name)}</td>
            <td>${esc(l.email)}</td>
            <td>${esc(l.company_name)}</td>
            <td>${esc(l.industry || '—')}</td>
            <td><span class="badge badge-${l.status}">${l.status.replace(/_/g, ' ')}</span></td>
            <td><span class="badge badge-${l.source === 'csv' ? 'new' : 'enriched'}">${l.source}</span></td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteLead(${l.id})">Delete</button></td>
        </tr>
    `).join('');

    renderPagination('leads-pagination', data.total, state.leadsPage, (p) => { state.leadsPage = p; loadLeads(); });
}

async function deleteLead(id) {
    if (!confirm('Delete this lead and all associated emails?')) return;
    const res = await fetch(`${API}/leads/${id}`, { method: 'DELETE' });
    if (res.ok) { showToast('success', 'Lead Deleted'); loadLeads(); }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  CAMPAIGNS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadCampaigns() {
    const data = await apiGet('/campaigns');
    if (!data) return;

    const grid = document.getElementById('campaigns-grid');
    if (!data.campaigns.length) {
        grid.innerHTML = '<div class="empty-state-card"><p>No campaigns yet. Create one to start sending emails.</p></div>';
        return;
    }

    grid.innerHTML = data.campaigns.map(c => `
        <div class="campaign-card">
            <div class="campaign-card-header">
                <span class="campaign-card-name">${esc(c.name)}</span>
                <span class="badge badge-${c.status}">${c.status}</span>
            </div>
            <div class="campaign-stats">
                <div class="campaign-stat">
                    <span class="campaign-stat-value">${c.total_leads}</span>
                    <span class="campaign-stat-label">Leads</span>
                </div>
                <div class="campaign-stat">
                    <span class="campaign-stat-value">${c.total_sent}</span>
                    <span class="campaign-stat-label">Sent</span>
                </div>
                <div class="campaign-stat">
                    <span class="campaign-stat-value">${c.reply_rate}%</span>
                    <span class="campaign-stat-label">Reply Rate</span>
                </div>
                <div class="campaign-stat">
                    <span class="campaign-stat-value">${c.total_bounces}</span>
                    <span class="campaign-stat-label">Bounces</span>
                </div>
            </div>
            <div class="campaign-card-actions">
                ${c.status === 'active'
                    ? `<button class="btn btn-secondary btn-sm" onclick="pauseCampaign(${c.id})">Pause</button>`
                    : `<button class="btn btn-primary btn-sm" onclick="startCampaign(${c.id})">Start</button>`
                }
            </div>
        </div>
    `).join('');
}

async function startCampaign(id) {
    const res = await apiPost(`/campaigns/${id}/start`);
    if (res) { showToast('success', 'Campaign Started', 'Emails are being sent in the background.'); loadCampaigns(); }
}

async function pauseCampaign(id) {
    const res = await apiPost(`/campaigns/${id}/pause`);
    if (res) { showToast('info', 'Campaign Paused'); loadCampaigns(); }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  EMAILS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadEmails() {
    const status = document.getElementById('email-status-filter')?.value || '';
    const type = document.getElementById('email-type-filter')?.value || '';
    const params = new URLSearchParams({ page: state.emailsPage, per_page: state.perPage });
    if (status) params.set('status', status);
    if (type) params.set('email_type', type);

    const data = await apiGet(`/emails?${params}`);
    if (!data) return;

    const tbody = document.getElementById('emails-tbody');
    if (!data.emails.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No emails found.</td></tr>';
        return;
    }

    tbody.innerHTML = data.emails.map(e => `
        <tr>
            <td style="color:var(--text-primary);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.subject)}</td>
            <td><span class="badge badge-${e.email_type}">${e.email_type.replace(/_/g, ' ')}</span></td>
            <td><span class="badge badge-${e.status}">${e.status}</span></td>
            <td>${esc(e.gmail_account || '—')}</td>
            <td>${e.sent_at ? new Date(e.sent_at).toLocaleString() : '—'}</td>
        </tr>
    `).join('');

    renderPagination('emails-pagination', data.total, state.emailsPage, (p) => { state.emailsPage = p; loadEmails(); });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  REPLIES
// ═══════════════════════════════════════════════════════════════════════════════

async function loadReplies() {
    const cls = document.getElementById('reply-class-filter')?.value || '';
    const params = new URLSearchParams({ page: state.repliesPage, per_page: state.perPage });
    if (cls) params.set('classification', cls);

    const data = await apiGet(`/replies?${params}`);
    if (!data) return;

    const tbody = document.getElementById('replies-tbody');
    if (!data.replies.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No replies yet.</td></tr>';
        return;
    }

    tbody.innerHTML = data.replies.map(r => `
        <tr>
            <td style="color:var(--text-primary)">Lead #${r.lead_id}</td>
            <td style="max-width:350px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.reply_body)}</td>
            <td><span class="badge badge-${r.classification}">${r.classification.replace(/_/g, ' ')}</span></td>
            <td>${r.confidence ? (r.confidence * 100).toFixed(0) + '%' : '—'}</td>
            <td>${r.received_at ? new Date(r.received_at).toLocaleString() : '—'}</td>
        </tr>
    `).join('');

    renderPagination('replies-pagination', data.total, state.repliesPage, (p) => { state.repliesPage = p; loadReplies(); });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ACCOUNTS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadAccounts() {
    const data = await apiGet('/accounts');
    if (!data) return;

    const grid = document.getElementById('accounts-grid');
    if (!data.accounts.length) {
        grid.innerHTML = '<div class="empty-state-card"><p>No Gmail accounts configured. Add one to start sending.</p></div>';
        return;
    }

    grid.innerHTML = data.accounts.map(a => `
        <div class="account-card">
            <div class="account-card-header">
                <span class="account-card-email">${esc(a.email)}</span>
                <span class="badge badge-${a.is_healthy ? 'healthy' : 'unhealthy'}">${a.is_healthy ? 'Healthy' : 'Unhealthy'}</span>
            </div>
            <div class="account-meta">
                <div class="account-meta-item">
                    <span>Display Name</span>
                    <span class="account-meta-value">${esc(a.display_name || '—')}</span>
                </div>
                <div class="account-meta-item">
                    <span>Sent Today</span>
                    <span class="account-meta-value">${a.sends_today}</span>
                </div>
                <div class="account-meta-item">
                    <span>Last Send</span>
                    <span class="account-meta-value">${a.last_send_at ? new Date(a.last_send_at).toLocaleString() : 'Never'}</span>
                </div>
                <div class="account-meta-item">
                    <span>Status</span>
                    <span class="account-meta-value">${a.is_active ? 'Active' : 'Inactive'}</span>
                </div>
            </div>
            ${a.error ? `<p style="font-size:0.78rem;color:var(--color-red);margin-bottom:12px">${esc(a.error)}</p>` : ''}
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MODALS
// ═══════════════════════════════════════════════════════════════════════════════

function initModals() {
    // New Campaign Modal
    const campaignModal = document.getElementById('modal-new-campaign');
    document.getElementById('btn-new-campaign')?.addEventListener('click', () => campaignModal.classList.add('open'));
    document.getElementById('modal-close-campaign')?.addEventListener('click', () => campaignModal.classList.remove('open'));
    document.getElementById('btn-cancel-campaign')?.addEventListener('click', () => campaignModal.classList.remove('open'));

    document.getElementById('btn-create-campaign')?.addEventListener('click', async () => {
        const name = document.getElementById('campaign-name').value.trim();
        const limit = parseInt(document.getElementById('campaign-limit').value) || 50;
        if (!name) { showToast('warning', 'Name Required'); return; }
        const res = await apiPost('/campaigns/create', { name, daily_limit: limit });
        if (res) {
            showToast('success', 'Campaign Created', `"${name}" is ready.`);
            campaignModal.classList.remove('open');
            document.getElementById('campaign-name').value = '';
            loadCampaigns();
        }
    });

    // Add Account Modal
    const accountModal = document.getElementById('modal-add-account');
    document.getElementById('btn-add-account')?.addEventListener('click', () => accountModal.classList.add('open'));
    document.getElementById('modal-close-account')?.addEventListener('click', () => accountModal.classList.remove('open'));
    document.getElementById('btn-cancel-account')?.addEventListener('click', () => accountModal.classList.remove('open'));

    document.getElementById('btn-submit-account')?.addEventListener('click', async () => {
        const email = document.getElementById('account-email').value.trim();
        const name = document.getElementById('account-name').value.trim();
        if (!email) { showToast('warning', 'Email Required'); return; }
        const res = await apiPost('/accounts/add', { email, display_name: name || null });
        if (res) {
            showToast('success', 'Account Added', `${email} connected successfully.`);
            accountModal.classList.remove('open');
            document.getElementById('account-email').value = '';
            document.getElementById('account-name').value = '';
            loadAccounts();
        }
    });

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.classList.remove('open');
        });
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ACTIONS
// ═══════════════════════════════════════════════════════════════════════════════

function initActions() {
    // Refresh
    document.getElementById('btn-refresh')?.addEventListener('click', () => {
        const loaders = {
            overview: loadOverview, leads: loadLeads, campaigns: loadCampaigns,
            emails: loadEmails, replies: loadReplies, accounts: loadAccounts,
        };
        if (loaders[state.currentSection]) loaders[state.currentSection]();
        showToast('info', 'Refreshed');
    });

    // Check replies
    document.getElementById('btn-check-replies')?.addEventListener('click', async () => {
        const res = await apiPost('/replies/check');
        if (res) showToast('info', 'Checking Replies', 'Scanning all inboxes...');
    });

    // CSV upload
    document.getElementById('csv-file-input')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('file', file);
        const res = await apiPost('/leads/upload-csv', fd);
        if (res) {
            showToast('success', 'CSV Imported', `${res.imported} leads imported.`);
            loadLeads();
        }
        e.target.value = '';
    });

    // Enrich
    document.getElementById('btn-enrich')?.addEventListener('click', async () => {
        const res = await apiPost('/leads/enrich');
        if (res) showToast('info', 'Enrichment Started', 'Running in background...');
    });

    // Generate emails
    document.getElementById('btn-generate-emails')?.addEventListener('click', async () => {
        const campaignData = await apiGet('/campaigns');
        const activeCampaign = campaignData?.campaigns?.find(c => c.status === 'active' || c.status === 'paused');
        const campaignId = activeCampaign?.id || null;
        const fd = new FormData();
        fd.append('limit', 50);
        if (campaignId) fd.append('campaign_id', campaignId);
        const res = await apiPost('/emails/generate', fd, true);
        if (res) showToast('info', 'Generation Started', 'AI is writing your emails...');
    });

    // Check follow-ups
    document.getElementById('btn-check-followups')?.addEventListener('click', async () => {
        const res = await apiPost('/followups/check', new FormData(), true);
        if (res) showToast('info', 'Follow-Up Check', 'Queuing eligible follow-ups...');
    });

    // Health check
    document.getElementById('btn-health-check')?.addEventListener('click', async () => {
        const res = await apiPost('/accounts/health-check');
        if (res) {
            showToast('info', 'Health Check', `${res.healthy} healthy, ${res.unhealthy} unhealthy`);
            loadAccounts();
        }
    });

    // Filters
    document.getElementById('lead-status-filter')?.addEventListener('change', () => { state.leadsPage = 1; loadLeads(); });
    document.getElementById('email-status-filter')?.addEventListener('change', () => { state.emailsPage = 1; loadEmails(); });
    document.getElementById('email-type-filter')?.addEventListener('change', () => { state.emailsPage = 1; loadEmails(); });
    document.getElementById('reply-class-filter')?.addEventListener('change', () => { state.repliesPage = 1; loadReplies(); });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════════════════

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function renderPagination(containerId, total, currentPage, onPageChange) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const totalPages = Math.ceil(total / state.perPage);
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = '';
    html += `<button ${currentPage <= 1 ? 'disabled' : ''} onclick="void(0)">Prev</button>`;

    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage < maxVisible - 1) startPage = Math.max(1, endPage - maxVisible + 1);

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }

    html += `<button ${currentPage >= totalPages ? 'disabled' : ''} onclick="void(0)">Next</button>`;
    container.innerHTML = html;

    container.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            const page = btn.dataset.page;
            if (page) {
                onPageChange(parseInt(page));
            } else if (btn.textContent === 'Prev') {
                onPageChange(currentPage - 1);
            } else if (btn.textContent === 'Next') {
                onPageChange(currentPage + 1);
            }
        });
    });
}

// ── Toast Notifications ─────────────────────────────────────────────────────

function showToast(type, title, message = '') {
    const container = document.getElementById('toast-container');
    const icons = {
        success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        error: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        info: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        warning: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <div class="toast-content">
            <div class="toast-title">${esc(title)}</div>
            ${message ? `<div class="toast-message">${esc(message)}</div>` : ''}
        </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
