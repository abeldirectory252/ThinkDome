// static/js/sandboxes.js

/* =================== SANDBOX NODES GRID & TABLE =================== */
function renderSandboxNodesTable() {
    const container = document.getElementById('sandboxesPageTableBody');
    if (!container) return;
    container.innerHTML = Object.keys(state.sandboxes).map(key => {
        const sb = state.sandboxes[key];
        let statClass = 'success';
        if (sb.status === 'stopped') statClass = 'error';
        else if (sb.status === 'halted') statClass = 'error';
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

function renderSandboxCards() {
    const grid = document.getElementById('sandboxInstanceGrid');
    if (!grid) return;
    
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

function updateSandboxCardsHTML() {
    renderSandboxCards();
}

/* =================== STATE SETTERS =================== */
function setSandboxState(sbKey, newState) {
    const sb = state.sandboxes[sbKey];
    if (!sb) return;
    if (sb.status === newState) return;
    
    sb.status = newState;
    if (newState === 'running') {
        sb.ramUsage = Math.floor(Math.random() * 25) + 40;
        sb.uptime = '0h 01m';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Booting sandbox container ${sbKey}...`);
            addLogLine('INFO', `Runtime engine connected on ${sbKey}`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Started sandbox runtime ${sbKey}`);
        }
    } else if (newState === 'stopped') {
        sb.ramUsage = 0;
        sb.uptime = '—';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Container ${sbKey} stopped by admin action.`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Stopped sandbox runtime ${sbKey}`);
        }
    } else if (newState === 'halted') {
        sb.ramUsage = 0;
        sb.uptime = '—';
        if (typeof addLogLine === 'function') {
            addLogLine('WARN', `Container ${sbKey} halted immediately (forced shutdown).`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Halted sandbox runtime ${sbKey}`);
        }
    } else if (newState === 'hibernating') {
        sb.uptime = sb.uptime + ' (suspended)';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Container ${sbKey} hibernated. State snapshot saved.`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Hibernated sandbox runtime ${sbKey}`);
        }
    }
    
    renderAllViews();
}

function toggleSandboxState(sbKey) {
    const sb = state.sandboxes[sbKey];
    if (!sb) return;
    if (sb.status === 'running') {
        sb.status = 'stopped';
        sb.ramUsage = 0;
        sb.uptime = '—';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Container ${sbKey} stopped by admin action.`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Stopped sandbox runtime ${sbKey}`);
        }
    } else {
        sb.status = 'running';
        sb.ramUsage = Math.floor(Math.random() * 25) + 40;
        sb.uptime = '0h 01m';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Booting sandbox container ${sbKey}...`);
            addLogLine('INFO', `Runtime engine connected on ${sbKey}`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Provisioned sandbox runtime ${sbKey}`);
        }
    }
    renderAllViews();
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
    const ok = await showCustomConfirm("Delete Sandbox Node", `Are you sure you want to permanently delete sandbox node "${sbKey}"?`);
    if (ok) {
        delete state.sandboxes[sbKey];
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
        
        renderAllViews();
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
        selected.forEach(key => {
            delete state.sandboxes[key];
        });
        
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Bulk deleted sandbox nodes: ${selected.join(', ')}`);
        }
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Bulk deleted sandboxes: ${selected.join(', ')}`);
        }
        
        if (!state.sandboxes[state.activeSbx]) {
            const keys = Object.keys(state.sandboxes);
            state.activeSbx = keys.length > 0 ? keys[0] : '';
        }
        
        const master = document.querySelector('input[onclick="toggleSelectAllTableSandboxes(this)"]');
        if (master) master.checked = false;
        tableSbxAllSelected = false;
        
        renderAllViews();
    }
}

/* =================== REGISTER MODAL =================== */
function registerNewSandboxNode() {
    const modal = document.getElementById('registerSbxModal');
    if (modal) {
        document.getElementById('sbxNameInput').value = "custom-node-05";
        document.getElementById('sbxRuntimeInput').value = "python:3.11";
        document.getElementById('sbxRegionInput').value = "us-east-1";
        document.getElementById('sbxCpuInput').value = "2";
        document.getElementById('sbxRamInput').value = "4 GB";
        document.getElementById('sbxRateInput').value = "0.08";
        
        modal.classList.add('active');
    }
}

function closeRegisterModal() {
    const modal = document.getElementById('registerSbxModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function submitRegisterModal(e) {
    e.preventDefault();
    
    const name = document.getElementById('sbxNameInput').value.trim();
    const runtime = document.getElementById('sbxRuntimeInput').value.trim();
    const region = document.getElementById('sbxRegionInput').value;
    const cpu = parseInt(document.getElementById('sbxCpuInput').value);
    const ram = document.getElementById('sbxRamInput').value;
    const rate = parseFloat(document.getElementById('sbxRateInput').value);

    if (!name || !runtime) return;

    const randomId = 'sbx_' + Math.random().toString(36).substring(2, 6);
    state.sandboxes[name] = {
        id: randomId,
        name: name,
        runtime: runtime,
        cores: cpu,
        ram: ram,
        region: region,
        uptime: '0h 01m',
        spend: 0.00,
        rate: rate,
        ramUsage: 45,
        status: 'running',
        executions: '0.00',
        subtotal: 0.00
    };

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Registered and launched virtual container ${name} (${randomId})`);
    }
    if (typeof addAuditEvent === 'function') {
        addAuditEvent(`Registered sandbox node ${name}`);
    }
    
    closeRegisterModal();
    renderAllViews();
}
