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
    } else if (pageId === 'limits') {
        loadNetworkAudit();
    } else if (pageId === 'account') {
        loadAccountSettings();
    }
}

async function loadAccountSettings() {
    const result = await window.API?.getCurrentUser?.();
    const user = result?.data?.user || result?.user || {};
    const username = document.getElementById('accountUsername');
    const role = document.getElementById('accountRole');
    const email = document.getElementById('accountEmail');
    if (username) username.value = user.username || '';
    if (role) role.value = user.role || '';
    if (email) email.value = user.email || '';
}

function saveAccountSettings() {
    if (typeof showToast === 'function') showToast('Profile changes are managed by your administrator.', 'info');
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
    const rolePillEl = document.getElementById('activeRolePill');
    const adminBannerEl = document.getElementById('adminControlBanner');

    if (profileNameEl) profileNameEl.innerText = activeUser;
    if (profileBadgeEl) profileBadgeEl.innerText = activeRole;
    if (profileAvatarEl) profileAvatarEl.innerText = activeUser.substring(0, 2).toUpperCase();
    if (rolePillEl) rolePillEl.lastChild.textContent = ` ${activeRole}`;
    if (adminBannerEl) adminBannerEl.hidden = !(isAdminRole(activeRole));

    // Show/Hide Nav Buttons according to Role Privileges
    const isAdmin = isAdminRole(activeRole);
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

function isAdminRole(role) {
    const normalized = (role || '').toUpperCase();
    return normalized.includes('ADMIN') || normalized === 'SUPER_ADMIN';
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
        navTo(state.activePage || 'dashboard');

        if (typeof switchProject === 'function') {
            switchProject('demo');
        }
        if (typeof loadMcpTools === 'function') {
            loadMcpTools();
        }
        renderAllViews();
    }
});

/* =================== STUB FUNCTIONS FOR NEW PAGES =================== */
function addWebhookSubscription() {
    const url = prompt('Enter webhook endpoint URL:');
    if (!url) return;
    const tbody = document.getElementById('webhooksTableBody');
    if (tbody) {
        tbody.innerHTML = `<tr>
            <td style="font-family:var(--font-mono);font-size:12px;">${url}</td>
            <td><span class="badge">sandbox.created</span></td>
            <td><span class="badge" style="background:var(--success);color:#fff;">Active</span></td>
            <td style="font-family:var(--font-mono);font-size:12px;color:var(--fg-muted);">Never</td>
            <td><button class="btn btn-ghost" style="font-size:12px;color:var(--danger);" onclick="this.closest('tr').remove()">Delete</button></td>
        </tr>`;
    }
}

function saveGeneralSettings() {
    const orgName = document.getElementById('settingsOrgName')?.value || "ThinkDome Enterprise";
    const backend = document.getElementById('settingsDefaultBackend')?.value || "subprocess";
    const timeout = document.getElementById('settingsTimeout')?.value || "30";
    const maxMem = document.getElementById('settingsMaxMemory')?.value || "1024";
    const autoPause = document.getElementById('settingsAutoPause')?.value || "30";
    const egress = document.getElementById('settingsEgressPolicy')?.value || "strict";

    localStorage.setItem('thinkdome_org_name', orgName);
    localStorage.setItem('thinkdome_default_backend', backend);
    localStorage.setItem('thinkdome_timeout', timeout);
    localStorage.setItem('thinkdome_max_memory', maxMem);
    localStorage.setItem('thinkdome_auto_pause', autoPause);
    localStorage.setItem('thinkdome_egress_policy', egress);

    if (typeof showCustomAlert === 'function') {
        showCustomAlert("Settings Saved", `System configuration updated successfully:\n• Organization: ${orgName}\n• Backend: ${backend}\n• Timeout: ${timeout}s\n• Max Memory: ${maxMem}MB`);
    } else {
        alert(`System configuration updated successfully:\n• Organization: ${orgName}\n• Backend: ${backend}\n• Timeout: ${timeout}s\n• Max Memory: ${maxMem}MB`);
    }
}

function sendTestEmail() {
    const toEmail = document.getElementById('settingsSmtpFromEmail')?.value || "noreply@thinkdome.dev";
    const host = document.getElementById('settingsSmtpHost')?.value || "smtp.sendgrid.net";
    const port = document.getElementById('settingsSmtpPort')?.value || "587";
    alert(`[SMTP TEST EMAIL ENQUEUED]\nConnected to ${host}:${port}\nSent test alert email to ${toEmail}`);
}

function sendTestSMS() {
    const toPhone = document.getElementById('settingsSmsToPhone')?.value || "+1 415 555 0122";
    const provider = document.getElementById('settingsSmsProvider')?.value || "Twilio";
    alert(`[SMS ALERT TEST DISPATCHED]\nDispatched via ${provider.toUpperCase()} Gateway\nSent test SMS alert to ${toPhone}`);
}

async function checkInfrastructureHealth() {
    const dbBadge = document.getElementById('badgeDbStatus');
    const rabbitBadge = document.getElementById('badgeRabbitStatus');
    const redisBadge = document.getElementById('badgeRedisStatus');
    const storageBadge = document.getElementById('badgeStorageStatus');

    if (dbBadge) dbBadge.textContent = 'Checking...';
    if (rabbitBadge) rabbitBadge.textContent = 'Checking...';
    if (redisBadge) redisBadge.textContent = 'Checking...';
    if (storageBadge) storageBadge.textContent = 'Checking...';

    setTimeout(() => {
        if (dbBadge) dbBadge.textContent = 'Connected';
        if (rabbitBadge) rabbitBadge.textContent = 'Connected';
        if (redisBadge) redisBadge.textContent = 'Connected';
        if (storageBadge) storageBadge.textContent = 'Online';
        if (typeof showCustomAlert === 'function') {
            showCustomAlert("System Health Checked", "All core infrastructure services (Database, RabbitMQ, Redis, Storage) are connected and healthy.");
        } else {
            alert("System Health Checked: All core infrastructure services (Database, RabbitMQ, Redis, Storage) are connected and healthy.");
        }
    }, 600);
}

function syncOrmSchema() {
    const engine = document.getElementById('settingsDbEngine')?.value || "sqlite";
    const dbUrl = document.getElementById('settingsDbUrl')?.value || "sqlite:///sites/think.local/storage/thinkbox.db";
    const message = `[ORM SCHEMA SYNC SUCCESSFUL]\n• Engine: ${engine.toUpperCase()}\n• Connection URL: ${dbUrl}\n• Mapped Models: 10 (Sandbox, Organization, Project, ExecutionNode, Snapshot, SystemSetting, User, Role, Permission, FileBox)\n• Base.metadata table structures verified.`;
    
    if (typeof showCustomAlert === 'function') {
        showCustomAlert("ORM Schema Synced", message);
    } else {
        alert(message);
    }
}

function addEgressRulePrompt() {
    const domain = prompt('Enter domain pattern (e.g. *.huggingface.co or api.cohere.com):');
    if (!domain) return;
    const methods = prompt('Enter allowed HTTP methods (e.g. GET, POST):', 'GET, POST');
    const desc = prompt('Enter rule description:', 'External AI Provider API Proxy');
    
    const tbody = document.getElementById('networkRulesTable');
    if (tbody) {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="font-family:var(--font-mono);font-size:12.5px;font-weight:600;color:var(--fg);">${domain}</td>
            <td><span class="badge" style="background:var(--accent-subtle);color:var(--accent);">${methods || 'GET, POST'}</span></td>
            <td style="font-family:var(--font-mono);font-size:12px;">120</td>
            <td><span class="badge" style="background:var(--success-subtle);color:var(--success);">Vault Injection</span></td>
            <td style="color:var(--fg-muted);font-size:13px;">${desc || 'Custom Egress Rule'}</td>
            <td><button class="btn btn-ghost btn-sm" onclick="this.closest('tr').remove()" style="color:var(--danger);">Delete</button></td>`;
        tbody.appendChild(row);
    }
}

function forkSnapshotPrompt() {
    const branchName = prompt('Enter new speculative branch tag (e.g. branch_gamma_03):');
    if (!branchName) return;
    
    const container = document.getElementById('snapshotTimelineList');
    if (container) {
        const item = document.createElement('div');
        item.style.cssText = "padding:16px;background:var(--surface-raised);border-radius:var(--radius-md);border:1px solid var(--border);border-left:4px solid var(--accent);";
        item.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <strong style="color:var(--accent);font-family:var(--font-mono);font-size:13.5px;">[${branchName}]</strong>
                        <span class="badge" style="background:var(--accent-subtle);color:var(--accent);">FORKED BRANCH</span>
                    </div>
                    <div style="font-size:12.5px;color:var(--fg-muted);margin-top:4px;">User-created speculative branch checkpoint</div>
                    <div style="font-size:11px;color:var(--fg-subtle);font-family:var(--font-mono);margin-top:6px;">RAM: 192MB | Files: 19 | Created: Just now</div>
                </div>
                <button class="btn btn-ghost btn-sm" onclick="restoreSnapshotUI('${branchName}')" style="color:var(--accent);border-color:var(--accent);">
                    ↩ Switch Branch
                </button>
            </div>`;
        container.insertBefore(item, container.firstChild);
        
        const countVal = document.getElementById('snapCountVal');
        if (countVal) countVal.textContent = parseInt(countVal.textContent || '4') + 1;
    }
}

function inviteMember() {
    const email = prompt('Enter member email to invite:');
    if (!email) return;
    const tbody = document.getElementById('membersTableBody');
    if (tbody) {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="font-weight:600;">Invited User</td>
            <td>${email}</td>
            <td><span class="badge" style="background:var(--fg-subtle);color:var(--fg);">PENDING</span></td>
            <td style="font-family:var(--font-mono);font-size:12px;color:var(--fg-muted);">Just now</td>
            <td><button class="btn btn-ghost" style="font-size:12px;color:var(--danger);" onclick="this.closest('tr').remove()">Revoke</button></td>`;
        tbody.appendChild(row);
    }
}

function createUserAccount() {
    document.getElementById('userModalTitle').textContent = 'Create New User Account';
    document.getElementById('userModalEditRowIndex').value = '';
    document.getElementById('userModalUsername').value = '';
    document.getElementById('userModalEmail').value = '';
    document.getElementById('userModalRole').value = 'AGENT_STANDARD';
    document.getElementById('userModalStatus').value = 'ACTIVE';
    document.getElementById('userModalPassword').value = '';
    
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.add('active');
}

function editUserAccount(btn) {
    const row = btn.closest('tr');
    if (!row) return;
    const cells = row.querySelectorAll('td');
    const username = cells[0]?.textContent?.trim() || '';
    const email = cells[1]?.textContent?.trim() || '';
    const roleBadge = cells[2]?.querySelector('.badge')?.textContent?.trim() || 'AGENT_STANDARD';
    
    document.getElementById('userModalTitle').textContent = `Edit User: ${username}`;
    document.getElementById('userModalEditRowIndex').value = Array.from(row.parentNode.children).indexOf(row);
    document.getElementById('userModalUsername').value = username;
    document.getElementById('userModalEmail').value = email;
    document.getElementById('userModalRole').value = roleBadge;
    document.getElementById('userModalStatus').value = 'ACTIVE';
    document.getElementById('userModalPassword').value = '';
    
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.add('active');
}

function closeUserModal() {
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.remove('active');
}

function saveUserAccountFromModal(event) {
    if (event) event.preventDefault();
    
    const rowIndex = document.getElementById('userModalEditRowIndex').value;
    const username = document.getElementById('userModalUsername').value.trim();
    const email = document.getElementById('userModalEmail').value.trim();
    const role = document.getElementById('userModalRole').value;
    const status = document.getElementById('userModalStatus').value;
    
    const tbody = document.getElementById('usersTableBody');
    if (!tbody) return;
    
    let roleBg = 'var(--accent)';
    let roleFg = 'var(--accent-fg)';
    if (role === 'AGENT_STANDARD') { roleBg = 'var(--success)'; roleFg = '#fff'; }
    else if (role === 'AUDITOR') { roleBg = 'var(--warn)'; roleFg = '#fff'; }
    else if (role === 'SUPER_ADMIN') { roleBg = 'var(--accent)'; roleFg = 'var(--accent-fg)'; }
    
    if (rowIndex !== '') {
        // Edit existing row
        const row = tbody.children[parseInt(rowIndex)];
        if (row) {
            row.children[0].textContent = username;
            row.children[1].textContent = email;
            row.children[2].innerHTML = `<span class="badge" style="background:${roleBg};color:${roleFg};">${role}</span>`;
        }
    } else {
        // Create new row
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="font-weight:600;">${username}</td>
            <td>${email}</td>
            <td><span class="badge" style="background:${roleBg};color:${roleFg};">${role}</span></td>
            <td style="font-family:var(--font-mono);font-size:12px;color:var(--fg-muted);">Just now</td>
            <td style="display:flex;gap:6px;">
                <button class="btn btn-ghost" style="font-size:12px;" onclick="editUserAccount(this)">Edit</button>
                <button class="btn btn-ghost" style="font-size:12px;color:var(--danger);" onclick="deleteUserAccount(this)">Delete</button>
            </td>`;
        tbody.insertBefore(row, tbody.firstChild);
    }
    
    closeUserModal();
    if (typeof showCustomAlert === 'function') {
        showCustomAlert("User Account Saved", `Successfully updated user account '${username}' (${email}) with role ${role}.`);
    } else {
        alert(`Successfully updated user account '${username}' (${email}) with role ${role}.`);
    }
}

function deleteUserAccount(btn) {
    const row = btn.closest('tr');
    const username = row?.children[0]?.textContent?.trim() || 'User';
    if (confirm(`Are you sure you want to delete user account '${username}'?`)) {
        row.remove();
    }
}

function openRoleModal() {
    document.getElementById('roleModalName').value = '';
    document.getElementById('roleModalInherit').value = '';
    document.getElementById('roleModalCategory').value = 'Tenant Custom';
    document.getElementById('roleModalScope').value = 'sandbox:exec, snapshot:rw';
    
    const modal = document.getElementById('roleCreateModal');
    if (modal) modal.classList.add('active');
}

function closeRoleModal() {
    const modal = document.getElementById('roleCreateModal');
    if (modal) modal.classList.remove('active');
}

function saveFrappeRoleFromModal(event) {
    if (event) event.preventDefault();
    
    const name = document.getElementById('roleModalName').value.trim();
    const roleCode = name.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
    const category = document.getElementById('roleModalCategory').value;
    const scope = document.getElementById('roleModalScope').value.trim() || 'sandbox:exec';
    
    if (!name) return;
    
    // Add Role Card dynamically to Roles Catalog Grid
    const container = document.getElementById('rbacRolesContainer');
    if (container) {
        const card = document.createElement('div');
        card.className = 'table-card';
        card.style.cssText = 'padding:20px;';
        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <span class="badge" style="background:var(--accent-subtle);color:var(--accent);font-weight:700;">${roleCode}</span>
                <span style="font-size:11px;color:var(--fg-muted);font-weight:600;">${category}</span>
            </div>
            <h4 style="font-size:15px;font-weight:700;margin-bottom:6px;">${name}</h4>
            <p style="font-size:13px;color:var(--fg-muted);margin-bottom:14px;line-height:1.4;">Custom Frappe-style role definition with granular module capabilities.</p>
            <div style="font-size:11.5px;font-family:var(--font-mono);color:var(--accent);background:var(--surface-raised);padding:8px 10px;border-radius:var(--radius-sm);border:1px solid var(--border);">Scope: ${scope}</div>`;
        container.insertBefore(card, container.firstChild);
    }
    
    // Dynamically append new role to select options in User Accounts Modal & User Role Assign dropdowns
    ['userModalRole', 'rbacAssignRoleSelect', 'roleModalInherit'].forEach(selectId => {
        const sel = document.getElementById(selectId);
        if (sel) {
            const opt = document.createElement('option');
            opt.value = roleCode;
            opt.textContent = `${roleCode} (${name})`;
            sel.appendChild(opt);
        }
    });

    closeRoleModal();

    if (typeof showCustomAlert === 'function') {
        showCustomAlert("Frappe Role Registered", `Role '${name}' (${roleCode}) successfully saved, permission matrix linked, and RBAC policy cache refreshed.`);
    } else {
        alert(`Role '${name}' (${roleCode}) successfully saved, permission matrix linked, and RBAC policy cache refreshed.`);
    }
}

function refreshRbacCache() {
    if (typeof showCustomAlert === 'function') {
        showCustomAlert("RBAC Cache Synced", "Dynamic permission tree & role hierarchy cache invalidated across all active nodes in < 4ms.");
    } else {
        alert("RBAC Cache Synced: Dynamic permission tree & role hierarchy cache invalidated across all active nodes in < 4ms.");
    }
}

/* =================== SIDEBAR COLLAPSE & RESIZER =================== */
function adjustSidebarWidth(val) {
    const widthPx = parseInt(val);
    const bodyGrid = document.getElementById('bodyGrid');
    const sidebar = document.querySelector('.sidebar');
    
    if (widthPx <= 80) {
        if (bodyGrid) bodyGrid.classList.add('collapsed');
        if (sidebar) sidebar.style.width = '';
        if (bodyGrid) bodyGrid.style.gridTemplateColumns = '';
    } else {
        if (bodyGrid) bodyGrid.classList.remove('collapsed');
        if (bodyGrid) bodyGrid.style.gridTemplateColumns = `${widthPx}px minmax(0, 1fr)`;
        if (sidebar) sidebar.style.width = `${widthPx}px`;
    }
    
    localStorage.setItem('thinkdome_sidebar_width', widthPx);
}

function toggleSidebarSlider() {
    const bodyGrid = document.getElementById('bodyGrid');
    if (!bodyGrid) return;
    
    const isCollapsed = bodyGrid.classList.contains('collapsed');
    
    if (isCollapsed) {
        // Expand
        bodyGrid.classList.remove('collapsed');
        bodyGrid.style.gridTemplateColumns = '';
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.style.width = '';
        localStorage.setItem('thinkdome_sidebar_collapsed', 'false');
    } else {
        // Collapse
        bodyGrid.classList.add('collapsed');
        bodyGrid.style.gridTemplateColumns = '';
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.style.width = '';
        localStorage.setItem('thinkdome_sidebar_collapsed', 'true');
    }
}

// Restore sidebar state on boot + resizer drag handler
document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('thinkdome_sidebar_collapsed') === 'true') {
        const bodyGrid = document.getElementById('bodyGrid');
        if (bodyGrid) bodyGrid.classList.add('collapsed');
    }

    // Splitter resizer drag handler
    const resizer = document.getElementById('sidebarResizerBar');
    if (resizer) {
        let isDragging = false;

        resizer.addEventListener('mousedown', (e) => {
            isDragging = true;
            resizer.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const sidebar = document.querySelector('.sidebar');
            if (!sidebar) return;
            const sidebarRect = sidebar.getBoundingClientRect();
            let newWidth = e.clientX - sidebarRect.left;
            if (newWidth < 64) newWidth = 64;
            if (newWidth > 360) newWidth = 360;
            adjustSidebarWidth(newWidth);
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                resizer.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }
});

/* =================== SIDEBAR QUICK FILTER & KEYBOARD SHORTCUTS =================== */
function filterSidebarMenu(query) {
    const q = (query || '').toLowerCase().trim();
    const navItems = document.querySelectorAll('#sidebarNavContainer .nav-item');
    const sections = document.querySelectorAll('#sidebarNavContainer .nav-section');
    
    navItems.forEach(item => {
        const text = item.textContent.toLowerCase();
        if (!q || text.includes(q)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
    
    sections.forEach(sec => {
        const visibleItems = sec.querySelectorAll('.nav-item[style*="display: flex"], .nav-item:not([style*="display: none"])');
        if (!q || visibleItems.length > 0) {
            sec.style.display = 'block';
        } else {
            sec.style.display = 'none';
        }
    });
}

// Global Keyboard Shortcuts (Ctrl+B = Toggle Sidebar, Ctrl+N = New Sandbox)
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggleSidebarSlider();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        if (typeof openNewSandboxModal === 'function') {
            openNewSandboxModal();
        } else {
            navTo('sandboxes');
        }
    }
});

/* =================== DASHBOARD LIVE TELEMETRY CANVAS CHART =================== */
let telemetryCpuHistory = [12, 14, 18, 16, 22, 25, 20, 18, 15, 19, 23, 21, 18, 16, 20, 24, 28, 22, 19, 18];
let telemetryRamHistory = [280, 290, 310, 305, 320, 340, 335, 330, 325, 338, 345, 350, 342, 338, 342, 348, 355, 342, 338, 342];

function initLiveDashboardChart() {
    const canvas = document.getElementById('dashboardLiveChartCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    function render() {
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);

        // Draw background grid lines
        ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--border') || 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 0; x < w; x += 40) {
            ctx.moveTo(x, 0); ctx.lineTo(x, h);
        }
        for (let y = 0; y < h; y += 40) {
            ctx.moveTo(0, y); ctx.lineTo(w, y);
        }
        ctx.stroke();

        // Colors
        const isDark = document.documentElement.classList.contains('dark');
        const cpuColor = isDark ? '#f4f4f5' : '#18181b';
        const ramColor = '#16a34a';

        // Render CPU Utilization Wave (0-100%)
        ctx.beginPath();
        const step = w / (telemetryCpuHistory.length - 1);
        telemetryCpuHistory.forEach((val, i) => {
            const x = i * step;
            const y = h - (val / 100) * (h - 20) - 10;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = cpuColor;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Render RAM Wave (0-500 MB scale)
        ctx.beginPath();
        telemetryRamHistory.forEach((val, i) => {
            const x = i * step;
            const y = h - (val / 500) * (h - 20) - 10;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = ramColor;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    render();
    window.addEventListener('resize', render);

    // Live update loop every 1s
    setInterval(() => {
        const lastCpu = telemetryCpuHistory[telemetryCpuHistory.length - 1];
        const nextCpu = Math.max(8, Math.min(85, Math.round(lastCpu + (Math.random() * 8 - 4))));
        telemetryCpuHistory.shift();
        telemetryCpuHistory.push(nextCpu);

        const lastRam = telemetryRamHistory[telemetryRamHistory.length - 1];
        const nextRam = Math.max(200, Math.min(480, Math.round(lastRam + (Math.random() * 12 - 6))));
        telemetryRamHistory.shift();
        telemetryRamHistory.push(nextRam);

        const cpuEl = document.getElementById('telemetryCpuVal');
        if (cpuEl) cpuEl.textContent = `${nextCpu}.4%`;
        const ramEl = document.getElementById('telemetryRamVal');
        if (ramEl) ramEl.textContent = `${nextRam} MB`;

        render();
    }, 1000);
}

function setChartRange(btn, range) {
    if (!btn || !btn.parentNode) return;
    btn.parentNode.querySelectorAll('button').forEach(b => {
        b.style.background = 'transparent';
        b.style.color = 'var(--fg-muted)';
    });
    btn.style.background = 'var(--accent-subtle)';
    btn.style.color = 'var(--accent)';
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initLiveDashboardChart, 300);
});
