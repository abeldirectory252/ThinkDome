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
    }
}

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
