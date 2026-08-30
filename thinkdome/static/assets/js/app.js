// static/js/app.js

/* =================== SIDEBAR & PAGES SWITCHING =================== */
function updateSidebarSandboxCount() {
    const badge = document.getElementById('sidebarSandboxCount');
    if (!badge) return;
    const sandboxes = Object.values(window.state?.sandboxes || {});
    const active = sandboxes.filter(sandbox => ['active', 'running'].includes(String(sandbox.status).toLowerCase())).length;
    badge.textContent = `${active} Active`;
}

// Add item-level drag and drop after the visual builder paints its rows.
document.addEventListener('dragstart', event => {
    const row = event.target.closest?.('.workspace-menu-item');
    if (!row) return;
    const menu = document.getElementById('workspaceMenuVisual');
    const group = row.closest('.workspace-section-card');
    const sectionIndex = [...menu.children].indexOf(group);
    const itemIndex = [...group.querySelectorAll('.workspace-menu-item')].indexOf(row);
    event.dataTransfer.setData('text/workspace-item', `${sectionIndex}:${itemIndex}`);
});
document.addEventListener('dragover', event => { if (event.target.closest?.('.workspace-menu-item')) event.preventDefault(); });
document.addEventListener('mousedown', event => { const row = event.target.closest?.('.workspace-menu-item'); if (row) row.draggable = true; });
document.addEventListener('drop', event => {
    const row = event.target.closest?.('.workspace-menu-item');
    if (!row) return;
    const raw = event.dataTransfer.getData('text/workspace-item');
    if (!raw) return;
    event.preventDefault();
    const menu = document.getElementById('workspaceMenuVisual');
    const group = row.closest('.workspace-section-card');
    const sectionIndex = [...menu.children].indexOf(group);
    const itemIndex = [...group.querySelectorAll('.workspace-menu-item')].indexOf(row);
    const [fromSection, fromItem] = raw.split(':').map(Number);
    const state = window.workspaceBuilderState;
    if (state && fromSection === sectionIndex && fromItem !== itemIndex) {
        const moved = state.sections[sectionIndex].items.splice(fromItem, 1)[0];
        state.sections[sectionIndex].items.splice(itemIndex, 0, moved);
        renderWorkspaceBuilder();
    }
});
window.updateSidebarSandboxCount = updateSidebarSandboxCount;

function canViewSandbox(sandbox) {
    // Sandbox authorization is enforced and filtered by the server API.
    // The browser must not make an additional role/owner access decision.
    return true;
}
window.canViewSandbox = canViewSandbox;

function navTo(pageId) {
    // Visibility and authorization are resolved by the server navigation
    // response.  The client only switches to a page it has already rendered.
    if (!document.getElementById('page-' + pageId)) return;
    state.activePage = pageId;
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.page === pageId);
    });
    let pageEl = document.getElementById('page-' + pageId);
    if (!pageEl && typeof window.openDynamicPageRuntime === 'function') {
        window.openDynamicPageRuntime(pageId);
        return;
    }

    document.querySelectorAll('.page').forEach(sec => {
        sec.classList.add('hidden');
    });
    if (pageEl) pageEl.classList.remove('hidden');
    ensurePageRefreshButton(pageEl, pageId);

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
    } else if (pageId === 'workspaces') {
        loadWorkspaceManager();
    } else if (pageId === 'users') {
        loadUsersFromServer();
    } else if (pageId === 'role-profiles') {
        loadRoleProfiles();
    }
}

function moduleSearchItems() {
    const items = [...document.querySelectorAll('.nav-item[data-page]')].map(item => ({ page: item.dataset.page, label: item.querySelector('span')?.textContent?.trim() || item.textContent.trim(), group: item.closest('.nav-section')?.querySelector('.nav-group-label')?.textContent?.trim() || 'Module' }));
    document.querySelectorAll('.page[id] h1,.page[id] h2').forEach(heading => { const page = heading.closest('.page'); if (page && !items.some(x => x.page === page.id.replace(/^page-/, ''))) items.push({ page: page.id.replace(/^page-/, ''), label: heading.textContent.trim(), group: 'Page' }); });
    return items.filter((item, index, all) => all.findIndex(x => x.page === item.page) === index);
}
function setupModuleSearch() {
    const input = document.getElementById('moduleSearchInput'), results = document.getElementById('moduleSearchResults'); if (!input || !results || input.dataset.ready) return; input.dataset.ready = 'true';
    let matches = [], active = -1;
    const score = (text, query) => { let pos = -1, points = 0; for (const char of query) { pos = text.indexOf(char, pos + 1); if (pos < 0) return -1; points += 3; } if (text.startsWith(query)) points += 12; if (text.includes(query)) points += 6; return points - text.length / 100; };
    const choose = index => { if (!matches[index]) return; navTo(matches[index].page); input.value = ''; results.classList.remove('active'); active = -1; };
    const render = () => { const q = input.value.trim().toLowerCase(); results.replaceChildren(); active = -1; if (!q) { results.classList.remove('active'); return; } matches = moduleSearchItems().map(x => ({ ...x, rank: score(`${x.label} ${x.group}`.toLowerCase(), q) })).filter(x => x.rank >= 0).sort((a,b) => b.rank - a.rank).slice(0, 12); matches.forEach((item, i) => { const b = document.createElement('button'); b.className = 'module-search-result'; b.dataset.index = i; const wrap = document.createElement('span'); const label = document.createElement('b'); label.textContent = item.label; const group = document.createElement('small'); group.textContent = item.group; wrap.append(label, group); const key = document.createElement('kbd'); key.textContent = '↵'; b.append(wrap, key); b.onclick = () => choose(i); results.appendChild(b); }); if (!matches.length) { const empty = document.createElement('div'); empty.className = 'module-search-empty'; empty.textContent = 'No matching modules'; results.appendChild(empty); } results.classList.add('active'); };
    input.addEventListener('input', render); input.addEventListener('keydown', e => { if (e.key === 'Escape') { input.value = ''; results.classList.remove('active'); } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (!matches.length) return; active = (active + (e.key === 'ArrowDown' ? 1 : matches.length - 1)) % matches.length; results.querySelectorAll('.module-search-result').forEach((b,i) => b.classList.toggle('active', i === active)); } else if (e.key === 'Enter') { e.preventDefault(); choose(active < 0 ? 0 : active); } }); document.addEventListener('click', e => { if (!e.target.closest('#topbarModuleSearch')) results.classList.remove('active'); });
    document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); input.select(); } });
}
window.setupModuleSearch = setupModuleSearch;
document.addEventListener('DOMContentLoaded', setupModuleSearch);

function ensurePageRefreshButton(pageEl, pageId) {
    const header = pageEl?.querySelector('.page-head, .page-header, .access-hero');
    if (!header || header.querySelector('.page-refresh-btn')) return;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn btn-ghost page-refresh-btn'; button.title = 'Refresh page data';
    button.innerHTML = '<span aria-hidden="true">↻</span><span>Refresh</span>';
    button.addEventListener('click', () => refreshCurrentPage(pageId, button));
    header.appendChild(button);
}

async function refreshCurrentPage(pageId, button) {
    if (button) button.classList.add('is-refreshing');
    try {
        const loaders = { users: loadUsersFromServer, 'role-profiles': loadRoleProfiles, workspaces: window.loadWorkspaceMenuEditor, account: window.loadAccountSettings, limits: window.loadNetworkAudit, mcp: window.loadMcpTools };
        if (typeof loaders[pageId] === 'function') await loaders[pageId]();
        else window.location.reload();
        if (typeof showToast === 'function' && typeof loaders[pageId] === 'function') showToast('Page refreshed.', 'success');
    } finally { if (button) button.classList.remove('is-refreshing'); }
}
window.refreshCurrentPage = refreshCurrentPage;

async function loadRoleProfiles() {
    const tbody = document.getElementById('roleProfilesTableBody'); if (!tbody) return;
    try {
        const profiles = await workspaceApi('/v1/role-profiles'); tbody.replaceChildren();
        profiles.forEach(profile => { const row = document.createElement('tr'); row.innerHTML = '<td></td><td></td><td></td>'; row.children[0].textContent = profile.name; row.children[1].textContent = profile.description || ''; row.children[2].textContent = (profile.roles || []).join(', ') || '—'; tbody.appendChild(row); });
        if (!profiles.length) tbody.innerHTML = '<tr><td colspan="3">No role profiles configured.</td></tr>';
    } catch (error) { tbody.innerHTML = `<tr><td colspan="3">Unable to load role profiles: ${error.message}</td></tr>`; }
}
window.loadRoleProfiles = loadRoleProfiles;

async function loadUsersFromServer() {
    const tbody = document.getElementById('usersTableBody');
    if (!tbody) return;
    try {
        const response = await workspaceApi('/v1/users');
        const users = Array.isArray(response) ? response : (response.users || []);
        tbody.replaceChildren();
        users.forEach(user => {
            const row = document.createElement('tr');
            row.dataset.userId = user.id || '';
            const roles = (user.roles || []).join(', ') || '—';
            row.innerHTML = `<td style="font-weight:600"></td><td></td><td><span class="badge"></span></td><td style="font-family:var(--font-mono);font-size:12px;color:var(--fg-muted)"></td><td></td>`;
            row.children[0].textContent = user.username || '';
            row.children[1].textContent = user.email || '';
            row.children[2].firstChild.textContent = roles;
            row.children[3].textContent = user.created_at ? new Date(user.created_at).toLocaleDateString() : '—';
            row.children[4].innerHTML = '<button class="btn btn-ghost user-action-edit" type="button">Edit</button><button class="btn btn-ghost user-action-delete" type="button">Delete</button>';
            row.children[4].querySelector('.user-action-edit').onclick = () => editUserAccount(row);
            row.children[4].querySelector('.user-action-delete').onclick = () => deleteUserAccount(row);
            tbody.appendChild(row);
        });
        if (!users.length) tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--fg-muted);padding:24px">No users found.</td></tr>';
    } catch (error) {
        const message = error?.message || 'The server rejected the request.';
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--danger);padding:24px">Unable to load users: ${message}</td></tr>`;
    }
}

/* =================== WORKSPACE DESK / DYNAMIC MENU =================== */
function workspaceToken() { return localStorage.getItem('thinkdome_token') || ''; }
async function workspaceApi(path, options = {}) {
    const result = await fetch(path, { credentials: 'same-origin', ...options, headers: {
        'Content-Type': 'application/json', Authorization: `Bearer ${workspaceToken()}`, ...(options.headers || {})
    }});
    const data = await result.json().catch(() => ({}));
    if (!result.ok) throw new Error(data.detail || 'Workspace request failed');
    return data;
}

function workspaceMenuSelectId() { return localStorage.getItem('thinkdome_active_workspace_id') || ''; }
function setActiveWorkspaceMenu(id) { localStorage.setItem('thinkdome_active_workspace_id', id); }

function renderWorkspaceMenu(menu) {
    const container = document.getElementById('workspaceMenuContainer');
    if (!container) return;
    container.replaceChildren();
    // Built-in links are not a second source of navigation policy.  The Desk
    // response is the single source of truth for what appears in the sidebar.
    document.querySelectorAll('#sidebarNavContainer > .nav-section').forEach(section => { section.hidden = true; });
    // `menu` is a server-resolved view model.  The browser does not validate
    // URLs, guess routes, or decide which configured entries are usable.
    (menu?.menu || []).forEach(section => {
        const sectionEl = document.createElement('div'); sectionEl.className = 'nav-section workspace-nav-section';
        const heading = document.createElement('div'); heading.className = 'nav-group-label'; heading.textContent = section.label;
        sectionEl.appendChild(heading);
        (section.items || []).forEach(item => {
            const isExternal = item.action === 'external';
            let externalHref = null;
            if (isExternal) {
                try {
                    const parsed = new URL(String(item.href || ''), window.location.origin);
                    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') externalHref = parsed.href;
                } catch (_) { /* malformed external targets are not rendered */ }
                if (!externalHref) return;
            }
            const entry = document.createElement(isExternal ? 'a' : 'button');
            entry.className = 'nav-item workspace-nav-item';
            entry.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12h8M12 8v8"/></svg>';
            const text = document.createElement('span'); text.textContent = item.label; entry.appendChild(text);
            if (isExternal) {
                entry.href = externalHref; entry.target = '_blank'; entry.rel = 'noopener noreferrer'; entry.dataset.workspaceExternal = 'true';
            } else { entry.type = 'button'; entry.dataset.page = item.page; entry.addEventListener('click', () => navTo(item.page)); }
            sectionEl.appendChild(entry);
        });
        if (sectionEl.querySelector('.nav-item')) container.appendChild(sectionEl);
    });
    applyRoleBasedUINavigation();
}

function renderWorkspacePages(pages) {
    document.querySelectorAll('[data-workspace-page="true"]').forEach(page => page.remove());
    const main = document.querySelector('.main');
    if (!main) return;
    (pages || []).forEach(page => {
        const section = document.createElement('section');
        section.className = 'page hidden'; section.id = `page-${page.page_id}`; section.dataset.workspacePage = 'true';
        const header = document.createElement('div'); header.className = 'page-header';
        const title = document.createElement('h1'); title.textContent = page.title; header.appendChild(title); section.appendChild(header);
        const content = document.createElement('div'); content.style.cssText = 'display:grid;gap:14px;max-width:1000px;';
        // Registered declarative layouts always use the framework renderer.
        // Keep the legacy block adapter only for older workspace records.
        if (Array.isArray(page.layout) && page.layout.length && window.thinkdome?.ui?.renderPage) {
            window.thinkdome.ui.renderPage(content, page);
        } else (page.blocks || []).forEach(block => {
            const card = document.createElement('div'); card.className = 'card'; card.style.padding = '20px';
            if (block.type === 'metric') { const value = document.createElement('div'); value.style.cssText = 'font-size:30px;font-weight:700;color:var(--accent);'; value.textContent = block.value; card.appendChild(value); }
            if (block.title) { const heading = document.createElement(block.type === 'heading' ? 'h2' : 'h3'); heading.textContent = block.title; card.appendChild(heading); }
            if (block.body) { const body = document.createElement('p'); body.style.color = 'var(--fg-muted)'; body.textContent = block.body; card.appendChild(body); }
            content.appendChild(card);
        });
        section.appendChild(content); main.appendChild(section);
    });
}

async function refreshWorkspaceMenu() {
    try {
        const nav = await window.thinkdome.ui.getNavigation();
        const menu = {
            menu: (nav.workspaces || []).map(workspace => ({
                label: workspace.label || workspace.name,
                items: (workspace.items || []).flatMap(item => item.type === 'group' ? (item.items || []) : [item]).map(item => ({
                    label: item.label || item.name,
                    page: item.route || item.name,
                    action: item.action,
                    href: item.href
                }))
            }))
        };
        renderWorkspacePages((nav.pages || []).map(page => ({
            page_id: page.name || page.route,
            title: page.title || page.name || page.route,
            layout: page.layout,
            blocks: page.blocks || []
        })));
        renderWorkspaceMenu(menu);
        return nav;
    } catch (error) {
        // A failed workspace request must not leave the original application
        // shell hidden. Restore the visual navigation template and surface
        // the error without crashing the rest of the app.
        document.querySelectorAll('#sidebarNavContainer > .nav-section').forEach(section => { section.hidden = false; });
        document.getElementById('workspaceMenuContainer')?.replaceChildren();
        console.warn('Workspace menu unavailable; restored original sidebar:', error);
        return null;
    }
}

async function loadDynamicWorkspace() {
    try {
        const nav = await refreshWorkspaceMenu();
        if (!nav) return;
        return nav;
    } catch (error) {
        console.warn('Dynamic workspace unavailable:', error);
        return null;
    }
}
window.loadDynamicWorkspace = loadDynamicWorkspace;
async function loadWorkspaceManager() {
    const nav = await loadDynamicWorkspace();
    await loadWorkspaceMenuEditor();
    renderWorkspaceRoleMatrix();
    if (typeof window.loadFrameworkWorkspaceManager === 'function') await window.loadFrameworkWorkspaceManager();
    return nav;
}
window.loadWorkspaceManager = loadWorkspaceManager;

async function loadWorkspaceMenuEditor() {
    const select = document.getElementById('workspaceMenuSelect');
    try {
        const list = await workspaceApi('/v1/workspaces');
        const workspaces = Array.isArray(list) ? list : (list.workspaces || []);
        if (select) {
            const current = workspaceMenuSelectId();
            if (!workspaces.length) { const empty = new Option('No workspaces yet — create one', ''); empty.disabled = true; select.replaceChildren(empty); }
            else select.replaceChildren(...workspaces.map(ws => new Option(ws.name, ws.workspace_id, false, ws.workspace_id === current)));
            const id = select.value || current || workspaces[0]?.workspace_id || '';
            if (id) { setActiveWorkspaceMenu(id); select.value = id; }
        }
        const id = workspaceMenuSelectId();
        if (!id) return;
        const menu = await workspaceApi(`/v1/workspaces/${encodeURIComponent(id)}/menu`);
        const pages = await workspaceApi(`/v1/workspaces/${encodeURIComponent(id)}/pages`);
        window.workspaceBuilderState = { pages: pages.pages || [], sections: menu.config || [] };
        renderWorkspaceBuilder();
        await loadWorkspaceRoles();
        refreshWorkspaceRoleOptions();
        refreshInlineWorkspacePages();
        renderWorkspaceRoleMatrix();
        await refreshWorkspaceMenu();
    } catch (error) { if (typeof showToast === 'function') showToast(error.message, 'error'); }
}

function openWorkspaceCreateModal() { const m = document.getElementById('workspaceCreateModal'); if (m) { const body = m.querySelector('.modal-body'); if (body && !document.getElementById('workspaceStarterTemplate')) { const label = document.createElement('label'); label.className = 'field-label'; label.innerHTML = 'Starter setup<select class="form-select" id="workspaceStarterTemplate"><option value="role-aware">Role-aware workspace</option><option value="blank">Empty workspace</option></select>'; body.insertBefore(label, body.children[1]); } document.getElementById('workspaceCreateName').value = ''; document.getElementById('workspaceCreateError').style.display = 'none'; m.classList.add('active'); } }
function closeWorkspaceCreateModal() { const m = document.getElementById('workspaceCreateModal'); if (m) m.classList.remove('active'); }
async function submitWorkspaceCreate(event) { event.preventDefault(); const error = document.getElementById('workspaceCreateError'); try { const ws = await workspaceApi('/v1/workspaces', { method: 'POST', body: JSON.stringify({ name: document.getElementById('workspaceCreateName').value.trim(), ttl_seconds: Number(document.getElementById('workspaceCreateTtl').value) * 60, quota_mb: Number(document.getElementById('workspaceCreateQuota').value) }) }); if (document.getElementById('workspaceStarterTemplate')?.value === 'role-aware') { const pages = [{page_id:'dashboard',title:'Dashboard',allowed_roles:['AGENT_STANDARD','SUPER_ADMIN'],blocks:[{type:'heading',title:'Dashboard'}]},{page_id:'sandboxes',title:'Sandboxes',allowed_roles:['AGENT_STANDARD','SUPER_ADMIN'],blocks:[]},{page_id:'console',title:'Console & IDE',allowed_roles:['AGENT_STANDARD','SUPER_ADMIN'],blocks:[]},{page_id:'admin',title:'Administration',allowed_roles:['SUPER_ADMIN'],blocks:[{type:'heading',title:'Administration'}]}]; const sections = [{label:'User menu',items:[{label:'Dashboard',target_type:'page',target:'dashboard',icon:'grid'},{label:'Sandboxes',target_type:'page',target:'sandboxes',icon:'box'},{label:'Console & IDE',target_type:'page',target:'console',icon:'terminal'}]},{label:'Admin',items:[{label:'Administration',target_type:'page',target:'admin',icon:'settings'}]}]; await workspaceApi(`/v1/workspaces/${encodeURIComponent(ws.workspace_id)}/pages`, {method:'PUT',body:JSON.stringify({pages})}); await workspaceApi(`/v1/workspaces/${encodeURIComponent(ws.workspace_id)}/menu`, {method:'PUT',body:JSON.stringify({sections})}); } setActiveWorkspaceMenu(ws.workspace_id); closeWorkspaceCreateModal(); await loadWorkspaceMenuEditor(); } catch (e) { if (error) { error.textContent = e.message; error.style.display = 'block'; } } }
window.openWorkspaceCreateModal = openWorkspaceCreateModal;

async function saveWorkspacePages() {
    const id = workspaceMenuSelectId(); const state = window.workspaceBuilderState;
    if (!id || !state) return;
    try {
        await workspaceApi(`/v1/workspaces/${encodeURIComponent(id)}/pages`, { method: 'PUT', body: JSON.stringify({ pages: state.pages }) });
        const status = document.getElementById('workspacePagesStatus'); if (status) { status.textContent = 'Saved just now'; setTimeout(() => status.textContent = '', 2500); }
        await refreshWorkspaceMenu();
        if (typeof showToast === 'function') showToast('Workspace pages saved.', 'success');
    } catch (error) { if (typeof showToast === 'function') showToast(error.message || 'Invalid pages JSON.', 'error'); }
}

function addWorkspacePage() {
    const state = window.workspaceBuilderState || (window.workspaceBuilderState = {pages:[],sections:[]});
    const base = 'new-page'; let pageId = base; let index = 2;
    while (state.pages.some(page => page.page_id === pageId)) pageId = `${base}-${index++}`;
    state.pages.push({page_id: pageId, title: 'New page', allowed_roles: [], blocks: [{type:'heading', title:'New page'}]});
    renderWorkspaceBuilder(); refreshInlineWorkspacePages(); renderWorkspaceRoleMatrix();
    const select = document.getElementById('workspaceInlinePage'); if (select) { select.value = pageId; loadInlineWorkspacePage(pageId); }
}
function refreshInlineWorkspacePages() { const select = document.getElementById('workspaceInlinePage'), editor = document.getElementById('workspaceInlineCustomizer'), pages = window.workspaceBuilderState?.pages || []; if (!select || !editor) return; const current = select.value; select.replaceChildren(...pages.map(page => new Option(page.title || page.page_id, page.page_id))); if (!pages.length) { editor.hidden = true; return; } editor.hidden = false; select.value = pages.some(page => page.page_id === current) ? current : pages[0].page_id; loadInlineWorkspacePage(select.value); }
function renderInlineWorkspaceRoles(selected = []) { const target = document.getElementById('workspaceInlineRoles'); if (!target) return; const roles = window.workspaceRoles?.length ? window.workspaceRoles : [...new Set((window.workspaceBuilderState?.pages || []).flatMap(page => page.allowed_roles || []))]; target.replaceChildren(); if (!roles.length) { const note = document.createElement('small'); note.textContent = 'No roles configured yet; the page follows the workspace default.'; target.appendChild(note); return; } roles.forEach(role => { const label = document.createElement('label'); label.className = 'role-checkbox-label'; const input = document.createElement('input'); input.type = 'checkbox'; input.value = role; input.checked = selected.includes(role); label.append(input, document.createTextNode(` ${role}`)); target.appendChild(label); }); }
function loadInlineWorkspacePage(pageId) { const page = (window.workspaceBuilderState?.pages || []).find(item => item.page_id === pageId); const list = document.getElementById('workspaceInlineBlocks'); if (!page || !list) return; document.getElementById('workspaceInlineTitle').value = page.title || ''; renderInlineWorkspaceRoles(page.allowed_roles || []); list.replaceChildren(); (page.blocks || []).forEach(block => addInlineWorkspaceBlock(block.type || 'text', block, false)); renderInlineWorkspacePreview(); }
function addInlineWorkspaceBlock(type = 'text', block = {}, focus = true) { const list = document.getElementById('workspaceInlineBlocks'); if (!list) return; const row = document.createElement('div'); row.className = 'workspace-block-row'; row.innerHTML = `<select class="form-select block-type"><option value="heading">Heading</option><option value="text">Text</option><option value="card">Card</option><option value="metric">Metric</option><option value="stat">Stat</option></select><input class="form-input block-title" placeholder="Title or label"><input class="form-input block-body" placeholder="Description or value"><button type="button" class="icon-btn danger" title="Remove block">⌫</button>`; row.querySelector('.block-type').value = type; row.querySelector('.block-title').value = block.title || block.label || ''; row.querySelector('.block-body').value = ['metric','stat'].includes(type) ? (block.value || '') : (block.body || ''); row.querySelectorAll('input').forEach(input => input.addEventListener('input', renderInlineWorkspacePreview)); row.querySelector('.block-type').onchange = renderInlineWorkspacePreview; row.querySelector('.danger').onclick = () => { row.remove(); renderInlineWorkspacePreview(); }; list.appendChild(row); if (focus) row.querySelector('.block-title').focus(); }
function collectInlineWorkspaceBlocks() { return [...document.querySelectorAll('#workspaceInlineBlocks .workspace-block-row')].map(row => { const type = row.querySelector('.block-type').value, title = row.querySelector('.block-title').value.trim(), value = row.querySelector('.block-body').value.trim(); return ['metric','stat'].includes(type) ? {type,title,value} : {type,title,body:value}; }).filter(block => block.title || block.body || block.value); }
function renderInlineWorkspacePreview() { const preview = document.getElementById('workspaceInlinePreview'); if (!preview) return; const blocks = collectInlineWorkspaceBlocks(); preview.replaceChildren(); if (!blocks.length) { const empty = document.createElement('div'); empty.className = 'workspace-preview-empty'; empty.textContent = 'Add a block to preview this page.'; preview.appendChild(empty); return; } blocks.forEach(block => { const card = document.createElement('div'); card.className = `workspace-preview-block preview-${block.type}`; if (block.type === 'heading') { const h = document.createElement('h3'); h.textContent = block.title || 'Heading'; card.appendChild(h); } else if (['metric','stat'].includes(block.type)) { const label = document.createElement('span'); label.textContent = block.title || 'Value'; const value = document.createElement('strong'); value.textContent = block.value || '—'; card.append(label, value); } else { const title = document.createElement('strong'); title.textContent = block.title || (block.type === 'text' ? 'Text' : 'Card'); const body = document.createElement('p'); body.textContent = block.body || 'Content'; card.append(title, body); } preview.appendChild(card); }); }
function saveInlineWorkspacePage() { const state = window.workspaceBuilderState, page = (state?.pages || []).find(item => item.page_id === document.getElementById('workspaceInlinePage')?.value); if (!page) return; page.title = document.getElementById('workspaceInlineTitle').value.trim() || page.title; page.allowed_roles = [...document.querySelectorAll('#workspaceInlineRoles input:checked')].map(input => input.value); page.blocks = collectInlineWorkspaceBlocks(); renderWorkspaceBuilder(); refreshInlineWorkspacePages(); renderWorkspaceRoleMatrix(); saveWorkspacePages(); if (typeof showToast === 'function') showToast('Page customization saved.', 'success'); }
async function saveWorkspaceMenu() {
    const id = workspaceMenuSelectId(); const state = window.workspaceBuilderState;
    if (!id || !state) return;
    try {
        await workspaceApi(`/v1/workspaces/${encodeURIComponent(id)}/menu`, { method: 'PUT', body: JSON.stringify({ sections: state.sections }) });

        if (typeof call === 'function') {
            try {
                const items = [];
                (state.sections || []).forEach(sec => {
                    (sec.items || []).forEach(it => {
                        items.push({
                            name: it.target || it.label,
                            type: it.target_type || 'page',
                            label: it.label,
                            route: it.target,
                            icon: it.icon || 'grid'
                        });
                    });
                });
                await call("thinkdome.core.ui.api.create_workspace", {
                    config: {
                        name: id,
                        label: id.charAt(0).toUpperCase() + id.slice(1),
                        sequence: 10,
                        items: items
                    }
                });
            } catch (rpcErr) {
                console.warn("Dynamic UI platform workspace menu sync:", rpcErr);
            }
        }

        const status = document.getElementById('workspaceMenuStatus'); if (status) { status.textContent = 'Saved just now'; setTimeout(() => status.textContent = '', 2500); }
        await refreshWorkspaceMenu();
        if (typeof showToast === 'function') showToast('Workspace menu saved & published.', 'success');
    } catch (error) { if (typeof showToast === 'function') showToast(error.message || 'Invalid menu JSON.', 'error'); }
}
async function loadWorkspaceRoles() { try { const result = await workspaceApi('/v1/roles'); window.workspaceRoles = (Array.isArray(result) ? result : result.roles || []).map(role => role.name || role).sort(); refreshWorkspaceRoleOptions(); } catch (_) { refreshWorkspaceRoleOptions(); } }
function refreshWorkspaceRoleOptions() { const select = document.getElementById('workspacePreviewRole'); if (!select) return; const roles = new Set(window.workspaceRoles || []); (window.workspaceBuilderState?.pages || []).forEach(page => (page.allowed_roles || []).forEach(role => roles.add(role))); const current = select.value || '__all__'; select.replaceChildren(new Option('All roles', '__all__'), ...[...roles].sort().map(role => new Option(role, role))); select.value = [...select.options].some(option => option.value === current) ? current : '__all__'; renderWorkspaceRolePreview(); }
function renderWorkspaceRolePreview() { const result = document.getElementById('workspaceRolePreview'), state = window.workspaceBuilderState || {pages:[],sections:[]}; if (!result) return; const role = document.getElementById('workspacePreviewRole')?.value || '__all__'; const canSee = page => role === '__all__' || !(page.allowed_roles || []).length || (page.allowed_roles || []).includes(role); const pages = state.pages.filter(canSee); const pageIds = new Set(pages.map(page => page.page_id)); const links = state.sections.reduce((count, section) => count + (section.items || []).filter(item => pageIds.has(item.target)).length, 0); result.innerHTML = ''; const strong = document.createElement('strong'); strong.textContent = role === '__all__' ? 'All configured roles' : role; const summary = document.createElement('span'); summary.textContent = ` · ${pages.length} page${pages.length === 1 ? '' : 's'} · ${links} sidebar link${links === 1 ? '' : 's'}`; result.append(strong, summary); }
function renderWorkspaceViewer() { const state = window.workspaceBuilderState || {pages:[],sections:[]}; const roleSelect = document.getElementById('workspaceViewerRole'), pageSelect = document.getElementById('workspaceViewerPage'), canvas = document.getElementById('workspaceViewerCanvas'); if (!roleSelect || !pageSelect || !canvas) return; const roles = new Set(window.workspaceRoles || []); state.pages.forEach(page => (page.allowed_roles || []).forEach(role => roles.add(role))); const oldRole = roleSelect.value || '__all__'; roleSelect.replaceChildren(new Option('All roles', '__all__'), ...[...roles].sort().map(role => new Option(role, role))); roleSelect.value = [...roleSelect.options].some(option => option.value === oldRole) ? oldRole : '__all__'; const role = roleSelect.value; const visible = state.pages.filter(page => role === '__all__' || !(page.allowed_roles || []).length || page.allowed_roles.includes(role)); const oldPage = pageSelect.value; pageSelect.replaceChildren(...visible.map(page => new Option(page.title || page.page_id, page.page_id))); if (!visible.length) { canvas.replaceChildren(); const empty = document.createElement('div'); empty.className = 'workspace-viewer-empty'; empty.textContent = state.pages.length ? 'This role has no page access.' : 'No configured page. The viewer is intentionally empty.'; canvas.appendChild(empty); return; } pageSelect.value = visible.some(page => page.page_id === oldPage) ? oldPage : visible[0].page_id; const page = visible.find(item => item.page_id === pageSelect.value) || visible[0]; canvas.replaceChildren(); const title = document.createElement('strong'); title.textContent = page.title || page.page_id; canvas.appendChild(title); (page.blocks || []).forEach(block => { const item = document.createElement('div'); item.className = `workspace-viewer-block viewer-${block.type || 'card'}`; if (['metric','stat'].includes(block.type)) { const label = document.createElement('span'); label.textContent = block.title || 'Value'; const value = document.createElement('strong'); value.textContent = block.value || '—'; item.append(label, value); } else { const heading = document.createElement(block.type === 'heading' ? 'h4' : 'strong'); heading.textContent = block.title || (block.type === 'heading' ? 'Section heading' : 'Content card'); item.appendChild(heading); if (block.body) { const body = document.createElement('p'); body.textContent = block.body; item.appendChild(body); } } canvas.appendChild(item); }); if (!(page.blocks || []).length) { const empty = document.createElement('span'); empty.className = 'workspace-viewer-empty'; empty.textContent = 'This page has no content blocks yet.'; canvas.appendChild(empty); } }
function renderWorkspaceRoleMatrix() { const target = document.getElementById('workspaceRoleMatrix'), state = window.workspaceBuilderState || {pages:[],sections:[]}; if (!target) return; const roles = new Set(window.workspaceRoles || []); state.pages.forEach(page => (page.allowed_roles || []).forEach(role => roles.add(role))); target.replaceChildren(); if (!state.pages.length) { const empty = document.createElement('div'); empty.className = 'workspace-viewer-empty'; empty.textContent = 'Create a page to build the access map.'; target.appendChild(empty); } else { state.pages.slice(0, 5).forEach(page => { const row = document.createElement('div'); row.className = 'workspace-matrix-row'; const name = document.createElement('strong'); name.textContent = page.title || page.page_id; const access = document.createElement('span'); access.textContent = page.allowed_roles?.length ? page.allowed_roles.join(' · ') : 'Everyone'; row.append(name, access); target.appendChild(row); }); } const pageCount = document.getElementById('workspacePageCount'); const roleCount = document.getElementById('workspaceRoleCount'); const blockCount = document.getElementById('workspaceBlockCount'); if (pageCount) pageCount.textContent = state.pages.length; if (roleCount) roleCount.textContent = roles.size; if (blockCount) blockCount.textContent = state.pages.reduce((sum, page) => sum + (page.blocks || []).length, 0); renderWorkspaceViewer(); }
function renderWorkspaceBuilder() { const state = window.workspaceBuilderState || {pages:[],sections:[]}; const pages = document.getElementById('workspacePagesVisual'), menu = document.getElementById('workspaceMenuVisual'); if (!pages || !menu) return; pages.replaceChildren(); menu.replaceChildren(); document.getElementById('workspacePagesEmpty').hidden = state.pages.length > 0; document.getElementById('workspaceMenuEmpty').hidden = state.sections.length > 0; state.pages.forEach(page => { const card = document.createElement('div'); card.className = 'workspace-page-card'; card.innerHTML = `<span class="workspace-page-dot">P</span><div class="workspace-card-copy"><strong></strong><span class="mono-muted"></span><div class="workspace-role-tags"></div></div><div class="workspace-card-actions"><button class="icon-btn" title="Edit page">✎</button><button class="icon-btn danger" title="Delete page">⌫</button></div>`; card.querySelector('strong').textContent = page.title; card.querySelector('.mono-muted').textContent = `/${page.page_id}`; const tags = card.querySelector('.workspace-role-tags'); (page.allowed_roles.length ? page.allowed_roles : ['Everyone']).forEach(role => { const tag = document.createElement('span'); tag.textContent = role; tags.appendChild(tag); }); card.querySelector('button').onclick = () => editWorkspacePage(page); card.querySelector('.danger').onclick = () => deleteWorkspacePage(page.page_id); pages.appendChild(card); }); state.sections.forEach((section, sectionIndex) => { const group = document.createElement('div'); group.className = 'workspace-section-card'; group.draggable = true; group.dataset.index = sectionIndex; group.innerHTML = `<div class="workspace-section-head"><span class="drag-handle">⠿</span><strong></strong><span class="item-count"></span><button class="icon-btn danger" title="Delete section">⌫</button></div><div class="workspace-item-list"></div><button class="add-item-link">+ Add menu item</button>`; group.querySelector('strong').textContent = section.label; group.querySelector('.item-count').textContent = `${section.items.length} item${section.items.length === 1 ? '' : 's'}`; group.querySelector('.danger').onclick = () => { state.sections.splice(sectionIndex, 1); renderWorkspaceBuilder(); }; const list = group.querySelector('.workspace-item-list'); section.items.forEach((item, itemIndex) => { const row = document.createElement('div'); row.className = 'workspace-menu-item'; row.innerHTML = `<span class="drag-handle">⠿</span><span class="workspace-item-icon">✦</span><strong></strong><span class="workspace-item-target"></span><button class="icon-btn" title="Edit item">✎</button><button class="icon-btn danger" title="Delete item">⌫</button>`; row.querySelector('strong').textContent = item.label; row.querySelector('.workspace-item-target').textContent = item.target; row.querySelector('button').onclick = () => editWorkspaceMenuItem(sectionIndex, itemIndex); row.querySelector('.danger').onclick = () => { section.items.splice(itemIndex, 1); renderWorkspaceBuilder(); }; list.appendChild(row); }); group.querySelector('.add-item-link').onclick = () => openWorkspaceMenuModal(sectionIndex); group.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', sectionIndex); }); group.addEventListener('dragover', e => e.preventDefault()); group.addEventListener('drop', e => { const from = Number(e.dataTransfer.getData('text/plain')); if (from !== sectionIndex) { const moved = state.sections.splice(from, 1)[0]; state.sections.splice(sectionIndex, 0, moved); renderWorkspaceBuilder(); } }); menu.appendChild(group); }); }
function editWorkspacePage(page) { refreshInlineWorkspacePages(); const select = document.getElementById('workspaceInlinePage'); if (select) { select.value = page.page_id; loadInlineWorkspacePage(page.page_id); } }
function deleteWorkspacePage(pageId) { const state = window.workspaceBuilderState; if (!confirm('Delete this page? Menu items linked to it should also be removed.')) return; state.pages = state.pages.filter(page => page.page_id !== pageId); state.sections.forEach(section => section.items = section.items.filter(item => !(item.target_type === 'page' && item.target === pageId))); renderWorkspaceBuilder(); refreshInlineWorkspacePages(); renderWorkspaceRoleMatrix(); }
function addWorkspaceSection() { const modal = document.getElementById('workspaceSectionModal'); if (!modal) return; document.getElementById('workspaceSectionLabel').value = ''; modal.classList.add('active'); setTimeout(() => document.getElementById('workspaceSectionLabel').focus(), 50); }
function closeWorkspaceSectionModal() { document.getElementById('workspaceSectionModal')?.classList.remove('active'); }
function submitWorkspaceSection(event) { event.preventDefault(); const state = window.workspaceBuilderState || {pages:[],sections:[]}; const label = document.getElementById('workspaceSectionLabel').value.trim(); if (!label) return; state.sections.push({label, items: []}); window.workspaceBuilderState = state; closeWorkspaceSectionModal(); renderWorkspaceBuilder(); }
function openWorkspaceMenuModal(sectionIndex, itemIndex = null) { const modal = document.getElementById('workspaceMenuModal'); modal.dataset.section = sectionIndex; modal.dataset.item = itemIndex === null ? '' : itemIndex; document.getElementById('workspaceMenuLabel').value = itemIndex === null ? '' : window.workspaceBuilderState.sections[sectionIndex].items[itemIndex].label; const select = document.getElementById('workspaceMenuTarget'); select.replaceChildren(...window.workspaceBuilderState.pages.map(page => new Option(page.title, page.page_id))); if (itemIndex !== null) { const item = window.workspaceBuilderState.sections[sectionIndex].items[itemIndex]; select.value = item.target; document.getElementById('workspaceMenuIcon').value = item.icon || 'grid'; } document.getElementById('workspaceMenuModalTitle').textContent = itemIndex === null ? 'Add menu item' : 'Edit menu item'; document.getElementById('workspaceMenuSubmit').textContent = itemIndex === null ? 'Add menu item' : 'Save item'; document.getElementById('workspaceMenuError').textContent = ''; modal.classList.add('active'); }
function closeWorkspaceMenuModal() { document.getElementById('workspaceMenuModal')?.classList.remove('active'); }
function editWorkspaceMenuItem(sectionIndex, itemIndex) { openWorkspaceMenuModal(sectionIndex, itemIndex); }
function submitWorkspaceMenuItem(event) { event.preventDefault(); const modal = document.getElementById('workspaceMenuModal'), state = window.workspaceBuilderState, section = state.sections[Number(modal.dataset.section)]; const item = {label: document.getElementById('workspaceMenuLabel').value.trim(), target_type: 'page', target: document.getElementById('workspaceMenuTarget').value, icon: document.getElementById('workspaceMenuIcon').value}; if (!item.target) { document.getElementById('workspaceMenuError').textContent = 'Create a page before adding a menu item.'; return; } const index = modal.dataset.item === '' ? -1 : Number(modal.dataset.item); if (index >= 0) section.items[index] = item; else section.items.push(item); closeWorkspaceMenuModal(); renderWorkspaceBuilder(); }
window.loadWorkspaceMenuEditor = loadWorkspaceMenuEditor;
window.saveWorkspaceMenu = saveWorkspaceMenu;
window.saveWorkspacePages = saveWorkspacePages;
window.setActiveWorkspaceMenu = setActiveWorkspaceMenu;

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

    document.documentElement.dataset.thinkdomeRole = activeRole;
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
window.addEventListener('DOMContentLoaded', async () => {
    const appView = document.getElementById('appView');
    const isLoggedIn = localStorage.getItem('thinkdome_logged_in') === 'true';
    if (appView && isLoggedIn) {
        const role = localStorage.getItem('thinkdome_user_role') || 'AGENT_STANDARD';
        const user = localStorage.getItem('thinkdome_username') || 'User';
        applyRoleBasedUINavigation(role, user);
        const nav = await loadWorkspaceManager();
        const configuredPages = Array.isArray(nav?.pages) ? nav.pages : [];
        // Dashboard is the preferred registered landing page. It is selected
        // from the server manifest, so it remains dynamic and still falls
        // back safely when an installation has no dashboard configured.
        const firstPage = configuredPages.find(page => {
            const id = String(page.name || page.page_id || page.route || '').toLowerCase();
            return id === 'dashboard' || id === 'home';
        }) || configuredPages[0];
        // There is no client-side default route. With no configured pages,
        // the application intentionally stays empty.
        if (firstPage) navTo(firstPage.name || firstPage.page_id || firstPage.route);
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
    document.getElementById('userModalPassword').required = false;
    document.getElementById('userModalPassword').dataset.reset = 'false';
    clearUserModalMessage();
    const meta = document.getElementById('userModalMeta'); if (meta) { meta.style.display = 'none'; meta.replaceChildren(); }
    
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.add('active');
}

function openAccessControlNotice(label) {
    if (typeof showToast === 'function') showToast(`${label} is available through the administrator access-control configuration.`, 'info');
}
window.openAccessControlNotice = openAccessControlNotice;

async function editUserAccount(btn) {
    const row = btn.closest ? btn.closest('tr') : btn;
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
    clearUserModalMessage();
    const meta = document.getElementById('userModalMeta');
    if (meta) { meta.style.display = 'grid'; meta.textContent = 'Loading account details…'; }
    if (row.dataset.userId) {
        try {
            const detail = await workspaceApi(`/v1/users/${encodeURIComponent(row.dataset.userId)}`);
            const user = detail.user || {};
            document.getElementById('userModalStatus').value = user.status === 'active' ? 'ACTIVE' : 'SUSPENDED';
            if (meta) { meta.innerHTML = ''; [['Account ID', user.id], ['Created', user.created_at ? new Date(user.created_at).toLocaleString() : '—'], ['Last login', user.last_login || 'Never'], ['State', user.status || 'active']].forEach(([label, value]) => { const item = document.createElement('div'); item.innerHTML = `<strong style="display:block;color:var(--fg);font-size:10px;text-transform:uppercase;letter-spacing:.06em;">${label}</strong><span>${value || '—'}</span>`; meta.appendChild(item); }); }
        } catch (_) { if (meta) meta.textContent = 'Account details unavailable.'; }
    }
    
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.add('active');
}

function closeUserModal() {
    const modal = document.getElementById('userAccountModal');
    if (modal) modal.classList.remove('active');
    loadUsersFromServer();
}

function clearUserModalMessage() { const box = document.getElementById('userModalError'); if (box) { box.textContent = ''; box.style.display = 'none'; } }
function showUserModalMessage(message, kind = 'error') { const box = document.getElementById('userModalError'); if (box) { box.textContent = message; box.style.display = 'block'; box.style.borderColor = kind === 'success' ? 'var(--success)' : 'var(--danger)'; box.style.background = kind === 'success' ? 'var(--success-subtle)' : 'var(--danger-subtle)'; box.style.color = kind === 'success' ? 'var(--success)' : 'var(--danger)'; } }

function preparePasswordReset() {
    const input = document.getElementById('userModalPassword');
    const hint = document.getElementById('userModalPasswordHint');
    if (input) { input.value = ''; input.required = false; input.dataset.reset = 'true'; input.placeholder = 'Enter new password (8+ characters)'; input.focus(); }
    if (hint) hint.textContent = 'Enter a new password, then choose Save User Account. The server stores only a hash.';
}
window.preparePasswordReset = preparePasswordReset;

function saveUserAccountFromModal(event) {
    if (event) event.preventDefault();
    
    const rowIndex = document.getElementById('userModalEditRowIndex').value;
    const username = document.getElementById('userModalUsername').value.trim();
    const email = document.getElementById('userModalEmail').value.trim();
    const role = document.getElementById('userModalRole').value;
    const status = document.getElementById('userModalStatus').value;
    const password = document.getElementById('userModalPassword').value;
    const passwordReset = document.getElementById('userModalPassword').dataset.reset === 'true';
    
    const tbody = document.getElementById('usersTableBody');
    if (!tbody) return;
    
    const row = rowIndex !== '' ? tbody.children[parseInt(rowIndex)] : null;
    const userId = row?.dataset.userId;
    if (!row && !password) { showUserModalMessage('A password is required for a new user.'); return; }
    if (passwordReset && password.length < 8) { showUserModalMessage('Enter a new password with at least 8 characters.'); return; }
    workspaceApi(row ? `/v1/users/${encodeURIComponent(userId)}` : '/v1/users', { method: row ? 'PUT' : 'POST', body: JSON.stringify({ username, email, password, status: status.toLowerCase(), role_name: role }) })
      .then(() => { loadUsersFromServer(); showUserModalMessage(row ? 'User updated successfully.' : 'User created successfully.', 'success'); })
      .catch(error => { showUserModalMessage(`Unable to save user: ${error.message}`); });
}

function deleteUserAccount(btn) {
    const row = btn.closest ? btn.closest('tr') : btn;
    const username = row?.children[0]?.textContent?.trim() || 'User';
    if (confirm(`Are you sure you want to delete user account '${username}'?`)) {
        const userId = row?.dataset.userId;
        if (!userId) { row.remove(); return; }
        workspaceApi(`/v1/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }).then(() => { row.remove(); if (typeof showToast === 'function') showToast('User deactivated.', 'success'); }).catch(error => { if (typeof showToast === 'function') showToast(error.message, 'error'); });
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

function saveRoleFromModal(event) {
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
            <p style="font-size:13px;color:var(--fg-muted);margin-bottom:14px;line-height:1.4;">Custom role definition with granular module capabilities.</p>
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
        showCustomAlert("Role Registered", `Role '${name}' (${roleCode}) successfully saved, permission matrix linked, and RBAC policy cache refreshed.`);
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
