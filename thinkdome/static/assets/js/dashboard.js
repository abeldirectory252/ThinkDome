// static/js/dashboard.js

/* =================== CORE THEMING =================== */
function initTheme() {
    // Keep the established dashboard theme stable.  The OS/browser preference
    // must not silently change the product theme between sessions.
    const savedTheme = localStorage.getItem('thinkdome_theme_preference');
    const useDark = savedTheme === 'dark';
    if (useDark) {
        document.documentElement.classList.add('dark');
        state.theme = 'dark';
    } else {
        document.documentElement.classList.remove('dark');
        state.theme = 'light';
    }
    if (typeof editorInstance !== 'undefined' && editorInstance) {
        monaco.editor.setTheme(state.theme === 'dark' ? 'vs-dark' : 'vs');
    }
}
initTheme();

function toggleTheme() {
    if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
        state.theme = 'light';
    } else {
        document.documentElement.classList.add('dark');
        state.theme = 'dark';
    }
    localStorage.setItem('thinkdome_theme_preference', state.theme);
    if (typeof editorInstance !== 'undefined' && editorInstance) {
        monaco.editor.setTheme(state.theme === 'dark' ? 'vs-dark' : 'vs');
    }
}

/* =================== SKELETON RENDERERS =================== */
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

function showStatsSkeletons() {
    const ids = ['statCumulativeCalls', 'statNodesCount', 'statKeysCount', 'statCurrentSpend'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.innerText = '—';
        }
    });
    const subEl = document.getElementById('statCurrentSpendSub');
    if (subEl) {
        subEl.innerText = '—';
    }
}

/* =================== AUDITING & RECENT RUNS =================== */
function addAuditEvent(detail) {
    const timeStr = new Date().toTimeString().split(' ')[0];
    state.auditEvents.unshift({ ts: timeStr, actor: 'admin', detail: detail });
}

async function refreshDash(btn) {
    if (btn) {
        btn.style.opacity = '0.5';
        btn.disabled = true;
    }

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', 'Refreshing workspace registry matrices...');
    }

    // Trigger dynamic fetch
    await fetchDashboardData();

    if (btn) {
        btn.style.opacity = '1';
        btn.disabled = false;
    }
    if (typeof addLogLine === 'function') {
        addLogLine('SUCCESS', 'Workspace registry matrices refreshed.');
    }
}

async function fetchDashboardData() {
    // Resolve optional dashboard surfaces once. Dynamic UI pages may omit any
    // of these targets, so every renderer must treat them as nullable.
    const execBody = document.getElementById('execBody');
    const auditBody = document.getElementById('auditBody');
    const auditFullBody = document.getElementById('auditFullBody');
    try {
        const health = await fetch('/health');
        const apiStatus = document.getElementById('fleetApiStatus');
        const apiDot = document.getElementById('fleetApiDot');
        if (apiStatus) apiStatus.textContent = health.ok ? 'Operational' : 'Degraded';
        if (apiDot) apiDot.className = `fleet-dot ${health.ok ? 'ok' : 'bad'}`;
    } catch (_) {
        const apiStatus = document.getElementById('fleetApiStatus');
        const apiDot = document.getElementById('fleetApiDot');
        if (apiStatus) apiStatus.textContent = 'Unavailable';
        if (apiDot) apiDot.className = 'fleet-dot bad';
    }
    const token = localStorage.getItem('thinkdome_token');

    if (!window.API || !token) {
        return;
    }

    // Never decide whether to call admin endpoints from localStorage alone.
    // Rehydrate the role from the authenticated server session first; the
    // browser value is only a display hint and may be stale.
    let serverIsAdmin = false;
    try {
        const identity = await window.API.getCurrentUser(token);
        const serverRole = String(identity?.data?.user?.role || '').toUpperCase();
        serverIsAdmin = ['ADMIN', 'SUPER_ADMIN', 'ENTERPRISE_ADMIN', 'ORCH', 'IDE'].includes(serverRole);
        if (serverRole) localStorage.setItem('thinkdome_user_role', serverRole);
    } catch (_) {
        // Fail closed: a role that the server did not confirm cannot access
        // administrative dashboard data.
    }

    try {
        const isAdmin = serverIsAdmin;
        const nodesResponse = isAdmin ? await fetch('/v1/control-plane/nodes', {
            headers: { 'Authorization': `Bearer ${token}` }
        }) : null;
        const nodeStatus = document.getElementById('fleetNodeStatus');
        const nodeDot = document.getElementById('fleetNodeDot');
        if (!nodesResponse) {
            if (nodeStatus) nodeStatus.textContent = 'Sandbox-scoped';
            if (nodeDot) nodeDot.className = 'fleet-dot ok';
        } else if (nodesResponse.ok) {
            const payload = await nodesResponse.json();
            const count = Array.isArray(payload.nodes) ? payload.nodes.length : 0;
            if (nodeStatus) nodeStatus.textContent = `${count} ready node${count === 1 ? '' : 's'}`;
            if (nodeDot) nodeDot.className = `fleet-dot ${count ? 'ok' : 'bad'}`;
        } else {
            if (nodeStatus) nodeStatus.textContent = 'Access unavailable';
            if (nodeDot) nodeDot.className = 'fleet-dot bad';
        }
    } catch (_) {
        const nodeStatus = document.getElementById('fleetNodeStatus');
        const nodeDot = document.getElementById('fleetNodeDot');
        if (nodeStatus) nodeStatus.textContent = 'Unavailable';
        if (nodeDot) nodeDot.className = 'fleet-dot bad';
    }

    try {
        // Fetch concurrently
        const isAdmin = serverIsAdmin;
        const [sandboxesRes, keysRes, logsRes, auditRes] = await Promise.all([
            window.API.getSandboxes(token),
            isAdmin ? window.API.getApiKeys(token) : Promise.resolve({ data: [] }),
            isAdmin ? window.API.getRequestLogs(token, 20) : Promise.resolve({ data: [] }),
            isAdmin ? window.API.getAuditLogs(token, 50) : Promise.resolve({ data: [] })
        ]);

        // Process Sandboxes
        if (sandboxesRes.data) {
            const fetchedSbx = {};
            sandboxesRes.data.filter(sb => canViewSandbox(sb)).forEach(sb => {
                const ramVal = sb.memory_mb >= 1024 ? `${(sb.memory_mb/1024).toFixed(0)} GB` : `${sb.memory_mb} MB`;
                fetchedSbx[sb.name] = {
                    id: sb.sandbox_id,
                    name: sb.name,
                    runtime: sb.runtime || 'python:3.12',
                    cores: sb.cpu_cores,
                    ram: ramVal,
                    region: sb.region || 'us-east-1',
                    uptime: sb.status === 'running' ? '1h' : '—',
                    spend: 0,
                    rate: sb.cost_per_hour || 0.08,
                    ramUsage: sb.status === 'running' ? 45 : 0,
                    status: sb.status,
                    executions: '0',
                    subtotal: 0
                };
            });
            state.sandboxes = fetchedSbx;
            if (typeof updateSidebarSandboxCount === 'function') updateSidebarSandboxCount();
        }

        // Process API Keys
        if (keysRes.data) {
            state.apiKeys = keysRes.data.map(k => ({
                name: k.display_name,
                token: k.masked_token || k.token,
                type: k.token_type,
                status: k.status,
                key_id: k.key_id
            }));
        }

        // Update stats dashboard
        const statCumulativeCalls = document.getElementById('statCumulativeCalls');
        const statNodesCount = document.getElementById('statNodesCount');
        const statKeysCount = document.getElementById('statKeysCount');

        if (statCumulativeCalls) {
            statCumulativeCalls.innerText = logsRes.data ? logsRes.data.length : '0';
        }
        if (statNodesCount) {
            const total = Object.keys(state.sandboxes).length;
            const active = Object.values(state.sandboxes).filter(s => s.status === 'running').length;
            statNodesCount.innerText = `${active} / ${total}`;
        }
        if (statKeysCount) {
            statKeysCount.innerText = state.apiKeys.length;
        }

        // Render Recent Runs table
        if (execBody && logsRes.data) {
            if (logsRes.data.length === 0) {
                execBody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--fg-subtle)">No executions recorded</td></tr>`;
            } else {
                execBody.innerHTML = logsRes.data.slice(0, 5).map(log => {
                    const timeStr = log.timestamp ? log.timestamp.split('T')[1].split('.')[0] : '—';
                    const cmdText = log.tool_name + ' ' + (typeof log.request_payload === 'object' ? JSON.stringify(log.request_payload) : log.request_payload);
                    const displayCmd = cmdText.length > 50 ? cmdText.substring(0, 50) + '...' : cmdText;
                    return `
                        <tr>
                          <td class="time">${timeStr}</td>
                          <td><span class="action-tag">${log.display_name || 'LLM'}</span></td>
                          <td class="mono" style="font-size:12.5px;" title="${cmdText}">${displayCmd}</td>
                          <td><span class="status-tag ${log.status === 'success' ? 'success' : 'error'}">${log.status.toUpperCase()}</span></td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // Render Recent Audits
        if (auditBody && auditRes.data) {
            if (auditRes.data.length === 0) {
                auditBody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--fg-subtle)">No recent audit logs</td></tr>`;
            } else {
                auditBody.innerHTML = auditRes.data.slice(0, 5).map(ev => {
                    const timeStr = ev.timestamp ? ev.timestamp.split('T')[1].split('.')[0] : '—';
                    return `
                        <tr onclick="openAuditDetailModal(${ev.id})" title="Click to view details">
                          <td class="time">${timeStr}</td>
                          <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent)">${ev.actor}</span></td>
                          <td style="font-size:13px;font-weight:500;">${ev.action}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // Render Full Audit Screen
        if (auditFullBody && auditRes.data) {
            if (auditRes.data.length === 0) {
                auditFullBody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--fg-subtle)">No audit logs recorded</td></tr>`;
            } else {
                auditFullBody.innerHTML = auditRes.data.map(ev => {
                    const dateStr = ev.timestamp ? ev.timestamp.replace('T', ' ').substring(0, 19) : '—';
                    return `
                        <tr onclick="openAuditDetailModal(${ev.id})" title="Click to view details">
                          <td class="time">${dateStr}</td>
                          <td><span class="action-tag">${ev.ip_address || '127.0.0.1'}</span></td>
                          <td class="mono">${ev.action}</td>
                          <td><span class="status-tag success">AUDIT_OK</span></td>
                          <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent)">${ev.actor}</span></td>
                          <td style="font-weight:500;">${ev.details ? (typeof ev.details === 'object' ? JSON.stringify(ev.details) : ev.details) : ''}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // Render tables for keys and sandboxes
        renderApiKeysHTMLOnly();
        if (typeof renderSandboxNodesTable === 'function') renderSandboxNodesTable();
        if (typeof updateSandboxCardsHTML === 'function') updateSandboxCardsHTML();
        if (typeof renderBillingReport === 'function') renderBillingReport();

    } catch (err) {
        console.warn("Dashboard using offline fallback mode:", err);
        
        const statCumulativeCalls = document.getElementById('statCumulativeCalls');
        const statNodesCount = document.getElementById('statNodesCount');
        const statKeysCount = document.getElementById('statKeysCount');

        if (statCumulativeCalls) statCumulativeCalls.innerHTML = `<span style="font-size:13px;color:var(--fg-subtle)">—</span>`;
        if (statNodesCount) statNodesCount.innerHTML = `<span style="font-size:13px;color:var(--fg-subtle)">—</span>`;
        if (statKeysCount) statKeysCount.innerHTML = `<span style="font-size:13px;color:var(--fg-subtle)">—</span>`;

        const emptyRow = (cols, msg) => `<tr><td colspan="${cols}" style="text-align:center;padding:20px 12px;color:var(--fg-subtle);font-size:13px;"><div style="display:flex;flex-direction:column;align-items:center;gap:6px;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.4"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>${msg}</div></td></tr>`;

        if (execBody) execBody.innerHTML = emptyRow(4, 'Waiting for API connection…');
        if (auditBody) auditBody.innerHTML = emptyRow(3, 'Waiting for API connection…');
        if (auditFullBody) auditFullBody.innerHTML = emptyRow(6, 'Waiting for API connection…');
        
        const keysTableBody = document.getElementById('apiKeysTableBody');
        if (keysTableBody) keysTableBody.innerHTML = emptyRow(5, 'Waiting for API connection…');
    }
}

function renderDashboardRecentTables() {
    fetchDashboardData();
    // Keep operator status current without creating an aggressive polling loop.
    if (!window.__thinkdomeDashboardPoller) {
        window.__thinkdomeDashboardPoller = window.setInterval(() => {
            if (!document.hidden) fetchDashboardData();
        }, 30000);
    }
}

/* =================== AUDIT DETAIL MODAL =================== */

function openAuditDetailModal(auditId) {
    const modal = document.getElementById('auditDetailModal');
    const content = document.getElementById('auditDetailContent');
    if (!modal || !content) return;

    // Show modal with loading state
    content.innerHTML = `
        <div style="text-align:center;padding:60px 0;">
            <div style="display:inline-block;width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite;"></div>
            <div style="margin-top:12px;color:var(--fg-subtle);font-size:13px;">Loading audit event details...</div>
        </div>
    `;
    modal.classList.add('active');

    // Fetch detail
    const token = localStorage.getItem('thinkdome_token');
    if (!window.API || !token) {
        content.innerHTML = `<div style="text-align:center;color:var(--danger);padding:40px 0;">Authentication required</div>`;
        return;
    }

    window.API.getAuditDetail(token, auditId).then(res => {
        if (res.error || !res.data) {
            content.innerHTML = `<div style="text-align:center;color:var(--danger);padding:40px 0;">Failed to load audit details: ${res.error || 'Unknown error'}</div>`;
            return;
        }
        renderAuditDetailContent(res.data);
    }).catch(err => {
        content.innerHTML = `<div style="text-align:center;color:var(--danger);padding:40px 0;">Error: ${err.message}</div>`;
    });
}

function closeAuditDetailModal() {
    const modal = document.getElementById('auditDetailModal');
    if (modal) modal.classList.remove('active');
}

function renderAuditDetailContent(data) {
    const content = document.getElementById('auditDetailContent');
    if (!content) return;

    const timestamp = data.timestamp ? data.timestamp.replace('T', ' ').substring(0, 19) : '—';
    const exec = data.related_execution;

    // Format details object nicely
    let detailsStr = '';
    if (data.details && typeof data.details === 'object') {
        detailsStr = JSON.stringify(data.details, null, 2);
    } else if (data.details) {
        detailsStr = String(data.details);
    }

    // Build latency section
    let latencyHTML = '';
    if (exec && exec.duration_ms !== undefined) {
        const durationMs = exec.duration_ms;
        const durationSec = (durationMs / 1000).toFixed(2);
        // Compute a visual bar width (cap at 100% = 10 seconds)
        const barPct = Math.min((durationMs / 10000) * 100, 100);
        const barColor = durationMs < 1000 ? 'var(--success)' : durationMs < 5000 ? 'var(--warn)' : 'var(--danger)';

        latencyHTML = `
            <div class="audit-detail-section">
                <div class="audit-detail-section-title">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    Performance Metrics
                </div>
                <div class="audit-latency-row">
                    <div class="audit-latency-stat">
                        <span class="label">Latency</span>
                        <span class="value">${durationMs.toFixed(0)}</span>
                        <span class="unit">ms</span>
                    </div>
                    <div class="audit-latency-stat">
                        <span class="label">Duration</span>
                        <span class="value">${durationSec}</span>
                        <span class="unit">seconds</span>
                    </div>
                    <div class="audit-latency-stat">
                        <span class="label">Status</span>
                        <span class="value" style="font-size:14px;">
                            <span class="status-tag ${exec.status === 'success' ? 'success' : 'error'}">${(exec.status || 'unknown').toUpperCase()}</span>
                        </span>
                        <span class="unit">&nbsp;</span>
                    </div>
                </div>
                <div class="audit-latency-bar">
                    <i style="width:${barPct}%;background:${barColor};"></i>
                </div>
            </div>
        `;
    }

    // Build input/output payload section
    let payloadHTML = '';
    if (exec) {
        const inputStr = exec.request_payload
            ? (typeof exec.request_payload === 'object' ? JSON.stringify(exec.request_payload, null, 2) : String(exec.request_payload))
            : '—';
        const outputStr = exec.response_payload
            ? (typeof exec.response_payload === 'object' ? JSON.stringify(exec.response_payload, null, 2) : String(exec.response_payload))
            : '—';

        payloadHTML = `
            <div class="audit-detail-section">
                <div class="audit-detail-section-title">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>
                    Execution Input / Output
                </div>
                <div class="audit-payload-block">
                    <div class="audit-payload-label">
                        <span class="direction-badge input">▶ INPUT</span>
                        Request Payload
                    </div>
                    <pre class="audit-payload-code">${escapeHtml(inputStr)}</pre>
                </div>
                <div class="audit-payload-block">
                    <div class="audit-payload-label">
                        <span class="direction-badge output">◀ OUTPUT</span>
                        Response Payload
                    </div>
                    <pre class="audit-payload-code">${escapeHtml(outputStr)}</pre>
                </div>
            </div>
        `;
    } else {
        payloadHTML = `
            <div class="audit-detail-section">
                <div class="audit-detail-section-title">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>
                    Execution Data
                </div>
                <div class="audit-no-exec">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>
                    <span>No related execution log found for this audit event</span>
                </div>
            </div>
        `;
    }

    content.innerHTML = `
        <!-- Meta Information -->
        <div class="audit-detail-section">
            <div class="audit-detail-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/></svg>
                Event Information
            </div>
            <div class="audit-meta-grid">
                <div class="audit-meta-item">
                    <span class="audit-meta-label">Timestamp</span>
                    <span class="audit-meta-value mono" style="font-size:13px;">${timestamp}</span>
                </div>
                <div class="audit-meta-item">
                    <span class="audit-meta-label">Actor</span>
                    <span class="audit-meta-value"><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent)">${data.actor || '—'}</span></span>
                </div>
                <div class="audit-meta-item">
                    <span class="audit-meta-label">Action</span>
                    <span class="audit-meta-value" style="font-weight:600;">${data.action || '—'}</span>
                </div>
                <div class="audit-meta-item">
                    <span class="audit-meta-label">IP Address</span>
                    <span class="audit-meta-value mono" style="font-size:13px;">${data.ip_address || '—'}</span>
                </div>
                <div class="audit-meta-item" style="grid-column: 1 / -1;">
                    <span class="audit-meta-label">Event ID</span>
                    <span class="audit-meta-value mono" style="font-size:12px;color:var(--fg-muted);">#${data.id}</span>
                </div>
            </div>
        </div>

        <!-- Details JSON -->
        ${detailsStr ? `
        <div class="audit-detail-section">
            <div class="audit-detail-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/></svg>
                Event Details
            </div>
            <pre class="audit-payload-code">${escapeHtml(detailsStr)}</pre>
        </div>
        ` : ''}

        <!-- Latency Metrics -->
        ${latencyHTML}

        <!-- Input / Output -->
        ${payloadHTML}
    `;

    // Animate latency bar after render
    if (exec && exec.duration_ms !== undefined) {
        setTimeout(() => {
            const bar = content.querySelector('.audit-latency-bar i');
            if (bar) {
                const target = bar.style.width;
                bar.style.width = '0%';
                requestAnimationFrame(() => {
                    bar.style.width = target;
                });
            }
        }, 50);
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* =================== BILLING REPORT CONTROLLER =================== */
let activeCycleKey = 'this';

function filterBillingCycle(cycle, btn) {
    activeCycleKey = cycle;
    document.querySelectorAll('.seg button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderBillingReport();
}

async function renderBillingReport() {
    // Set loading placeholders for billing summary fields (no skeletons)
    const summaryIds = [
        'billCycleLabel', 'billTotalDue', 'billProjected', 'billExecCount',
        'breakdownCompute', 'breakdownAPI', 'breakdownStorage', 'breakdownNetwork', 'breakdownTotal',
        'statCurrentSpend', 'statCurrentSpendSub', 'billBudgetSub', 'billProjectedSub'
    ];
    summaryIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerText = '—';
    });

    const barEl = document.getElementById('budgetBar');
    if (barEl) barEl.style.width = '0%';

    const tbody = document.getElementById('billingSandboxTable');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--fg-subtle)">Loading sandbox run costs...</td></tr>';

    const token = localStorage.getItem('thinkdome_token');
    if (!token) return;

    try {
        if (!window.API || typeof window.API.getBillingData !== 'function') {
            throw new Error("API unavailable");
        }
        const res = await window.API.getBillingData(activeCycleKey);
        if (res.error) throw new Error(res.error);
        const data = res.data;
        if (!data) throw new Error("No billing data returned");

        const labelEl = document.getElementById('billCycleLabel');
        if (labelEl) labelEl.innerText = data.label || '—';
        
        const dueEl = document.getElementById('billTotalDue');
        if (dueEl) dueEl.innerText = data.total || '$0.00';
        
        const spendEl = document.getElementById('statCurrentSpend');
        if (spendEl) spendEl.innerText = data.total || '$0.00';
        
        const spendSubEl = document.getElementById('statCurrentSpendSub');
        const budgetSubEl = document.getElementById('billBudgetSub');
        const budgetText = `${data.budgetPct || 0}% of ${data.budgetLimit || '$600.00'} budget limit`;
        if (spendSubEl) spendSubEl.innerText = budgetText;
        if (budgetSubEl) budgetSubEl.innerText = budgetText;

        const projEl = document.getElementById('billProjected');
        if (projEl) projEl.innerText = data.projected || '$0.00';
        
        const projSubEl = document.getElementById('billProjectedSub');
        if (projSubEl) {
            if (data.overBudget) {
                projSubEl.innerText = `+${data.overPct || 0}% over budget limit`;
                projSubEl.style.color = 'var(--danger)';
                projSubEl.style.fontWeight = '600';
            } else {
                projSubEl.innerText = 'Under budget limit';
                projSubEl.style.color = 'var(--success)';
                projSubEl.style.fontWeight = '600';
            }
        }

        const execEl = document.getElementById('billExecCount');
        if (execEl) execEl.innerText = data.execs || '0';

        const bcEl = document.getElementById('breakdownCompute');
        if (bcEl) bcEl.innerText = data.compute || '$0.00';
        
        const baEl = document.getElementById('breakdownAPI');
        if (baEl) baEl.innerText = data.api || '$0.00';
        
        const bsEl = document.getElementById('breakdownStorage');
        if (bsEl) bsEl.innerText = data.storage || '$0.00';
        
        const bnEl = document.getElementById('breakdownNetwork');
        if (bnEl) bnEl.innerText = data.network || '$0.00';
        
        const btEl = document.getElementById('breakdownTotal');
        if (btEl) btEl.innerText = data.total || '$0.00';

        const pct = parseFloat(data.budgetPct) || 0;
        if (barEl) barEl.style.width = pct + '%';

        if (tbody && data.sandboxes) {
            const allSandboxKeys = new Set([...Object.keys(data.sandboxes), ...Object.keys(state.sandboxes)]);
            if (allSandboxKeys.size === 0) {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--fg-subtle)">No sandbox billing data available</td></tr>`;
            } else {
                tbody.innerHTML = Array.from(allSandboxKeys).map(key => {
                    const item = data.sandboxes[key] || { uptime: '—', rate: '—', compute: '—', execs: '—', subtotal: '—' };
                    const runtime = state.sandboxes[key] ? state.sandboxes[key].runtime : '—';
                    return `
                      <tr>
                        <td style="font-weight: 600;">${key}</td>
                        <td class="mono">${runtime}</td>
                        <td class="mono">${item.uptime}</td>
                        <td class="mono">${item.rate}</td>
                        <td class="mono">${item.compute}</td>
                        <td class="mono">${item.execs}</td>
                        <td class="mono" style="font-weight: 700; color:var(--fg);">${item.subtotal}</td>
                      </tr>
                    `;
                }).join('');
            }
        } else if (tbody) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--fg-subtle)">No sandbox billing data available</td></tr>`;
        }

        const chart = document.getElementById('spendChartContainer');
        if (chart) {
            chart.style.opacity = '0.5';
            setTimeout(() => { chart.style.opacity = '1'; }, 150);
        }
    } catch (err) {
        console.warn("Billing report offline:", err);
        summaryIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `<span style="font-size:13px;color:var(--fg-subtle)">—</span>`;
        });
        if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:20px 12px;color:var(--fg-subtle);font-size:13px;"><div style="display:flex;flex-direction:column;align-items:center;gap:6px;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.4"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>Waiting for billing data…</div></td></tr>`;
    }
}

async function downloadInvoice() {
    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) throw new Error("API Offline");
        const res = await window.API.downloadInvoice(activeCycleKey, token);
        if (res.error) throw new Error(res.error);
        const invoiceId = res.data?.invoice_id || 'unknown';
        const downloadUrl = res.data?.download_url || `/v1/admin/billing/invoice/download/${invoiceId}`;
        
        // Initiate actual browser download
        const a = document.createElement('a');
        // Same-origin downloads automatically include the HttpOnly session cookie;
        // never place bearer tokens in URLs where proxies/history can log them.
        a.href = downloadUrl;
        a.download = `invoice-${invoiceId}.pdf`;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        await showCustomAlert("Invoice Compiled", `Invoice #${invoiceId} compiled and download initiated.`);
        addAuditEvent(`Invoice #${invoiceId} downloaded`);
    } catch (err) {
        await showCustomAlert("Invoice Download Failed", `Failed to compile invoice: ${err.message || err}`);
    }
}

/* =================== API KEYS CONTROLLER =================== */
function maskToken(token) {
    if (!token) return '';
    if (token.length <= 12) return '••••••••';
    const prefix = token.substring(0, 8);
    const suffix = token.substring(token.length - 4);
    return `${prefix}••••••••${suffix}`;
}

function renderApiKeysHTMLOnly() {
    const tbody = document.getElementById('apiKeysTableBody');
    if (!tbody) return;
    tbody.innerHTML = state.apiKeys.map((k, index) => {
        const nameVal = k.name || k.display_name;
        const tokVal = k.masked_token || k.token;
        const typeVal = k.token_type || k.type;
        const statusVal = k.status;
        const isRevoked = statusVal === 'REVOKED' || statusVal === 'revoked';
        const displayStatus = isRevoked ? 'REVOKED' : 'ACTIVE';
        return `
            <tr>
              <td style="font-weight:600;">${nameVal}</td>
              <td class="mono" style="font-size: 13px;">${maskToken(tokVal)}</td>
              <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent);">${typeVal} Token</span></td>
              <td><span class="status-tag ${displayStatus === 'ACTIVE' ? 'success' : 'error'}">${displayStatus}</span></td>
              <td>
                ${displayStatus === 'ACTIVE' ? `<button class="btn btn-ghost btn-sm" style="color:var(--danger); border-color:var(--danger-subtle);" onclick="revokeKey('${k.key_id || index}', ${index})">Revoke</button>` : `<span class="faint" style="font-size:12px;color:var(--fg-subtle)">Revoked</span>`}
              </td>
            </tr>
        `;
    }).join('');
}

async function renderApiKeys() {
    const role = localStorage.getItem('thinkdome_user_role');
    const authorized = typeof isAdminRole === 'function'
        ? isAdminRole(role)
        : ['ADMIN', 'SUPER_ADMIN', 'ENTERPRISE_ADMIN'].includes(String(role || '').toUpperCase());
    if (!authorized) return;
    const tbody = document.getElementById('apiKeysTableBody');
    if (tbody) tbody.innerHTML = getTableSkeletonHTML(5, 3);

    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) throw new Error("Offline");
        const { data, error } = await window.API.getApiKeys(token);
        if (error) throw new Error(error);

        if (data) {
            state.apiKeys = data.map(k => ({
                name: k.display_name,
                token: k.masked_token || k.token,
                type: k.token_type,
                status: k.status,
                key_id: k.key_id
            }));
        }
        renderApiKeysHTMLOnly();
    } catch {
        renderApiKeysHTMLOnly();
    }
}

async function generateNewKey(e) {
    e.preventDefault();
    const nameInput = document.getElementById('keyName');
    const typeInput = document.getElementById('keyType');
    if (!nameInput || !typeInput) return;

    const name = nameInput.value.trim();
    const type = typeInput.value;
    if (!name) return;

    const btn = e.target.querySelector('button[type="submit"]');
    const originalBtn = btn ? btn.innerText : '';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Creating...';
    }

    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) throw new Error("API Offline");
        const { data, error } = await window.API.createApiKey({
            display_name: name,
            token_type: type,
            expires_at: null
        }, token);

        if (error) throw new Error(error);

        nameInput.value = '';
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalBtn;
        }

        const rawToken = data.token;
        try {
            await navigator.clipboard.writeText(rawToken);
        } catch {}

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Created new secure API token: ${name}`);
        }
        addAuditEvent(`Generated API Key: ${name}`);

        await renderApiKeys();

        await showCustomAlert("Secure API Key Generated", `
          <span style="display:block; margin-bottom:12px; font-size:13.5px; color:var(--fg-muted);">Here is your new API key. We have copied it to your clipboard automatically.</span>
          <div style="background:var(--surface-raised); border:1px solid var(--border); border-radius:var(--radius-md); padding:14px; font-family:var(--font-mono); color:var(--accent); font-weight:600; text-align:center; word-break:break-all; font-size:13.5px; margin-bottom:12px; user-select:all;">
            ${rawToken}
          </div>
          <button class="btn btn-ghost" id="btn-copy-modal-key" style="width:100%; margin-bottom:12px; border-color:var(--accent-subtle); color:var(--accent); font-size:12.5px;" onclick="navigator.clipboard.writeText('${rawToken}').then(() => { const el = document.getElementById('btn-copy-modal-key'); el.innerHTML = '✓ Copied!'; setTimeout(() => el.innerHTML = 'Copy Key to Clipboard', 2000); })">
            Copy Key to Clipboard
          </button>
          <span style="color:var(--danger); font-size:12px; font-weight:600; display:block;">⚠️ Save this key securely. For security reasons, you will not be able to view it again.</span>
        `);

    } catch (err) {
        nameInput.value = '';
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalBtn;
        }
        await showCustomAlert("Failed to Generate Key", `Error generating API Key: ${err.message || err}`);
    }
}

async function revokeKey(keyId, index) {
    const keyItem = state.apiKeys.find(k => k.key_id === keyId) || state.apiKeys[index];
    const keyName = keyItem ? keyItem.name : "this key";
    const ok = await showCustomConfirm("Revoke API Key Credentials", `Are you sure you want to permanently revoke credentials for "${keyName}"?`);
    if (ok) {
        const token = localStorage.getItem('thinkdome_token');
        try {
            if (!window.API || !token) throw new Error("Offline or Unauthorized");
            const { error } = await window.API.revokeApiKey(keyId, token);
            if (error) throw new Error(error);
            
            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Revoked token authentication key: ${keyName}`);
            }
            addAuditEvent(`Revoked API Key: ${keyName}`);
            await renderApiKeys();
        } catch (err) {
            await showCustomAlert("Revocation Failed", `Failed to revoke API key: ${err.message || err}`);
        }
    }
}

async function loadMcpTools() {
    const tbody = document.getElementById('mcpToolsTableBody');
    const token = localStorage.getItem('thinkdome_token') || "";
    ensureMcpRegistryControls();
    
    try {
        if (window.API && typeof window.API.getTools === 'function') {
            const { data, error } = await window.API.getTools(token);
            if (!error && Array.isArray(data)) {
                renderMcpToolsTable(data);
                return;
            }
        }
    } catch (err) {
        console.warn("API getTools failed, using 24 built-in MCP tools fallback:", err);
    }
    
    // Do not fabricate a registry when the server is unavailable. The MCP
    // page is server-authoritative and must show an explicit unavailable state.
    renderMcpToolsTable([]);
}

function isMcpAdministrator() {
    let roles = [];
    try { roles = JSON.parse(localStorage.getItem('thinkdome_user_roles') || '[]'); } catch (_) { roles = []; }
    const values = Array.isArray(roles) ? [...roles] : [];
    values.push(localStorage.getItem('thinkdome_user_role') || '');
    return values.some(role => ['ADMIN', 'ADMINISTRATOR', 'SUPERADMIN', 'SUPER_ADMIN', 'ENTERPRISE_ADMIN']
        .includes(String(role).toUpperCase()));
}

function ensureMcpRegistryControls() {
    const page = document.getElementById('page-mcp');
    if (!page || !isMcpAdministrator() || document.getElementById('mcpRegistryControls')) return;
    const panel = document.createElement('div');
    panel.id = 'mcpRegistryControls';
    panel.className = 'table-card';
    panel.style.cssText = 'padding:16px;margin-bottom:24px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;';
    const copy = document.createElement('div');
    const title = document.createElement('h3'); title.textContent = 'MCP Policy Registry'; title.style.margin = '0 0 4px';
    const hint = document.createElement('p'); hint.textContent = 'Manage title, activation, and role access for registered tools.'; hint.style.cssText = 'font-size:12.5px;color:var(--fg-muted);margin:0;';
    copy.append(title, hint);
    const button = document.createElement('button'); button.className = 'btn btn-primary'; button.textContent = '+ Register Tool Policy';
    button.onclick = () => editMcpToolPolicy();
    panel.append(copy, button);
    const anchor = page.querySelector('#mcpToolsTableBody')?.closest('.table-card');
    if (anchor) anchor.parentNode.insertBefore(panel, anchor);
}

function closeMcpPolicyModal() {
    const modal = document.getElementById('mcpPolicyModal');
    if (modal) { modal.classList.remove('active'); modal.hidden = true; }
}

async function loadMcpPolicyRoles(selected = []) {
    const select = document.getElementById('mcpPolicyRoles');
    if (!select) return;
    const token = localStorage.getItem('thinkdome_token') || '';
    const headers = { Authorization: `Bearer ${token}` };
    const names = new Set();
    try {
        const response = await fetch('/v1/roles', { headers });
        if (response.ok) {
            const payload = await response.json();
            (Array.isArray(payload) ? payload : payload.roles || []).forEach(role => names.add(String(role.name || role)));
        }
    } catch (_) { /* role profiles may still provide usable options */ }
    try {
        const response = await fetch('/v1/role-profiles', { headers });
        if (response.ok) {
            const profiles = await response.json();
            profiles.forEach(profile => (profile.roles || []).forEach(role => names.add(String(role))));
        }
    } catch (_) { /* optional role-profile endpoint */ }
    selected.forEach(role => names.add(String(role)));
    select.replaceChildren();
    [...names].filter(Boolean).sort((a, b) => a.localeCompare(b)).forEach(role => {
        const option = new Option(role, role, false, selected.some(item => String(item).toUpperCase() === role.toUpperCase()));
        select.appendChild(option);
    });
    if (!select.options.length) {
        const option = new Option('No registered roles found', '', false, false);
        option.disabled = true;
        select.appendChild(option);
    }
}

async function editMcpToolPolicy(tool = null) {
    if (typeof tool === 'string') {
        tool = ((window.state && window.state.allMcpTools) || []).find(item => item.name === tool) || { name: tool };
    }
    const modal = document.getElementById('mcpPolicyModal');
    if (!modal) return;
    document.getElementById('mcpPolicyModalTitle').textContent = tool?.name ? 'Edit MCP Tool Policy' : 'Register MCP Tool Policy';
    document.getElementById('mcpPolicyOriginalName').value = tool?.name || '';
    document.getElementById('mcpPolicyName').value = tool?.name || '';
    document.getElementById('mcpPolicyTitle').value = tool?.title || tool?.name || '';
    document.getElementById('mcpPolicyDescription').value = tool?.description || '';
    document.getElementById('mcpPolicyScope').value = tool?.required_scope || '';
    await loadMcpPolicyRoles(tool?.allowed_roles || []);
    document.getElementById('mcpPolicyActive').checked = tool?.is_active !== false;
    document.getElementById('mcpPolicyDelete').hidden = !tool?.name;
    document.getElementById('mcpPolicyRuntimeInfo').textContent = tool?.is_runtime_registered === false
        ? 'Policy saved, but no executable implementation is registered yet.'
        : tool?.name ? 'Executable implementation is registered in the runtime tool registry.' : 'New policies can be attached to a registered MCP tool.';
    document.getElementById('mcpPolicyError').hidden = true;
    modal.hidden = false;
    modal.classList.add('active');
    modal.onclick = event => { if (event.target === modal) closeMcpPolicyModal(); };
    document.getElementById('mcpPolicyName').focus();
}

async function submitMcpPolicyModal(event) {
    event.preventDefault();
    const originalName = document.getElementById('mcpPolicyOriginalName').value;
    const name = document.getElementById('mcpPolicyName').value.trim();
    const error = document.getElementById('mcpPolicyError');
    const payload = { name, title: document.getElementById('mcpPolicyTitle').value.trim(),
        description: document.getElementById('mcpPolicyDescription').value.trim(),
        required_scope: document.getElementById('mcpPolicyScope').value.trim() || null,
        is_active: document.getElementById('mcpPolicyActive').checked,
        allowed_roles: [...document.getElementById('mcpPolicyRoles').selectedOptions].map(option => option.value).filter(Boolean) };
    try {
        const endpoint = `/v1/tools/metadata${originalName ? `/${encodeURIComponent(originalName)}` : ''}`;
        const response = await fetch(endpoint, { method: originalName ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('thinkdome_token') || ''}` }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'MCP policy update failed');
        closeMcpPolicyModal();
        await loadMcpTools();
    } catch (e) {
        error.textContent = e.message;
        error.hidden = false;
    }
}

async function deleteMcpPolicyFromModal() {
    const name = document.getElementById('mcpPolicyOriginalName').value;
    if (!name || !confirm(`Delete the saved policy for '${name}'? It will be retained as inactive so the tool cannot be re-enabled accidentally.`)) return;
    try {
        const response = await fetch(`/v1/tools/metadata/${encodeURIComponent(name)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.getItem('thinkdome_token') || ''}` } });
        if (!response.ok) throw new Error('MCP policy deletion failed');
        closeMcpPolicyModal();
        await loadMcpTools();
    } catch (e) {
        const error = document.getElementById('mcpPolicyError'); error.textContent = e.message; error.hidden = false;
    }
}

async function deleteMcpToolPolicy(name) {
    if (!confirm(`Delete the saved policy for '${name}'? The executable code registry will not be modified.`)) return;
    const response = await fetch(`/v1/tools/metadata/${encodeURIComponent(name)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.getItem('thinkdome_token') || ''}` } });
    if (!response.ok) throw new Error('MCP policy deletion failed');
    await loadMcpTools();
}

const BUILTIN_MCP_TOOLS_FALLBACK = [
    { name: "read_file", app_name: "storage", required_scope: "file:read", is_active: true, description: "Read workspace file content by absolute or relative path" },
    { name: "write_file", app_name: "storage", required_scope: "file:write", is_active: true, description: "Write string or binary content to isolated workspace file" },
    { name: "list_dir", app_name: "storage", required_scope: "file:read", is_active: true, description: "List files and subdirectories with sizes and metadata" },
    { name: "file_exists", app_name: "storage", required_scope: "file:read", is_active: true, description: "Check if a specific path exists in the sandbox" },
    { name: "make_dir", app_name: "storage", required_scope: "file:write", is_active: true, description: "Create a directory path recursively" },
    { name: "remove_file", app_name: "storage", required_scope: "file:destructive", is_active: true, description: "Delete a file permanently from workspace" },
    { name: "remove_dir", app_name: "storage", required_scope: "file:destructive", is_active: true, description: "Delete a directory tree recursively" },
    { name: "move_file", app_name: "storage", required_scope: "file:destructive", is_active: true, description: "Move or rename a file or directory" },
    { name: "copy_file", app_name: "storage", required_scope: "file:write", is_active: true, description: "Copy a file within the workspace" },
    { name: "run_code", app_name: "execution", required_scope: "code:run", is_active: true, description: "Execute Python / JavaScript code in containerized backend" },
    { name: "shell_exec", app_name: "execution", required_scope: "shell:run", is_active: true, description: "Execute shell command within sandbox bounds" },
    { name: "web_search", app_name: "search", required_scope: "web:search", is_active: true, description: "Search the web via egress proxy with domain rules" },
    { name: "grep_search", app_name: "search", required_scope: "file:read", is_active: true, description: "Search file contents with regular expressions" },
    { name: "find_files", app_name: "search", required_scope: "file:read", is_active: true, description: "Locate files matching glob patterns" },
    { name: "get_file_info", app_name: "search", required_scope: "file:read", is_active: true, description: "Retrieve metadata, permissions, and hash of a file" },
    { name: "hash_file", app_name: "search", required_scope: "file:read", is_active: true, description: "Compute SHA-256 or MD5 hash of workspace file" },
    { name: "memory_store", app_name: "memory", required_scope: "memory:write", is_active: true, description: "Store key-value entry in persistent agent memory" },
    { name: "memory_retrieve", app_name: "memory", required_scope: "memory:read", is_active: true, description: "Retrieve stored memory entry by key" },
    { name: "memory_search", app_name: "memory", required_scope: "memory:read", is_active: true, description: "Search agent memory entries by similarity or key" },
    { name: "memory_delete", app_name: "memory", required_scope: "memory:delete", is_active: true, description: "Remove entry from agent memory store" },
    { name: "memory_list", app_name: "memory", required_scope: "memory:read", is_active: true, description: "List available memory keys and namespaces" },
    { name: "http_request", app_name: "network", required_scope: "network:all", is_active: true, description: "Make HTTP request subject to strict egress firewall policies" },
    { name: "send_email", app_name: "comms", required_scope: "comms:send", is_active: true, description: "Send notification email via configured SMTP relay" },
    { name: "send_telegram", app_name: "comms", required_scope: "comms:send", is_active: true, description: "Send agent status message via Telegram bot API" },
];

const MCP_TOOL_JSON_PAYLOAD_MAP = {
    read_file: { path: "/workspace/README.md" },
    write_file: { path: "/workspace/config.json", content: "{\n  \"status\": \"active\",\n  \"env\": \"production\"\n}" },
    list_dir: { path: "/workspace" },
    file_exists: { path: "/workspace/package.json" },
    make_dir: { path: "/workspace/output/logs" },
    remove_file: { path: "/workspace/temp.log" },
    remove_dir: { path: "/workspace/tmp_cache" },
    move_file: { source: "/workspace/old.txt", destination: "/workspace/new.txt" },
    copy_file: { source: "/workspace/sample.py", destination: "/workspace/sample_backup.py" },
    run_code: { language: "python", code: "import sys\nprint(f'Python Version: {sys.version}')" },
    shell_exec: { command: "ls -la /workspace" },
    web_search: { query: "ThinkDome Python SDK documentation", limit: 5 },
    grep_search: { pattern: "def ", path: "/workspace" },
    find_files: { pattern: "*.py", path: "/workspace" },
    get_file_info: { path: "/workspace/README.md" },
    hash_file: { path: "/workspace/README.md", algorithm: "sha256" },
    memory_store: { key: "agent_checkpoint_01", value: { step: 5, score: 0.98 } },
    memory_retrieve: { key: "agent_checkpoint_01" },
    memory_search: { query: "checkpoint", limit: 5 },
    memory_delete: { key: "agent_checkpoint_01" },
    memory_list: { namespace: "default" },
    http_request: { url: "https://api.github.com/zen", method: "GET" },
    send_email: { to: "dev@thinkdome.dev", subject: "Sandbox Deployment Alert", body: "Sandbox container SBX-8849 booted successfully." },
    send_telegram: { chat_id: "@thinkdome_alerts", message: "● Active Agent Lease Renewal: 300s" }
};

function renderMcpToolsTable(tools) {
    const tbody = document.getElementById('mcpToolsTableBody');
    if (!tbody) return;

    const list = Array.isArray(tools) ? tools : [];
    if (!window.state) window.state = typeof state !== 'undefined' ? state : {};
    window.state.allMcpTools = list;

    const statEl = document.getElementById('mcpStatCount');
    if (statEl) statEl.textContent = list.length;
    const headingEl = document.getElementById('mcpRegistryHeading');
    if (headingEl) headingEl.textContent = `Dynamic Tool Registry (${list.length} Tools)`;
    const domains = new Set(list.map(tool => tool.app_name).filter(Boolean));
    const scopes = new Set(list.map(tool => tool.required_scope).filter(Boolean));
    const domainCount = document.getElementById('mcpDomainCount');
    const scopeCount = document.getElementById('mcpScopeCount');
    if (domainCount) domainCount.textContent = domains.size;
    if (scopeCount) scopeCount.textContent = scopes.size;

    const escapeMcpHtml = value => String(value ?? '').replace(/[&<>\"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' }[char]));
    if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--fg-muted);padding:24px;">No MCP tools are available from the server registry.</td></tr>';
        return;
    }
    let html = "";
    list.forEach(t => {
        const domain = escapeMcpHtml(t.app_name || 'general');
        const name = escapeMcpHtml(t.name);
        const title = escapeMcpHtml(t.title || t.name);
        const description = escapeMcpHtml(t.description);
        const scope = escapeMcpHtml(t.required_scope || 'None');
        const domainColor = t.app_name === 'execution' ? 'var(--accent)' : t.app_name === 'storage' ? 'var(--warn)' : t.app_name === 'memory' ? 'var(--success)' : 'var(--fg-muted)';
        const statusBadge = t.is_active === false ? `<span class="badge" style="background:var(--surface-raised);color:var(--fg-muted);padding:2px 7px;font-size:11px;font-weight:600;">Inactive</span>` : `<span class="badge" style="background:var(--success-subtle);color:var(--success);padding:2px 7px;font-size:11px;font-weight:600;">Active</span>`;
        const safeToolArg = escapeMcpHtml(JSON.stringify(String(t.name || '')));
        const adminActions = isMcpAdministrator() ? `<button class="btn btn-ghost btn-sm" onclick="editMcpToolPolicy(${safeToolArg})" style="padding:4px 8px;font-size:11px;">Edit</button><button class="btn btn-danger btn-sm" onclick="deleteMcpToolPolicy(${safeToolArg})" style="padding:4px 8px;font-size:11px;">Delete</button>` : '';
        const testAction = t.is_runtime_registered === false ? '<span class="mono-muted" title="This policy has no executable implementation registered">Policy only</span>' : `<button class="btn btn-primary btn-sm" onclick="testMcpTool(${safeToolArg})" style="padding:4px 10px;font-size:11.5px;font-weight:600;white-space:nowrap;">⚡ Test Tool</button>`;
        
        html += `
            <tr style="border-bottom:1px solid var(--border);transition:background 0.1s ease;">
                <td style="padding:8px 12px;font-weight:700;color:var(--fg);font-family:var(--font-mono);font-size:12.5px;">${name}</td>
                <td style="padding:8px 10px;color:var(--fg);">${title}</td>
                <td style="padding:8px 10px;"><span style="background:var(--surface-raised);color:${domainColor};padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid var(--border);display:inline-block;">${domain}</span></td>
                <td style="padding:8px 10px;"><span style="font-family:var(--font-mono);font-size:11px;padding:2px 6px;background:var(--surface-raised);border-radius:4px;border:1px solid var(--border);color:var(--fg-muted);">${scope}</span></td>
                <td style="padding:8px 10px;">${statusBadge}</td>
                <td style="padding:8px 12px;color:var(--fg-muted);font-size:12.5px;line-height:1.35;">${description}</td>
                <td style="padding:8px 12px;text-align:right;">
                    ${testAction}${adminActions}
                </td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

function filterMcpToolsTable() {
    const term = (document.getElementById('mcpSearchInput')?.value || '').toLowerCase();
    const allTools = (window.state && window.state.allMcpTools) || [];
    if (!term) {
        renderMcpToolsTable(allTools);
        return;
    }
    const filtered = allTools.filter(t => 
        t.name.toLowerCase().includes(term) || 
        t.description.toLowerCase().includes(term) ||
        t.app_name.toLowerCase().includes(term)
    );
    renderMcpToolsTable(filtered);
}

async function testMcpTool(toolName) {
    const token = localStorage.getItem('thinkdome_token');
    const defaultPayloadObj = MCP_TOOL_JSON_PAYLOAD_MAP[toolName] || { tool: toolName, params: {} };
    const defaultPayload = JSON.stringify(defaultPayloadObj, null, 2);

    const inputStr = await openMcpTestModal(toolName, defaultPayload);
    if (inputStr === null) return;

    let toolInput = {};
    try {
        toolInput = inputStr.trim() ? JSON.parse(inputStr) : {};
    } catch {
        const modalError = document.getElementById('mcpTestError');
        if (modalError) {
            modalError.textContent = 'Please enter valid JSON before executing this tool.';
            modalError.hidden = false;
        }
        return;
    }

    try {
        const payload = {
            type: "tool_use",
            id: `toolu_test_${Date.now()}`,
            name: toolName,
            input: toolInput
        };

        if (window.API && typeof window.API.orchestrate === 'function') {
            const res = await window.API.orchestrate(payload, token);
            if (res.error) {
                showMcpTestResult('Tool execution failed', res.error, false);
            } else {
                let contentText = res.data ? (res.data.content || JSON.stringify(res.data, null, 2)) : "";
                showMcpTestResult('Tool executed successfully', contentText || JSON.stringify(res.data, null, 2), true);
            }
        } else {
            showMcpTestResult('Tool executed successfully', JSON.stringify({
                status: "success",
                tool: toolName,
                input: toolInput,
                result: `Simulated execution output for ${toolName}`
            }, null, 2), true);
        }
    } catch (e) {
        showMcpTestResult('Execution error', e.message || String(e), false);
    }
}

let mcpTestResolver = null;
function openMcpTestModal(toolName, payload) {
    const modal = document.getElementById('mcpTestModal');
    const title = document.getElementById('mcpTestTitle');
    const input = document.getElementById('mcpTestInput');
    const error = document.getElementById('mcpTestError');
    const resultBox = document.getElementById('mcpTestResultBox');
    const result = document.getElementById('mcpTestResult');
    const execute = document.getElementById('mcpTestExecuteBtn');
    
    if (!modal || !input) return Promise.resolve(payload);
    
    title.textContent = `Test Tool: ${toolName}`;
    input.value = payload;
    input.hidden = false;
    input.style.display = 'block';
    
    if (error) { error.hidden = true; error.textContent = ''; }
    if (resultBox) resultBox.hidden = true;
    if (result) result.textContent = '';
    if (execute) execute.hidden = false;
    
    modal.classList.add('active');
    setTimeout(() => input.focus(), 100);
    return new Promise(resolve => { mcpTestResolver = resolve; });
}

function showMcpTestResult(title, message, success) {
    const modal = document.getElementById('mcpTestModal');
    const titleEl = document.getElementById('mcpTestTitle');
    const resultBox = document.getElementById('mcpTestResultBox');
    const result = document.getElementById('mcpTestResult');
    const execute = document.getElementById('mcpTestExecuteBtn');
    
    if (!modal || !result) return;
    
    titleEl.textContent = title;
    if (resultBox) resultBox.hidden = false;
    result.textContent = message;
    result.style.borderColor = success ? 'var(--success)' : 'var(--danger)';
    if (execute) execute.hidden = true;
    
    modal.classList.add('active');
}

function closeMcpTestModal() {
    const modal = document.getElementById('mcpTestModal');
    if (modal) modal.classList.remove('active');
    if (mcpTestResolver) { mcpTestResolver(null); mcpTestResolver = null; }
}

function submitMcpTestModal() {
    const input = document.getElementById('mcpTestInput');
    const error = document.getElementById('mcpTestError');
    try {
        JSON.parse(input.value);
    } catch (_) {
        if (error) {
            error.textContent = 'Please enter valid JSON before executing this tool.';
            error.hidden = false;
        }
        return;
    }
    const value = input.value;
    const modal = document.getElementById('mcpTestModal');
    if (modal) modal.classList.remove('active');
    if (mcpTestResolver) { mcpTestResolver(value); mcpTestResolver = null; }
}

function copyMcpConfig() {
    const code = document.getElementById('mcpConfigCode').innerText;
    const button = document.querySelector('[onclick="copyMcpConfig()"]');
    navigator.clipboard.writeText(code).then(() => {
        if (!button) return;
        const original = button.textContent;
        button.textContent = 'Copied';
        button.classList.add('is-success');
        window.setTimeout(() => {
            button.textContent = original;
            button.classList.remove('is-success');
        }, 1600);
    }).catch(err => {
        console.error("Failed to copy text: ", err);
        if (button) button.textContent = 'Copy failed';
    });
}

function downloadMcpConfig() {
    const code = document.getElementById('mcpConfigCode')?.innerText || '';
    const blob = new Blob([code], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'thinkdome-mcp-config.json';
    link.click();
    URL.revokeObjectURL(url);
}
