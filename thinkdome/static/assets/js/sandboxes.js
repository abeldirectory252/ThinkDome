// static/js/sandboxes.js

/* =================== SKELETON LOADERS =================== */
function getTableSkeletonHTML(colCount, rowCount = 4) {
    let rowsHTML = '';
    for (let r = 0; r < rowCount; r++) {
        rowsHTML += `<tr>`;
        for (let c = 0; c < colCount; c++) {
            rowsHTML += `<td><span class="skeleton skeleton-table-cell"></span></td>`;
        }
        rowsHTML += `</tr>`;
    }
    return rowsHTML;
}

function getCardsSkeletonHTML(cardCount = 3) {
    let cardsHTML = '';
    for (let c = 0; c < cardCount; c++) {
        cardsHTML += `
          <div class="skeleton-card" style="height: 200px;">
            <div class="skeleton-row">
              <div style="display:flex; gap:10px; align-items:center; width:100%;">
                <span class="skeleton skeleton-avatar"></span>
                <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                  <span class="skeleton" style="height:14px; width:50%;"></span>
                  <span class="skeleton" style="height:10px; width:30%;"></span>
                </div>
              </div>
            </div>
            <div class="skeleton" style="height:14px; width:80%;"></div>
            <div class="skeleton" style="height:14px; width:70%;"></div>
            <div class="skeleton" style="height:14px; width:90%;"></div>
            <div class="skeleton-row" style="margin-top:auto;">
              <span class="skeleton" style="height:12px; width:40%;"></span>
              <span class="skeleton" style="height:20px; width:20%;"></span>
            </div>
          </div>
        `;
    }
    return cardsHTML;
}

/* =================== SANDBOX NODES GRID & TABLE =================== */
async function fetchSandboxesData() {
    const token = localStorage.getItem('thinkdome_token');

    // Show static loading placeholders (no skeletons)
    const grid = document.getElementById('sandboxInstanceGrid');
    const container = document.getElementById('sandboxesPageTableBody');

    if (grid) grid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding: 24px; color:var(--fg-subtle);">Loading sandbox nodes...</div>';
    if (container) container.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--fg-subtle)">Loading registry list...</td></tr>';

    if (!window.API || !token) {
        return;
    }

    try {
        const { data, error } = await window.API.getSandboxes(token);
        if (error) throw new Error(error);

        if (data) {
            const fetchedSbx = {};
            data.filter(sb => canViewSandbox(sb)).forEach(sb => {
                const ramVal = sb.memory_mb >= 1024 ? `${(sb.memory_mb/1024).toFixed(0)} GB` : `${sb.memory_mb} MB`;
                const displayStatus = (sb.status === 'active' || sb.status === 'running') ? 'running' : 'stopped';
                fetchedSbx[sb.name] = {
                    id: sb.sandbox_id,
                    name: sb.name,
                    runtime: sb.runtime || 'python:3.12',
                    cores: sb.cpu_cores,
                    ram: ramVal,
                    region: sb.region || 'us-east-1',
                    uptime: displayStatus === 'running' ? '1h' : '—',
                    spend: 0,
                    rate: sb.cost_per_hour || 0.08,
                    ramUsage: displayStatus === 'running' ? 45 : 0,
                    status: displayStatus,
                    executions: '0',
                    subtotal: 0
                };
            });
            state.sandboxes = fetchedSbx;
            updateSidebarSandboxCount();
        }

        renderSandboxNodesTableHTMLOnly();
        renderSandboxCardsHTMLOnly();
        renderSbxDropdowns();
        updateSidebarSandboxCount();
        if (typeof updateTerminalLabel === 'function') updateTerminalLabel();

    } catch (err) {
        console.warn("Sandboxes using offline mode:", err);
        const grid = document.getElementById('sandboxInstanceGrid');
        const container = document.getElementById('sandboxesPageTableBody');
        if (grid) grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 32px 24px; color:var(--fg-subtle); font-size:13px;"><div style="display:flex;flex-direction:column;align-items:center;gap:8px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.35"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>Waiting for sandbox data…</div></div>`;
        if (container) container.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:20px 12px;color:var(--fg-subtle);font-size:13px;"><div style="display:flex;flex-direction:column;align-items:center;gap:6px;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.4"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>Waiting for sandbox data…</div></td></tr>`;
        renderSbxDropdowns();
    }
}

function renderSandboxNodesTable() {
    // When called, refresh data asynchronously
    fetchSandboxesData();
}

function renderSandboxNodesTableHTMLOnly() {
    const container = document.getElementById('sandboxesPageTableBody');
    if (!container) return;

    if (Object.keys(state.sandboxes).length === 0) {
        container.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--fg-subtle)">No sandbox nodes registered</td></tr>`;
        updateBulkDeleteButtonVisibility();
        return;
    }

    container.innerHTML = Object.keys(state.sandboxes).map(key => {
        const sb = state.sandboxes[key];
        let statClass = 'success';
        if (sb.status === 'stopped' || sb.status === 'halted') statClass = 'error';
        else if (sb.status === 'hibernating') statClass = 'warn';

        const statTag = `<span class="status-tag ${statClass}">${sb.status.toUpperCase()}</span>`;
        return `
          <tr>
            <td style="text-align: center;">
              <input type="checkbox" class="sbx-table-checkbox" data-key="${key}" style="cursor:pointer;" onchange="updateBulkDeleteButtonVisibility()" />
            </td>
            <td class="mono" style="font-weight:600;">${sb.name} <span style="font-size:11px;color:var(--fg-subtle)">(${sb.id})</span></td>
            <td>${sb.region}</td>
            <td>${sb.cores} Cores</td>
            <td>${sb.ram}</td>
            <td class="mono">${sb.runtime}</td>
            <td class="mono" style="font-weight:600;">$${sb.rate.toFixed(2)}/hr</td>
            <td>${statTag}</td>
            <td>
              <div style="display:flex; gap:6px;">
                <button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'running')" title="Power On" ${sb.status === 'running' ? 'disabled style="opacity:0.4;"' : ''}>On</button>
                <button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'stopped')" title="Power Off" ${sb.status === 'stopped' ? 'disabled style="opacity:0.4;"' : ''}>Off</button>
                <button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'halted')" title="Halt Node" ${sb.status === 'halted' ? 'disabled style="opacity:0.4;"' : ''}>Halt</button>
                <button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'hibernating')" title="Hibernate Node" ${sb.status === 'hibernating' ? 'disabled style="opacity:0.4;"' : ''}>Sleep</button>
                <button class="btn btn-ghost btn-sm" onclick="deleteSingleSandbox('${key}')" title="Delete Sandbox" style="color:var(--danger); border-color:var(--danger-subtle);">Delete</button>
              </div>
            </td>
          </tr>
        `;
    }).join('');
    updateBulkDeleteButtonVisibility();
}

function renderSandboxCardsHTMLOnly() {
    const grid = document.getElementById('sandboxInstanceGrid');
    if (!grid) return;
    
    if (Object.keys(state.sandboxes).length === 0) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 24px; color:var(--fg-subtle);">No sandbox nodes currently active. Register a new node to begin.</div>`;
        return;
    }

    grid.innerHTML = Object.keys(state.sandboxes).map(key => {
        const sb = state.sandboxes[key];
        
        let statusBadgeClass = 'b-muted';
        if (sb.status === 'running') {
            statusBadgeClass = 'b-success';
        } else if (sb.status === 'halted') {
            statusBadgeClass = 'b-danger';
        } else if (sb.status === 'hibernating') {
            statusBadgeClass = 'b-warning';
        }
        
        const statusLabel = sb.status;
        
        const consoleBtn = `<button class="btn btn-ghost btn-sm" onclick="jumpToSbxConsole('${key}')" title="Open Console IDE"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg></button>`;
        const powerBtn = `<button class="btn btn-ghost btn-sm" onclick="toggleSandboxState('${key}')" title="Stop/Start Sandbox"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><path d="M18.4 5.6a9 9 0 1 1-12.8 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg></button>`;
        const haltBtn = `<button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'halted')" title="Halt Node" ${sb.status === 'halted' ? 'disabled style="opacity:0.4;"' : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg></button>`;
        const hibBtn = `<button class="btn btn-ghost btn-sm" onclick="setSandboxState('${key}', 'hibernating')" title="Hibernate Node" ${sb.status === 'hibernating' ? 'disabled style="opacity:0.4;"' : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg></button>`;
        const delBtn = `<button class="btn btn-ghost btn-sm" onclick="deleteSingleSandbox('${key}')" title="Delete Sandbox" style="color:var(--danger); border-color:var(--danger-subtle);"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg></button>`;

        const uptimeText = sb.status === 'running' || sb.status === 'hibernating' ? sb.uptime : '—';

        return `
            <div class="card sbx" id="sb-card-${key}">
              <div class="row1">
                <div class="title">
                  <div class="ic">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                    </svg>
                  </div>
                  <div>
                    <div style="font-weight:600; color:var(--fg);">${sb.name}</div>
                    <div class="faint mono">${sb.id}</div>
                  </div>
                </div>
                <span class="badge ${statusBadgeClass}" id="badge-${key}"><span class="dot" style="background:currentColor"></span>${statusLabel}</span>
              </div>
              <div class="specs">
                <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6"></rect><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"></path></svg>${sb.cores} vCPU</span>
                <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="10" rx="2"></rect><path d="M6 7v10M10 7v10M14 7v10M18 7v10"></path></svg>${sb.ram}</span>
                <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"></path></svg>${sb.region}</span>
                <span class="mono">${sb.runtime}</span>
              </div>
              <div style="font-size:11.5px;color:var(--text-muted);display:flex;justify-content:space-between;">
                <span>RAM usage</span>
                <span class="mono" id="ram-text-${key}">${sb.ramUsage}%</span>
              </div>
              <div class="bar"><i style="width:${sb.ramUsage}%" id="ram-bar-${key}"></i></div>
              <div class="foot">
                <span class="faint" id="footer-${key}">Up ${uptimeText} · $${sb.rate.toFixed(2)}/hr</span>
                <div style="display:flex;gap:8px;">
                  ${consoleBtn}
                  ${powerBtn}
                  ${haltBtn}
                  ${hibBtn}
                  ${delBtn}
                </div>
              </div>
            </div>
        `;
    }).join('');
}

function renderSandboxCards() {
    fetchSandboxesData();
}

function updateSandboxCardsHTML() {
    renderSandboxCardsHTMLOnly();
}

/* =================== STATE SETTERS =================== */
async function setSandboxState(sbKey, newState) {
    const sb = state.sandboxes[sbKey];
    if (!sb) return;
    
    // Convert states to backend toggle
    // active <-> stopped
    const backendStatus = (newState === 'running') ? 'active' : 'stopped';
    const currentBackendStatus = (sb.status === 'running') ? 'active' : 'stopped';

    if (backendStatus === currentBackendStatus && newState !== 'halted' && newState !== 'hibernating') return;

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Changing sandbox container ${sbKey} state to ${newState}...`);
    }

    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) {
            throw new Error("Offline or Unauthorized");
        }
        const { error } = await window.API.toggleSandbox(sb.id, token);
        if (error) throw new Error(error);

        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Updated sandbox state: ${sbKey} → ${newState}`);
        }
        await fetchSandboxesData();
    } catch (err) {
        await showCustomAlert("Operation Failed", `Failed to change sandbox state: ${err.message || err}`);
    }
}

async function toggleSandboxState(sbKey) {
    const sb = state.sandboxes[sbKey];
    if (!sb) return;
    
    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) {
            throw new Error("Offline or Unauthorized");
        }
        const { error } = await window.API.toggleSandbox(sb.id, token);
        if (error) throw new Error(error);

        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Toggled sandbox state: ${sbKey}`);
        }
        await fetchSandboxesData();
    } catch (err) {
        await showCustomAlert("Operation Failed", `Failed to toggle sandbox state: ${err.message || err}`);
    }
}

function jumpToSbxConsole(sbKey) {
    state.activeSbx = sbKey;
    const ideSelect = document.getElementById('ideTargetNodeSelect');
    if (ideSelect) ideSelect.value = sbKey;
    const banner = document.getElementById('activeSbxBanner');
    if (banner) banner.innerText = `${sbKey} connected`;
    
    if (typeof navTo === 'function') {
        navTo('console');
    }
    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Terminal active focus switched to ${sbKey}`);
    }
}

function changeActiveSbx(sbKey) {
    state.activeSbx = sbKey;
    const banner = document.getElementById('activeSbxBanner');
    if (banner) banner.innerText = `${sbKey} connected`;
    
    if (typeof updateTerminalLabel === 'function') {
        updateTerminalLabel();
    }
    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Console target runtime mapped to ${sbKey}`);
    }
}

async function deleteSingleSandbox(sbKey) {
    const sb = state.sandboxes[sbKey];
    if (!sb) return;

    const ok = await showCustomConfirm("Delete Sandbox Node", `Are you sure you want to permanently delete sandbox node "${sbKey}"?`);
    if (ok) {
        const token = localStorage.getItem('thinkdome_token');
        try {
            if (!window.API || !token) {
                throw new Error("Offline or Unauthorized");
            }
            const { error } = await window.API.terminateSandbox(sb.id, token);
            if (error) throw new Error(error);

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Deleted sandbox node workspace: ${sbKey}`);
            }
            if (typeof addAuditEvent === 'function') {
                addAuditEvent(`Deleted sandbox node ${sbKey}`);
            }
            
            if (state.activeSbx === sbKey) {
                const keys = Object.keys(state.sandboxes);
                state.activeSbx = keys.length > 0 ? keys[0] : '';
            }
            
            await fetchSandboxesData();
        } catch (err) {
            await showCustomAlert("Delete Failed", `Failed to delete sandbox node: ${err.message || err}`);
        }
    }
}

function renderSbxDropdowns() {
    const ideSelect = document.getElementById('ideTargetNodeSelect');
    if (ideSelect) {
        const curVal = ideSelect.value || state.activeSbx;
        ideSelect.innerHTML = '';
        
        Object.keys(state.sandboxes).forEach(key => {
            const sb = state.sandboxes[key];
            const opt = document.createElement('option');
            opt.value = key;
            
            let statusChar = '⬡';
            if (sb.status === 'running') statusChar = '●';
            else if (sb.status === 'hibernating') statusChar = '☾';
            else if (sb.status === 'halted') statusChar = '▲';
            
            opt.textContent = `${statusChar} ${sb.id} · ${sb.name}`;
            ideSelect.appendChild(opt);
        });
        
        if (state.sandboxes[curVal]) {
            ideSelect.value = curVal;
        } else {
            const keys = Object.keys(state.sandboxes);
            if (keys.length > 0) {
                ideSelect.value = keys[0];
                state.activeSbx = keys[0];
            }
        }
    }
}

/* =================== BULK SELECTION & DELETE =================== */
let tableSbxAllSelected = false;
function toggleSelectAllTableSandboxes(masterCb) {
    tableSbxAllSelected = masterCb.checked;
    document.querySelectorAll('.sbx-table-checkbox').forEach(cb => {
        cb.checked = tableSbxAllSelected;
    });
    updateBulkDeleteButtonVisibility();
}

function updateBulkDeleteButtonVisibility() {
    const btn = document.getElementById('btn-bulk-delete-sbx');
    if (!btn) return;
    const total = document.querySelectorAll('.sbx-table-checkbox').length;
    const checkedBoxes = document.querySelectorAll('.sbx-table-checkbox:checked');
    
    if (checkedBoxes.length > 0) {
        btn.style.display = 'inline-flex';
    } else {
        btn.style.display = 'none';
    }

    const master = document.querySelector('input[onclick="toggleSelectAllTableSandboxes(this)"]');
    if (master) {
        if (checkedBoxes.length === 0) {
            master.checked = false;
        } else if (checkedBoxes.length === total && total > 0) {
            master.checked = true;
        } else {
            master.checked = false;
        }
    }
}

async function bulkDeleteSandboxes() {
    const selected = [];
    document.querySelectorAll('.sbx-table-checkbox:checked').forEach(cb => {
        selected.push(cb.getAttribute('data-key'));
    });
    
    if (selected.length === 0) {
        await showCustomAlert("No Selection", "No sandboxes selected. Please check the boxes in the Sandbox Node Registry table below.");
        return;
    }
    
    const ok = await showCustomConfirm("Bulk Delete Sandboxes", `Are you sure you want to permanently delete these ${selected.length} sandboxes: ${selected.join(', ')}?`);
    if (ok) {
        const token = localStorage.getItem('thinkdome_token');
        let failCount = 0;
        
        for (let key of selected) {
            const sb = state.sandboxes[key];
            if (!sb) continue;
            try {
                if (!window.API || !token) {
                    throw new Error("Offline");
                }
                const { error } = await window.API.terminateSandbox(sb.id, token);
                if (error) throw new Error(error);
                
                if (typeof addLogLine === 'function') {
                    addLogLine('SYS', `Deleted sandbox node workspace: ${key}`);
                }
                if (typeof addAuditEvent === 'function') {
                    addAuditEvent(`Deleted sandbox node ${key}`);
                }
            } catch {
                failCount++;
            }
        }
        
        if (failCount > 0) {
            await showCustomAlert("Bulk Delete Issues", `Failed to delete ${failCount} sandboxes. Please check your connection.`);
        }
        
        if (!state.sandboxes[state.activeSbx]) {
            const keys = Object.keys(state.sandboxes);
            state.activeSbx = keys.length > 0 ? keys[0] : '';
        }
        
        const master = document.querySelector('input[onclick="toggleSelectAllTableSandboxes(this)"]');
        if (master) master.checked = false;
        tableSbxAllSelected = false;
        
        await fetchSandboxesData();
    }
}

/* =================== MODULAR REGISTER MODAL & CHIP VALIDATORS =================== */
let sbxEgressDomainsList = ['api.github.com', 'pypi.org', 'huggingface.co', 'cdn.jsdelivr.net'];
let sbxIngressPortsList = ['80', '443', '8000'];

function toggleEgressDomainInputVisibility(mode) {
    const notice = document.getElementById('sbxEgressStatusNotice');
    const formRow = document.getElementById('sbxEgressAddFormRow');
    const chipsList = document.getElementById('sbxEgressChipsList');
    
    if (mode === 'whitelist') {
        if (notice) notice.hidden = true;
        if (formRow) formRow.style.display = 'flex';
        if (chipsList) chipsList.style.display = 'flex';
    } else if (mode === 'full') {
        if (notice) {
            notice.innerHTML = `🔓 <strong>Unrestricted Outbound Access Active:</strong> All outbound network traffic permitted without domain proxying. Custom whitelist domain rules are locked.`;
            notice.hidden = false;
        }
        if (formRow) formRow.style.display = 'none';
        if (chipsList) chipsList.style.display = 'none';
    } else if (mode === 'lockdown') {
        if (notice) {
            notice.innerHTML = `🔒 <strong>Strict Airgap Isolation Active:</strong> All outbound network traffic is completely blocked. Domain whitelist rules are locked.`;
            notice.hidden = false;
        }
        if (formRow) formRow.style.display = 'none';
        if (chipsList) chipsList.style.display = 'none';
    }
}

function toggleIngressPortInputVisibility(mode) {
    const notice = document.getElementById('sbxIngressStatusNotice');
    const formRow = document.getElementById('sbxIngressAddFormRow');
    const chipsList = document.getElementById('sbxIngressChipsList');
    
    if (mode === 'whitelisted_ports') {
        if (notice) notice.hidden = true;
        if (formRow) formRow.style.display = 'flex';
        if (chipsList) chipsList.style.display = 'flex';
    } else if (mode === 'deny_all') {
        if (notice) {
            notice.innerHTML = `🔒 <strong>Default Deny Inbound Policy Active:</strong> All incoming connections blocked by default firewall. Custom port rules are locked.`;
            notice.hidden = false;
        }
        if (formRow) formRow.style.display = 'none';
        if (chipsList) chipsList.style.display = 'none';
    } else if (mode === 'public_load_balancer') {
        if (notice) {
            notice.innerHTML = `🌐 <strong>Public Load Balancer Ingress Active:</strong> Standard HTTP (80) & HTTPS (443) ports exposed automatically. Custom port rules are locked.`;
            notice.hidden = false;
        }
        if (formRow) formRow.style.display = 'none';
        if (chipsList) chipsList.style.display = 'none';
    }
}

function isValidDomainName(domain) {
    if (!domain) return false;
    const clean = domain.trim().toLowerCase();
    if (clean === 'localhost') return true;
    const pattern = /^(\*\.)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$/;
    return pattern.test(clean);
}

function isValidPortRule(rule) {
    if (!rule) return false;
    const clean = rule.trim();
    // Port number range 1-65535 or range 8000-8080 or CIDR
    if (/^\d+$/.test(clean)) {
        const val = parseInt(clean, 10);
        return val >= 1 && val <= 65535;
    }
    if (/^\d+-\d+$/.test(clean)) {
        const [s, e] = clean.split('-').map(v => parseInt(v, 10));
        return s >= 1 && e <= 65535 && s < e;
    }
    if (/^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/.test(clean)) return true;
    return false;
}

function renderEgressChips() {
    const container = document.getElementById('sbxEgressChipsList');
    if (!container) return;
    if (sbxEgressDomainsList.length === 0) {
        container.innerHTML = `<span style="font-size:12px;color:var(--fg-subtle);font-style:italic;">No egress domains added. Click + Add Domain to allow outbound API targets.</span>`;
        return;
    }
    container.innerHTML = sbxEgressDomainsList.map(domain => `
        <span style="display:inline-flex;align-items:center;gap:6px;padding:3px 9px;background:var(--surface-raised);border:1px solid var(--border-strong);border-radius:14px;font-size:11.5px;font-family:var(--font-mono);color:var(--fg);">
            <span>${domain}</span>
            <button type="button" onclick="removeEgressDomainChip('${domain}')" style="background:none;border:none;color:var(--danger);cursor:pointer;font-weight:700;font-size:13px;line-height:1;padding:0 2px;">&times;</button>
        </span>
    `).join('');
}

function addEgressDomainChip() {
    const input = document.getElementById('sbxEgressAddInput');
    const errEl = document.getElementById('sbxEgressChipError');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    if (!input) return;
    const domain = input.value.trim().toLowerCase();
    
    if (!isValidDomainName(domain)) {
        if (errEl) {
            errEl.textContent = `Invalid domain format '${domain}'. Must be a valid hostname (e.g. api.openai.com, pypi.org, or *.github.com).`;
            errEl.hidden = false;
        }
        return;
    }
    
    if (!sbxEgressDomainsList.includes(domain)) {
        sbxEgressDomainsList.push(domain);
        renderEgressChips();
    }
    input.value = '';
}

function removeEgressDomainChip(domain) {
    sbxEgressDomainsList = sbxEgressDomainsList.filter(d => d !== domain);
    renderEgressChips();
}

function renderIngressChips() {
    const container = document.getElementById('sbxIngressChipsList');
    if (!container) return;
    if (sbxIngressPortsList.length === 0) {
        container.innerHTML = `<span style="font-size:12px;color:var(--fg-subtle);font-style:italic;">No ingress ports added. Default deny policy active.</span>`;
        return;
    }
    container.innerHTML = sbxIngressPortsList.map(port => `
        <span style="display:inline-flex;align-items:center;gap:6px;padding:3px 9px;background:var(--surface-raised);border:1px solid var(--border-strong);border-radius:14px;font-size:11.5px;font-family:var(--font-mono);color:var(--accent);">
            <span>Port ${port}</span>
            <button type="button" onclick="removeIngressPortChip('${port}')" style="background:none;border:none;color:var(--danger);cursor:pointer;font-weight:700;font-size:13px;line-height:1;padding:0 2px;">&times;</button>
        </span>
    `).join('');
}

function addIngressPortChip() {
    const input = document.getElementById('sbxIngressAddInput');
    const errEl = document.getElementById('sbxIngressChipError');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    if (!input) return;
    const rule = input.value.trim();
    
    if (!isValidPortRule(rule)) {
        if (errEl) {
            errEl.textContent = `Invalid ingress port format '${rule}'. Must be a port number (e.g. 8000), range (8080-8090), or CIDR.`;
            errEl.hidden = false;
        }
        return;
    }
    
    if (!sbxIngressPortsList.includes(rule)) {
        sbxIngressPortsList.push(rule);
        renderIngressChips();
    }
    input.value = '';
}

function removeIngressPortChip(port) {
    sbxIngressPortsList = sbxIngressPortsList.filter(p => p !== port);
    renderIngressChips();
}

function registerNewSandboxNode() {
    const modal = document.getElementById('registerSbxModal');
    const alertEl = document.getElementById('sbxValidationErrorAlert');
    if (alertEl) { alertEl.hidden = true; alertEl.textContent = ''; }
    
    if (modal) {
        const randomId = Math.floor(10 + Math.random() * 90);
        if (document.getElementById('sbxNameInput')) document.getElementById('sbxNameInput').value = `custom-node-${randomId}`;
        if (document.getElementById('sbxRuntimeInput')) document.getElementById('sbxRuntimeInput').value = "python:3.11-slim";
        if (document.getElementById('sbxExecutionTypeSelect')) document.getElementById('sbxExecutionTypeSelect').value = "docker";
        if (document.getElementById('sbxRegionInput')) document.getElementById('sbxRegionInput').value = "us-east-1";
        if (document.getElementById('sbxCpuInput')) document.getElementById('sbxCpuInput').value = "2";
        if (document.getElementById('sbxRamInput')) document.getElementById('sbxRamInput').value = "4 GB";
        if (document.getElementById('sbxDiskInput')) document.getElementById('sbxDiskInput').value = "10 GB";
        if (document.getElementById('sbxDiskTypeSelect')) document.getElementById('sbxDiskTypeSelect').value = "nvme_ssd";
        if (document.getElementById('sbxNetworkModeSelect')) document.getElementById('sbxNetworkModeSelect').value = "whitelist";
        if (document.getElementById('sbxBandwidthLimitSelect')) document.getElementById('sbxBandwidthLimitSelect').value = "100 Mbps";
        if (document.getElementById('sbxIngressModeSelect')) document.getElementById('sbxIngressModeSelect').value = "deny_all";
        if (document.getElementById('sbxIngressProtocolSelect')) document.getElementById('sbxIngressProtocolSelect').value = "TCP";
        if (document.getElementById('sbxTtlSelect')) document.getElementById('sbxTtlSelect').value = "1 hour";
        if (document.getElementById('sbxRateInput')) document.getElementById('sbxRateInput').value = "0.08";
        if (document.getElementById('sbxRateLimitSelect')) document.getElementById('sbxRateLimitSelect').value = "60";
        if (document.getElementById('sbxConcurrentExecSelect')) document.getElementById('sbxConcurrentExecSelect').value = "5";
        
        sbxEgressDomainsList = ['api.github.com', 'pypi.org', 'huggingface.co', 'cdn.jsdelivr.net'];
        sbxIngressPortsList = ['80', '443', '8000'];
        renderEgressChips();
        renderIngressChips();

        toggleEgressDomainInputVisibility("whitelist");
        toggleIngressPortInputVisibility("deny_all");
        modal.classList.add('active');
    }
}

function closeRegisterModal() {
    const modal = document.getElementById('registerSbxModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

async function submitRegisterModal(e) {
    e.preventDefault();
    const alertEl = document.getElementById('sbxValidationErrorAlert');
    if (alertEl) { alertEl.hidden = true; alertEl.textContent = ''; }
    
    const name = document.getElementById('sbxNameInput')?.value.trim() || "custom-node-01";
    const executionType = document.getElementById('sbxExecutionTypeSelect')?.value || "docker";
    const runtime = document.getElementById('sbxRuntimeInput')?.value.trim() || "python:3.11-slim";
    const region = document.getElementById('sbxRegionInput')?.value || "us-east-1";
    const cpuStr = document.getElementById('sbxCpuInput')?.value || "2";
    const ramStr = document.getElementById('sbxRamInput')?.value || "4 GB";
    const diskStr = document.getElementById('sbxDiskInput')?.value || "10 GB";
    const ingressMode = document.getElementById('sbxIngressModeSelect')?.value || "deny_all";
    const ingressProtocol = document.getElementById('sbxIngressProtocolSelect')?.value || "TCP";
    const egressDomains = [...sbxEgressDomainsList];
    const ingressPorts = [...sbxIngressPortsList];
    const ttlStr = document.getElementById('sbxTtlSelect')?.value || "1 hour";
    const rate = parseFloat(document.getElementById('sbxRateInput')?.value || "0.08");
    const rateLimit = parseInt(document.getElementById('sbxRateLimitSelect')?.value || "60", 10);
    const maxConcurrent = parseInt(document.getElementById('sbxConcurrentExecSelect')?.value || "5", 10);

    if (!name || !runtime) return;

    // Strict Resource Quota & Threshold Validation
    const cpuCores = parseInt(cpuStr, 10);
    const ramGb = ramStr.includes('MB') ? (parseInt(ramStr, 10) / 1024) : parseInt(ramStr, 10);
    const diskGb = parseInt(diskStr, 10);

    if (cpuCores > 16) {
        if (alertEl) {
            alertEl.textContent = "Safety Threshold Error: CPU allocation cannot exceed 16 vCPU Cores ceiling.";
            alertEl.hidden = false;
        }
        return;
    }

    if (ramGb > 32) {
        if (alertEl) {
            alertEl.textContent = "Safety Threshold Error: RAM allocation cannot exceed 32 GB ceiling. Illogical allocations like 10,000 GB RAM are blocked.";
            alertEl.hidden = false;
        }
        return;
    }

    if (diskGb > 250) {
        if (alertEl) {
            alertEl.textContent = "Safety Threshold Error: Storage allocation cannot exceed 250 GB NVMe ceiling.";
            alertEl.hidden = false;
        }
        return;
    }

    if (rateLimit > 500) {
        if (alertEl) {
            alertEl.textContent = "Safety Threshold Error: API rate limit cannot exceed 500 req/sec ceiling.";
            alertEl.hidden = false;
        }
        return;
    }

    const memory_mb = Math.round(ramGb * 1024);
    const token = localStorage.getItem('thinkdome_token');

    const newSandboxObj = {
        id: `sbx-${Date.now().toString(36)}`,
        name: name,
        runtime: runtime,
        execution_type: executionType.toUpperCase(),
        region: region,
        cpu_cores: cpuCores,
        ram_gb: ramGb,
        ram_display: ramStr,
        disk_gb: diskGb,
        disk_type: diskType.toUpperCase(),
        network_mode: networkMode.toUpperCase(),
        bandwidth: bandwidth,
        egress_domains: egressDomains,
        ingress_mode: ingressMode.toUpperCase(),
        ingress_protocol: ingressProtocol,
        ingress_ports: ingressPorts,
        ttl: ttlStr,
        rate: rate,
        rate_limit: `${rateLimit} req/s`,
        max_concurrent: maxConcurrent,
        status: "RUNNING",
        status_color: "var(--success)",
        uptime: "Just now",
        ip: "10.244.12.89"
    };

    try {
        if (window.API && token) {
            const { data, error } = await window.API.createSandbox({
                name: name,
                memory_mb: memory_mb,
                cpu_cores: cpuCores,
                timeout_sec: 3600,
                network_enabled: networkMode !== 'lockdown'
            }, token);

            if (data && data.id) {
                newSandboxObj.id = data.id;
            }
        }

        if (window.state && Array.isArray(window.state.sandboxes)) {
            window.state.sandboxes.unshift(newSandboxObj);
        } else if (typeof state !== 'undefined' && Array.isArray(state.sandboxes)) {
            state.sandboxes.unshift(newSandboxObj);
        }

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Provisioned modular sandbox node '${name}' [${executionType.toUpperCase()}, ${ramStr} RAM, ${diskStr} NVMe, Rate Limit: ${rateLimit} req/s, Max Concurrent: ${maxConcurrent}]`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Provisioned modular sandbox node ${name}`);
        }
        
        closeRegisterModal();
        if (typeof renderSandboxesView === 'function') {
            renderSandboxesView();
        } else if (typeof fetchSandboxesData === 'function') {
            await fetchSandboxesData();
        }
    } catch (err) {
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Local provisioned sandbox node '${name}' [${executionType.toUpperCase()}, ${ramStr} RAM]`);
        }
        closeRegisterModal();
        if (typeof renderSandboxesView === 'function') {
            renderSandboxesView();
        }
    }
}
