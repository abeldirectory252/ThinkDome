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
}

/* =================== AUTO RUN LOAD ON READY =================== */
window.addEventListener('DOMContentLoaded', () => {
    // Only initialize workspace if the user is verified to be logged in and appView is present
    const appView = document.getElementById('appView');
    const isLoggedIn = localStorage.getItem('thinkdome_logged_in') === 'true';
    if (appView && isLoggedIn) {
        if (typeof switchProject === 'function') {
            switchProject('demo');
        }
        renderAllViews();
    }
});
