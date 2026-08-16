// static/js/app.js

/* =================== SIDEBAR & PAGES SWITCHING =================== */
function navTo(pageId) {
    state.activePage = pageId;
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.page === pageId);
    });
    document.querySelectorAll('.page').forEach(sec => {
        sec.classList.add('hidden');
    });
    const pageEl = document.getElementById('page-' + pageId);
    if (pageEl) pageEl.classList.remove('hidden');

    // Custom redraws per page if required
    if (pageId === 'console') {
        const drawer = document.querySelector('.terminal-drawer');
        const toggleBtn = document.getElementById('btn-toggle-terminal');
        if (drawer && drawer.classList.contains('closed')) {
            drawer.classList.remove('closed');
            if (toggleBtn) toggleBtn.classList.add('active');
        }

        if (typeof editorInstance !== 'undefined' && editorInstance) {
            editorInstance.layout();
        }
        if (typeof focusTerminalInput === 'function') {
            focusTerminalInput();
        }
    } else if (pageId === 'mcp') {
        if (typeof loadMcpTools === 'function') {
            loadMcpTools();
        }
    } else if (pageId === 'network') {
        loadNetworkAudit();
    }
}

async function loadNetworkAudit() {
    try {
        const [statsRes, auditRes, rulesRes] = await Promise.all([
            fetch('/v1/network/stats').then(r => r.json()).catch(() => ({})),
            fetch('/v1/network/audit-log?limit=50').then(r => r.json()).catch(() => ({ audit_log: [] })),
            fetch('/v1/network/rules').then(r => r.json()).catch(() => ({ rules: [] })),
        ]);

        // 1. KPI Cards
        const totalEl = document.getElementById('net-total-eval');
        if (totalEl) totalEl.textContent = statsRes.total_evaluations || 0;
        const allowedEl = document.getElementById('net-allowed-count');
        if (allowedEl) allowedEl.textContent = statsRes.allowed || 0;
        const deniedEl = document.getElementById('net-denied-count');
        if (deniedEl) deniedEl.textContent = statsRes.denied || 0;
        const rulesEl = document.getElementById('net-rules-count');
        if (rulesEl) rulesEl.textContent = statsRes.total_rules || (rulesRes.rules ? rulesRes.rules.length : 0);

        // 2. Audit Table
        const auditTable = document.getElementById('networkAuditTable');
        if (auditTable) {
            const logs = auditRes.audit_log || [];
            if (!logs.length) {
                auditTable.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--fg-subtle);padding:24px;">No network egress activity recorded yet.</td></tr>`;
            } else {
                auditTable.innerHTML = logs.map(e => {
                    const ts = new Date(e.timestamp * 1000).toLocaleString();
                    const statusBadge = e.allowed
                        ? `<span class="badge badge-success" style="background:rgba(16,185,129,0.15);color:#10b981;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">ALLOWED</span>`
                        : `<span class="badge badge-danger" style="background:rgba(239,68,68,0.15);color:#ef4444;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">DENIED</span>`;
                    return `
                        <tr>
                            <td style="font-family:var(--font-mono);font-size:12px;">${ts}</td>
                            <td style="font-weight:600;">${e.sandbox_id || 'global'}</td>
                            <td><span style="background:var(--bg-card);padding:2px 6px;border-radius:4px;font-size:11px;">${e.method || 'GET'}</span></td>
                            <td style="font-family:var(--font-mono);font-size:12px;color:var(--accent);">${e.url || e.domain}</td>
                            <td>${statusBadge}</td>
                            <td style="font-size:12px;color:var(--fg-muted);">${e.reason || e.matched_rule || 'Default Deny'}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // 3. Rules Table
        const rulesTable = document.getElementById('networkRulesTable');
        if (rulesTable) {
            const rules = rulesRes.rules || [];
            if (!rules.length) {
                rulesTable.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--fg-subtle);padding:24px;">No egress domain rules configured.</td></tr>`;
            } else {
                rulesTable.innerHTML = rules.map(r => `
                    <tr>
                        <td style="font-family:var(--font-mono);font-weight:600;color:var(--accent);">${r.domain_pattern}</td>
                        <td>${(r.methods || []).map(m => `<span style="background:var(--bg-card);padding:2px 6px;border-radius:4px;font-size:11px;">${m}</span>`).join(' ')}</td>
                        <td>${r.max_requests_per_min || 300}/min</td>
                        <td>${r.has_injected_credentials ? '<span style="color:var(--warn);font-size:12px;">🔐 Vault Injected</span>' : 'None'}</td>
                        <td style="font-size:12px;color:var(--fg-muted);">${r.description || 'Allow rule'}</td>
                    </tr>
                `).join('');
            }
        }
    } catch (err) {
        console.error('Failed to load network audit:', err);
    }
}
window.loadNetworkAudit = loadNetworkAudit;

/* =================== DYNAMIC RENDERING CONTROLLER =================== */
function renderAllViews() {
    if (typeof renderDashboardRecentTables === 'function') renderDashboardRecentTables();
    if (typeof renderSandboxNodesTable === 'function') renderSandboxNodesTable();
    if (typeof updateSandboxCardsHTML === 'function') updateSandboxCardsHTML();
    if (typeof renderBillingReport === 'function') renderBillingReport();
    if (typeof renderApiKeys === 'function') renderApiKeys();
    if (typeof renderFileExplorer === 'function') renderFileExplorer();
    if (typeof renderTabs === 'function') renderTabs();
    if (typeof renderActiveFileContent === 'function') renderActiveFileContent();
    if (typeof renderLogsPane === 'function') renderLogsPane();
    if (typeof updateTerminalLabel === 'function') updateTerminalLabel();
    if (typeof updateTerminalPromptPath === 'function') updateTerminalPromptPath();
    if (typeof renderProjectDropdown === 'function') renderProjectDropdown();
    if (typeof renderSbxDropdowns === 'function') renderSbxDropdowns();
    if (typeof loadMcpTools === 'function') loadMcpTools();
}

/* =================== ROLE-BASED UI ADAPTATION ENGINE =================== */
function applyRoleBasedUINavigation(role, username) {
    const activeRole = (role || localStorage.getItem('thinkdome_user_role') || 'AGENT_STANDARD').toUpperCase();
    const activeUser = username || localStorage.getItem('thinkdome_username') || 'User';

    // Update Profile Footer
    const profileNameEl = document.querySelector('.profile-name');
    const profileBadgeEl = document.querySelector('.profile-badge');
    const profileAvatarEl = document.querySelector('.profile-avatar');

    if (profileNameEl) profileNameEl.innerText = activeUser;
    if (profileBadgeEl) profileBadgeEl.innerText = activeRole;
    if (profileAvatarEl) profileAvatarEl.innerText = activeUser.substring(0, 2).toUpperCase();

    // Show/Hide Nav Buttons according to Role Privileges
    const isAdmin = activeRole.includes('ADMIN') || activeRole === 'SUPER_ADMIN';
    const isAuditor = activeRole.includes('AUDIT');
    const isFinance = activeRole.includes('FINANCE');

    document.querySelectorAll('.nav-item').forEach(btn => {
        const page = btn.dataset.page;
        if (page === 'roles' || page === 'apikeys' || page === 'billing') {
            btn.style.display = (isAdmin || isFinance) ? 'flex' : 'none';
        } else if (page === 'audit') {
            btn.style.display = (isAdmin || isAuditor) ? 'flex' : 'none';
        } else {
            btn.style.display = 'flex';
        }
    });
}

async function submitUserRoleAssignment() {
    const userId = document.getElementById('rbacAssignUserId')?.value.trim();
    const roleId = document.getElementById('rbacAssignRoleSelect')?.value;
    const token = localStorage.getItem('thinkdome_token');

    if (!userId || !roleId) {
        alert("Please enter a User ID and select a Role.");
        return;
    }

    if (window.API && typeof window.API.assignUserRole === 'function') {
        const { data, error } = await window.API.assignUserRole(userId, roleId, token);
        if (error) {
            alert("Role assignment failed: " + error);
        } else {
            alert(`Successfully assigned role '${roleId}' to user '${userId}'!`);
        }
    }
}

/* =================== AUTO RUN LOAD ON READY =================== */
window.addEventListener('DOMContentLoaded', () => {
    const appView = document.getElementById('appView');
    const isLoggedIn = localStorage.getItem('thinkdome_logged_in') === 'true';
    if (appView && isLoggedIn) {
        const role = localStorage.getItem('thinkdome_user_role') || 'AGENT_STANDARD';
        const user = localStorage.getItem('thinkdome_username') || 'User';
        applyRoleBasedUINavigation(role, user);

        if (typeof switchProject === 'function') {
            switchProject('demo');
        }
        renderAllViews();
    }
});
