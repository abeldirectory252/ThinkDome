// static/js/dashboard.js

/* =================== CORE THEMING (Auto detection) =================== */
function initTheme() {
    // Check if user has explicit theme preference or follow browser
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (prefersDark) {
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
    if (typeof editorInstance !== 'undefined' && editorInstance) {
        monaco.editor.setTheme(state.theme === 'dark' ? 'vs-dark' : 'vs');
    }
}

/* =================== AUDITING & RECENT RUNS =================== */
function addAuditEvent(detail) {
    const timeStr = new Date().toTimeString().split(' ')[0];
    state.auditEvents.unshift({ ts: timeStr, actor: 'admin', detail: detail });
}

function refreshDash(btn) {
    btn.style.opacity = '0.5';
    btn.disabled = true;

    // Simulate random fluctuations
    Object.keys(state.sandboxes).forEach(key => {
        if (state.sandboxes[key].status === 'running') {
            state.sandboxes[key].ramUsage = Math.floor(Math.random() * 20) + 50;
        }
    });

    setTimeout(() => {
        btn.style.opacity = '1';
        btn.disabled = false;
        renderAllViews();
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', 'Sandbox status matrices refreshed successfully.');
        }
    }, 600);
}

function renderDashboardRecentTables() {
    // Recent runs (based on mock logs)
    const execBody = document.getElementById('execBody');
    if (!execBody) return;
    const mockRuns = [
        { time: '18:29:12', runtime: 'prod-runner-01', cmd: 'python main.py', status: 'SUCCESS' },
        { time: '18:24:50', runtime: 'agent-worker-02', cmd: 'node index.js', status: 'SUCCESS' },
        { time: '18:20:11', runtime: 'batch-eval-03', cmd: 'pip install openai', status: 'SUCCESS' },
        { time: '18:02:44', runtime: 'prod-runner-01', cmd: 'python agent.py', status: 'WARN' },
        { time: '17:41:09', runtime: 'staging-test-04', cmd: 'npm run dev', status: 'ERROR' }
    ];

    execBody.innerHTML = mockRuns.map(run => `
        <tr>
          <td class="time">${run.time}</td>
          <td><span class="action-tag">${run.runtime}</span></td>
          <td class="mono" style="font-size:12.5px;">${run.cmd}</td>
          <td><span class="status-tag ${run.status === 'SUCCESS' ? 'success' : run.status === 'WARN' ? 'warn' : 'error'}">${run.status}</span></td>
        </tr>
      `).join('');

    // Infrastructure logs
    const auditBody = document.getElementById('auditBody');
    if (auditBody) {
        auditBody.innerHTML = state.auditEvents.slice(0, 5).map(ev => `
            <tr>
              <td class="time">${ev.ts}</td>
              <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent)">${ev.actor}</span></td>
              <td style="font-size:13px;font-weight:500;">${ev.detail}</td>
            </tr>
          `).join('');
    }

    // Full Audit stream page
    const auditFullBody = document.getElementById('auditFullBody');
    if (auditFullBody) {
        auditFullBody.innerHTML = state.auditEvents.map(ev => `
            <tr>
              <td class="time">${ev.ts}</td>
              <td><span class="action-tag">prod-runner-01</span></td>
              <td class="mono">SYSTEM_EVENT</td>
              <td><span class="status-tag success">AUDIT_OK</span></td>
              <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent)">${ev.actor}</span></td>
              <td style="font-weight:500;">${ev.detail}</td>
            </tr>
          `).join('');
    }
}

/* =================== BILLING REPORT CONTROLLER =================== */
const billingCycles = {
    this: {
        label: 'Current cycle · Jun 1 – Jun 12, 2026',
        total: '$418.62',
        budgetPct: '70%',
        projected: '$712.30',
        execs: '42,918',
        compute: '$286.40',
        api: '$42.90',
        storage: '$58.10',
        network: '$31.22',
        sandboxes: {
            'prod-runner-01': { uptime: '102h', rate: '$0.08/hr', compute: '$8.57', execs: '$18.40', subtotal: '$26.97' },
            'agent-worker-02': { uptime: '35h', rate: '$0.16/hr', compute: '$5.67', execs: '$9.10', subtotal: '$14.77' },
            'batch-eval-03': { uptime: '7h', rate: '$0.32/hr', compute: '$2.27', execs: '$12.20', subtotal: '$14.47' },
            'staging-test-04': { uptime: '0h', rate: '$0.04/hr', compute: '$0.00', execs: '$0.00', subtotal: '$0.00' }
        }
    },
    last: {
        label: 'Last cycle · May 1 – May 31, 2026',
        total: '$512.44',
        budgetPct: '85%',
        projected: '$512.44',
        execs: '59,102',
        compute: '$352.10',
        api: '$59.10',
        storage: '$62.00',
        network: '$39.24',
        sandboxes: {
            'prod-runner-01': { uptime: '320h', rate: '$0.08/hr', compute: '$25.60', execs: '$44.10', subtotal: '$69.70' },
            'agent-worker-02': { uptime: '180h', rate: '$0.16/hr', compute: '$28.80', execs: '$32.40', subtotal: '$61.20' },
            'batch-eval-03': { uptime: '45h', rate: '$0.32/hr', compute: '$14.40', execs: '$52.00', subtotal: '$66.40' },
            'staging-test-04': { uptime: '12h', rate: '$0.04/hr', compute: '$0.48', execs: '$2.10', subtotal: '$2.58' }
        }
    },
    ytd: {
        label: 'Year-to-date (YTD) 2026',
        total: '$2,419.80',
        budgetPct: '50%', // cumulative overall
        projected: '$3,800.00',
        execs: '302,492',
        compute: '$1,620.40',
        api: '$302.50',
        storage: '$312.00',
        network: '$184.90',
        sandboxes: {
            'prod-runner-01': { uptime: '1,420h', rate: '$0.08/hr', compute: '$113.60', execs: '$210.40', subtotal: '$324.00' },
            'agent-worker-02': { uptime: '840h', rate: '$0.16/hr', compute: '$134.40', execs: '$198.20', subtotal: '$332.60' },
            'batch-eval-03': { uptime: '210h', rate: '$0.32/hr', compute: '$67.20', execs: '$345.10', subtotal: '$412.30' },
            'staging-test-04': { uptime: '44h', rate: '$0.04/hr', compute: '$1.76', execs: '$12.40', subtotal: '$14.16' }
        }
    }
};

let activeCycleKey = 'this';

function filterBillingCycle(cycle, btn) {
    activeCycleKey = cycle;
    document.querySelectorAll('.seg button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderBillingReport();
}

function renderBillingReport() {
    const data = billingCycles[activeCycleKey];
    if (!data) return;

    const labelEl = document.getElementById('billCycleLabel');
    if (labelEl) labelEl.innerText = data.label;
    
    const dueEl = document.getElementById('billTotalDue');
    if (dueEl) dueEl.innerText = data.total;
    
    const projEl = document.getElementById('billProjected');
    if (projEl) projEl.innerText = data.projected;
    
    const execEl = document.getElementById('billExecCount');
    if (execEl) execEl.innerText = data.execs;

    const bcEl = document.getElementById('breakdownCompute');
    if (bcEl) bcEl.innerText = data.compute;
    
    const baEl = document.getElementById('breakdownAPI');
    if (baEl) baEl.innerText = data.api;
    
    const bsEl = document.getElementById('breakdownStorage');
    if (bsEl) bsEl.innerText = data.storage;
    
    const bnEl = document.getElementById('breakdownNetwork');
    if (bnEl) bnEl.innerText = data.network;
    
    const btEl = document.getElementById('breakdownTotal');
    if (btEl) btEl.innerText = data.total;

    // Budget indicator width
    const pct = parseFloat(data.budgetPct);
    const barEl = document.getElementById('budgetBar');
    if (barEl) barEl.style.width = pct + '%';

    // Sandbox Itemized Costs table
    const tbody = document.getElementById('billingSandboxTable');
    if (tbody) {
        tbody.innerHTML = Object.keys(data.sandboxes).map(key => {
            const item = data.sandboxes[key];
            const runtime = state.sandboxes[key] ? state.sandboxes[key].runtime : 'python:3.12';
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

    // Simple animation check
    const chart = document.getElementById('spendChartContainer');
    if (chart) {
        chart.style.opacity = '0.5';
        setTimeout(() => { chart.style.opacity = '1'; }, 150);
    }
}

async function downloadInvoice() {
    await showCustomAlert("Invoice Compile Result", "Preparing PDF invoice compile request...\n\nThinkDome billing cycle summary compiled. Mock Invoice #TD-2026-0612.pdf downloaded successfully!");
    addAuditEvent("Invoice #TD-2026-0612.pdf downloaded");
}

/* =================== API KEYS CONTROLLER =================== */
function maskToken(token) {
    if (!token) return '';
    if (token.length <= 12) return '••••••••';
    const prefix = token.substring(0, 8);
    const suffix = token.substring(token.length - 4);
    return `${prefix}••••••••${suffix}`;
}

function renderApiKeys() {
    const tbody = document.getElementById('apiKeysTableBody');
    if (!tbody) return;
    tbody.innerHTML = state.apiKeys.map((k, index) => `
        <tr>
          <td style="font-weight:600;">${k.name}</td>
          <td class="mono" style="font-size: 13px;">${maskToken(k.token)}</td>
          <td><span class="action-tag" style="background:var(--accent-subtle);color:var(--accent);">${k.type} Token</span></td>
          <td><span class="status-tag ${k.status === 'ACTIVE' ? 'success' : 'error'}">${k.status}</span></td>
          <td>
            ${k.status === 'ACTIVE' ? `<button class="btn btn-ghost btn-sm" style="color:var(--danger); border-color:var(--danger-subtle);" onclick="revokeKey(${index})">Revoke</button>` : `<span class="faint" style="font-size:12px;color:var(--fg-subtle)">Revoked</span>`}
          </td>
        </tr>
      `).join('');
}

async function generateNewKey(e) {
    e.preventDefault();
    const nameInput = document.getElementById('keyName');
    const typeInput = document.getElementById('keyType');
    if (!nameInput || !typeInput) return;

    const name = nameInput.value.trim();
    const type = typeInput.value;
    if (!name) return;

    // Generate a long secure random API token (like gsk_...)
    const characters = 'abcdef0123456789';
    let tokenBody = '';
    for (let i = 0; i < 32; i++) {
        tokenBody += characters.charAt(Math.floor(Math.random() * characters.length));
    }
    const prefix = type === 'ADMIN' ? 'admin_' : type === 'READONLY' ? 'read_' : 'gsk_';
    const token = prefix + tokenBody;

    state.apiKeys.unshift({
        name: name,
        token: token,
        type: type,
        status: 'ACTIVE'
    });

    nameInput.value = '';
    
    // Copy the token to the clipboard immediately
    try {
        await navigator.clipboard.writeText(token);
    } catch (err) {
        console.error('Failed to copy API key: ', err);
    }

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Created new secure API token credentials for user profile access: ${name}`);
    }
    addAuditEvent(`Generated API Key: ${name}`);
    
    renderAllViews();

    // Show the modal alert containing the raw token, copy button, and security warning
    await showCustomAlert("Secure API Key Generated", `
      <span style="display:block; margin-bottom:12px; font-size:13.5px; color:var(--fg-muted);">Here is your new API key. We have copied it to your clipboard automatically.</span>
      <div style="background:var(--surface-raised); border:1px solid var(--border); border-radius:var(--radius-md); padding:14px; font-family:var(--font-mono); color:var(--accent); font-weight:600; text-align:center; word-break:break-all; font-size:13.5px; margin-bottom:12px; user-select:all;">
        ${token}
      </div>
      <button class="btn btn-ghost" id="btn-copy-modal-key" style="width:100%; margin-bottom:12px; border-color:var(--accent-subtle); color:var(--accent); font-size:12.5px;" onclick="navigator.clipboard.writeText('${token}').then(() => { const el = document.getElementById('btn-copy-modal-key'); el.innerHTML = '✓ Copied!'; setTimeout(() => el.innerHTML = 'Copy Key to Clipboard', 2000); })">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px; height:14px; margin-right:6px; display:inline-block; vertical-align:middle;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
        Copy Key to Clipboard
      </button>
      <span style="color:var(--danger); font-size:12px; font-weight:600; display:block;">⚠️ Save this key securely. For security reasons, you will not be able to view it again.</span>
    `);
}

async function revokeKey(index) {
    const ok = await showCustomConfirm("Revoke API Key Credentials", `Are you sure you want to permanently revoke credentials for "${state.apiKeys[index].name}"?`);
    if (ok) {
        state.apiKeys[index].status = 'REVOKED';
        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Revoked token authentication key: ${state.apiKeys[index].name}`);
        }
        addAuditEvent(`Revoked API Key: ${state.apiKeys[index].name}`);
        renderAllViews();
    }
}
