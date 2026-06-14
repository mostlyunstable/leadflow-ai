/**
 * LeadFlow AI — Dashboard JavaScript
 * Premium SaaS Dashboard — All UI interactions, API calls, and real-time updates.
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
    leadSearchQuery: '',
};

// ═══════════════════════════════════════════════════════════════════════════════
//  INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModals();
    initActions();
    initSlideOvers();
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

    const toggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');
    if (toggle) {
        toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    }
}

function switchSection(section) {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`[data-section="${section}"]`);
    if (navItem) navItem.classList.add('active');

    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    const sectionEl = document.getElementById(`section-${section}`);
    if (sectionEl) sectionEl.classList.add('active');

    const titles = {
        overview: 'Overview', leads: 'Lead Management', campaigns: 'Campaigns',
        emails: 'Email Log', replies: 'Reply Tracking', accounts: 'Gmail Accounts',
        analytics: 'Analytics',
    };
    document.getElementById('page-title').textContent = titles[section] || section;

    state.currentSection = section;

        const loaders = {
            overview: loadOverview,
        leads: loadLeads,
        campaigns: loadCampaigns,
        emails: loadEmails,
        replies: loadReplies,
        accounts: loadAccounts,
        analytics: loadAnalytics,
    };
    if (loaders[section]) loaders[section]();

    document.getElementById('sidebar').classList.remove('open');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  API HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

let _apiKeyCache = null;
let _apiKeyChecked = false;

async function getApiKey() {
    if (_apiKeyChecked) return _apiKeyCache || '';

    try {
        const res = await fetch(`${API}/stats`, { headers: {} });
        if (res.ok) {
            _apiKeyCache = '';
            _apiKeyChecked = true;
            return '';
        }
    } catch (e) {}

    const key = prompt("Enter API Key (leave blank if none configured):");
    if (key) _apiKeyCache = key;
    _apiKeyChecked = true;
    return _apiKeyCache || '';
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

    document.getElementById('val-total-leads').textContent = o.total_leads;
    document.getElementById('val-total-sent').textContent = o.total_sent;
    document.getElementById('val-total-replies').textContent = o.total_replies;
    document.getElementById('val-reply-rate').textContent = `${r.reply_rate}%`;

    renderPipelineBreakdown(data.lead_status_breakdown, o.total_leads);
    loadOverviewCounts();
}

async function loadOverviewCounts() {
    const [campaignData, accountData] = await Promise.all([
        apiGet('/campaigns'),
        apiGet('/accounts'),
    ]);
    if (campaignData) {
        const active = campaignData.campaigns.filter(c => c.status === 'active').length;
        document.getElementById('val-active-campaigns').textContent = active;
    }
    if (accountData) {
        document.getElementById('val-accounts-count').textContent = accountData.accounts.length;
    }
}

function renderPipelineBreakdown(breakdown, total) {
    const el = document.getElementById('pipeline-breakdown');
    if (!el) return;

    const stages = [
        { key: 'new', label: 'New' },
        { key: 'enriched', label: 'Enriched' },
        { key: 'email_generated', label: 'Email Generated' },
        { key: 'emailed', label: 'Emailed' },
        { key: 'followup_1_sent', label: 'Follow-Up 1' },
        { key: 'followup_2_sent', label: 'Follow-Up 2' },
        { key: 'replied', label: 'Replied' },
        { key: 'bounced', label: 'Bounced' },
    ];

    const rows = stages
        .map(s => ({ ...s, count: breakdown[s.key] || 0 }))
        .filter(s => s.count > 0);

    if (rows.length === 0) {
        el.innerHTML = '<div class="empty-state">No leads in pipeline</div>';
        return;
    }

    el.innerHTML = `<table class="data-table">
        <thead><tr><th>Status</th><th style="text-align:right">Count</th><th style="text-align:right">%</th></tr></thead>
        <tbody>${rows.map(s => {
            const pct = total > 0 ? Math.round((s.count / total) * 100) : 0;
            return `<tr>
                <td>${s.label}</td>
                <td style="text-align:right;font-weight:600">${s.count}</td>
                <td style="text-align:right;color:var(--text-muted)">${pct}%</td>
            </tr>`;
        }).join('')}</tbody>
    </table>`;
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

    let leads = data.leads;
    if (state.leadSearchQuery) {
        const q = state.leadSearchQuery.toLowerCase();
        leads = leads.filter(l =>
            l.first_name.toLowerCase().includes(q) ||
            l.last_name.toLowerCase().includes(q) ||
            l.email.toLowerCase().includes(q) ||
            l.company_name.toLowerCase().includes(q)
        );
    }

    const tbody = document.getElementById('leads-tbody');
    if (!leads.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No leads found. Upload a CSV to get started.</td></tr>';
        return;
    }

    tbody.innerHTML = leads.map(l => `
        <tr onclick="openLeadDetail(${l.id}, '${esc(l.first_name)}', '${esc(l.last_name)}', '${esc(l.email)}', '${esc(l.company_name)}', '${esc(l.industry || '')}')" data-lead-id="${l.id}">
            <td style="color:var(--text-primary);font-weight:500">${esc(l.first_name)} ${esc(l.last_name)}</td>
            <td>${esc(l.email)}</td>
            <td>${esc(l.company_name)}</td>
            <td>${esc(l.industry || '—')}</td>
            <td><span class="badge badge-${l.status}">${l.status.replace(/_/g, ' ')}</span></td>
            <td><span class="badge badge-${l.source === 'csv' ? 'new' : 'enriched'}">${l.source}</span></td>
            <td><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteLead(${l.id})">Delete</button></td>
        </tr>
    `).join('');

    renderPagination('leads-pagination', data.total, state.leadsPage, (p) => { state.leadsPage = p; loadLeads(); });
}

async function deleteLead(id) {
    if (!confirm('Delete this lead and all associated emails?')) return;
    const apiKey = await getApiKey();
    const headers = apiKey ? { 'X-Api-Key': apiKey } : {};
    const res = await fetch(`${API}/leads/${id}`, { method: 'DELETE', headers });
    if (res.ok) {
        showToast('success', 'Lead Deleted');
        loadLeads();
    }
}

function openLeadDetail(id, firstName, lastName, email, company, industry) {
    document.getElementById('lead-detail-name').textContent = `${firstName} ${lastName}`;
    document.getElementById('detail-email').textContent = email;
    document.getElementById('detail-company').textContent = company || '—';
    document.getElementById('detail-industry').textContent = industry || '—';
    document.getElementById('lead-detail-overlay').classList.add('open');
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

    grid.innerHTML = data.campaigns.map(c => {
        const progress = c.total_leads > 0 ? Math.round((c.total_sent / c.total_leads) * 100) : 0;
        return `
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
                        <span class="campaign-stat-value">${c.total_replies || 0}</span>
                        <span class="campaign-stat-label">Replies</span>
                    </div>
                    <div class="campaign-stat">
                        <span class="campaign-stat-value">${c.reply_rate}%</span>
                        <span class="campaign-stat-label">Reply Rate</span>
                    </div>
                </div>
                <div class="campaign-progress">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width:${Math.min(progress, 100)}%"></div>
                    </div>
                    <div class="progress-label">
                        <span>${c.total_sent} / ${c.total_leads} sent</span>
                        <span>${progress}%</span>
                    </div>
                </div>
                <div class="campaign-card-actions">
                    ${c.status === 'active'
                        ? `<button class="btn btn-secondary btn-sm" onclick="pauseCampaign(${c.id})">Pause</button>`
                        : `<button class="btn btn-primary btn-sm" onclick="startCampaign(${c.id})">Start</button>`
                    }
                </div>
            </div>
        `;
    }).join('');
}

async function startCampaign(id) {
    const res = await apiPost(`/campaigns/${id}/start`);
    if (res) {
        showToast('success', 'Campaign Started', 'Emails are being sent in the background.');
        loadCampaigns();
    }
}

async function pauseCampaign(id) {
    const res = await apiPost(`/campaigns/${id}/pause`);
    if (res) {
        showToast('info', 'Campaign Paused');
        loadCampaigns();
    }
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
        <tr onclick="openEmailPreview('${esc(e.subject)}', '${esc(e.body)}', '${e.email_type}', '${e.status}', '${esc(e.gmail_account || '')}', '${e.sent_at || ''}')" style="cursor:pointer">
            <td style="color:var(--text-primary);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.subject)}</td>
            <td><span class="badge badge-${e.email_type}">${e.email_type.replace(/_/g, ' ')}</span></td>
            <td><span class="badge badge-${e.status}">${e.status}</span></td>
            <td>${esc(e.gmail_account || '—')}</td>
            <td>${e.sent_at ? new Date(e.sent_at).toLocaleString() : '—'}</td>
        </tr>
    `).join('');

    renderPagination('emails-pagination', data.total, state.emailsPage, (p) => { state.emailsPage = p; loadEmails(); });
}

function openEmailPreview(subject, body, type, status, account, sentAt) {
    document.getElementById('preview-subject').textContent = subject || '—';
    document.getElementById('preview-body').textContent = body || '—';
    document.getElementById('preview-type').textContent = type.replace(/_/g, ' ');
    document.getElementById('preview-status').textContent = status;
    document.getElementById('preview-account').textContent = account || '—';
    document.getElementById('preview-sent-at').textContent = sentAt ? new Date(sentAt).toLocaleString() : '—';
    document.getElementById('email-preview-overlay').classList.add('open');
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
//  ANALYTICS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadAnalytics() {
    const data = await apiGet('/stats/optimization');
    if (!data) return;

    document.getElementById('analytics-total-templates').textContent = data.total_templates;
    document.getElementById('analytics-total-uses').textContent = data.total_uses;
    document.getElementById('analytics-total-replies').textContent = data.total_replies;
    document.getElementById('analytics-overall-rate').textContent = `${data.overall_reply_rate}%`;

    const templatesEl = document.getElementById('top-templates');
    if (data.top_performers.length === 0) {
        templatesEl.innerHTML = '<div class="activity-empty">No templates with enough data yet</div>';
    } else {
        templatesEl.innerHTML = data.top_performers.map(t => `
            <div class="template-item">
                <div class="template-info">
                    <div class="template-name">${esc(t.subject)}</div>
                    <div class="template-meta">Used ${t.uses} times · ${t.replies} replies</div>
                </div>
                <div class="template-score">${t.score}%</div>
            </div>
        `).join('');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SLIDE-OVERS
// ═══════════════════════════════════════════════════════════════════════════════

function initSlideOvers() {
    document.getElementById('lead-detail-close')?.addEventListener('click', () => {
        document.getElementById('lead-detail-overlay').classList.remove('open');
    });
    document.getElementById('lead-detail-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'lead-detail-overlay') {
            document.getElementById('lead-detail-overlay').classList.remove('open');
        }
    });

    document.getElementById('email-preview-close')?.addEventListener('click', () => {
        document.getElementById('email-preview-overlay').classList.remove('open');
    });
    document.getElementById('email-preview-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'email-preview-overlay') {
            document.getElementById('email-preview-overlay').classList.remove('open');
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MODALS
// ═══════════════════════════════════════════════════════════════════════════════

function initModals() {
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
    document.getElementById('btn-refresh')?.addEventListener('click', () => {
        const loaders = {
        overview: loadOverview,
            leads: loadLeads, campaigns: loadCampaigns,
            emails: loadEmails, replies: loadReplies, accounts: loadAccounts,
            analytics: loadAnalytics,
        };
        if (loaders[state.currentSection]) loaders[state.currentSection]();
        showToast('info', 'Refreshed');
    });

    document.getElementById('btn-check-replies')?.addEventListener('click', async () => {
        const res = await apiPost('/replies/check');
        if (res) {
            showToast('info', 'Checking Replies', 'Scanning all inboxes...');
        }
    });

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

    document.getElementById('btn-enrich')?.addEventListener('click', async () => {
        const apiKey = await getApiKey();
        const headers = apiKey ? { 'X-API-Key': apiKey } : {};
        const res = await fetch(`${API}/leads/enrich`, { method: 'POST', headers });
        if (res.ok) {
            showToast('info', 'Enrichment Started', 'Running in background...');
        } else {
            showToast('error', 'Request Failed', `HTTP ${res.status}`);
        }
    });

    document.getElementById('btn-generate-emails')?.addEventListener('click', async () => {
        const campaignData = await apiGet('/campaigns');
        const activeCampaign = campaignData?.campaigns?.find(c => c.status === 'active' || c.status === 'paused');
        const campaignId = activeCampaign?.id || null;
        const fd = new FormData();
        fd.append('limit', 50);
        if (campaignId) fd.append('campaign_id', campaignId);
        const res = await apiPost('/emails/generate', fd, true);
        if (res) {
            showToast('info', 'Generation Started', 'AI is writing your emails...');
        }
    });

    document.getElementById('btn-check-followups')?.addEventListener('click', async () => {
        const res = await apiPost('/followups/check', new FormData(), true);
        if (res) {
            showToast('info', 'Follow-Up Check', 'Queuing eligible follow-ups...');
        }
    });

    document.getElementById('btn-health-check')?.addEventListener('click', async () => {
        const res = await apiPost('/accounts/health-check');
        if (res) {
            showToast('info', 'Health Check', `${res.healthy} healthy, ${res.unhealthy} unhealthy`);
            loadAccounts();
        }
    });

    document.getElementById('lead-status-filter')?.addEventListener('change', () => { state.leadsPage = 1; loadLeads(); });
    document.getElementById('email-status-filter')?.addEventListener('change', () => { state.emailsPage = 1; loadEmails(); });
    document.getElementById('email-type-filter')?.addEventListener('change', () => { state.emailsPage = 1; loadEmails(); });
    document.getElementById('reply-class-filter')?.addEventListener('change', () => { state.repliesPage = 1; loadReplies(); });

    document.getElementById('lead-search')?.addEventListener('input', debounce((e) => {
        state.leadSearchQuery = e.target.value;
        state.leadsPage = 1;
        loadLeads();
    }, 300));
}

// ═══════════════════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════════════════

function esc(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function debounce(fn, ms) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}

function renderPagination(containerId, total, currentPage, onPageChange) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const totalPages = Math.ceil(total / state.perPage);
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = '';
    html += `<button ${currentPage <= 1 ? 'disabled' : ''}>Prev</button>`;

    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage < maxVisible - 1) startPage = Math.max(1, endPage - maxVisible + 1);

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }

    html += `<button ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>`;
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
