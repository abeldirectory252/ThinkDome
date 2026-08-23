// static/js/state.js

/* =================== INITIAL STATE & DATA =================== */
const state = {
    theme: 'light', // stable original theme; changed only by explicit user toggle
    activePage: 'dashboard',
    activeSbx: '',
    activeConsoleTab: 'ide', // ide or orchestrator
    activeIdePane: 'editor', // editor or tooluse
    activeRightTab: 'logs', // logs, result, metrics

    // Sandbox Nodes empty initial state
    sandboxes: {},

    // Workspace Projects empty initial state
    projects: {
        demo: {
            name: 'Demo Sandbox Agent',
            files: {},
            activeFile: null,
            openTabs: []
        }
    },
    activeProject: 'demo',
    terminalCwd: '.',

    // Logs collection
    logs: [],

    // API Keys
    apiKeys: [],

    // Infrastructure Events
    auditEvents: []
};

window.state = state;

// Preset configurations for original LLM Orchestration Console
// Sandbox IDs are dynamically resolved from state.activeSbx at invocation time
function getPresetsOrch() {
    const sbxId = (state.activeSbx && state.sandboxes[state.activeSbx]) ? state.sandboxes[state.activeSbx].id : '';
    return {
        run_code: { type: 'tool_use', id: 'toolu_01', name: 'run_code', input: { sandbox: sbxId, language: 'python', code: 'print("Hello World from ThinkDome")' } },
        read_file: { type: 'tool_use', id: 'toolu_02', name: 'read_file', input: { sandbox: sbxId, path: '/workspace/main.py' } },
        write_file: { type: 'tool_use', id: 'toolu_03', name: 'write_file', input: { sandbox: sbxId, path: '/workspace/note.txt', content: 'Successfully written from orchestrator.' } },
        list_dir: { type: 'tool_use', id: 'toolu_04', name: 'list_dir', input: { sandbox: sbxId, path: '/app' } },
        web_search: { type: 'tool_use', id: 'toolu_05', name: 'web_search', input: { sandbox: sbxId, query: 'thinkdome orchestrator documentation' } },
        host_html: { type: 'tool_use', id: 'toolu_06', name: 'host_html', input: { sandbox: sbxId, html: '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>ThinkDome Live Preview</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet"><style>:root{--bg:#f8fafc;--card-bg:#ffffff;--border:#e2e8f0;--text:#0f172a;--text-muted:#64748b;--accent:#0284c7;--accent-emerald:#059669;}*{box-sizing:border-box;margin:0;padding:0;}body{font-family:Inter,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 20px;position:relative;overflow-x:hidden;}body::before{content:"";position:absolute;width:500px;height:500px;background:radial-gradient(circle,rgba(2,132,199,0.08) 0%,rgba(99,102,241,0.03) 50%,transparent 70%);top:-100px;left:-100px;z-index:0;}body::after{content:"";position:absolute;width:600px;height:600px;background:radial-gradient(circle,rgba(124,58,237,0.06) 0%,transparent 70%);bottom:-150px;right:-150px;z-index:0;}.container{position:relative;z-index:1;width:100%;max-width:680px;}.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;}.brand{display:flex;align-items:center;gap:10px;font-family:Outfit,sans-serif;font-size:20px;font-weight:800;color:var(--accent);}.badge{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:30px;font-size:12px;font-weight:600;color:var(--accent-emerald);}.pulse{width:8px;height:8px;background:var(--accent-emerald);border-radius:50%;box-shadow:0 0 8px rgba(5,150,105,0.4);animation:p 2s infinite;}@keyframes p{0%{transform:scale(0.95);box-shadow:0 0 0 0 rgba(5,150,105,0.4);}70%{transform:scale(1);box-shadow:0 0 0 8px rgba(5,150,105,0);}100%{transform:scale(0.95);box-shadow:0 0 0 0 rgba(5,150,105,0);}}.card{background:var(--card-bg);border:1px solid var(--border);border-radius:20px;padding:36px;box-shadow:0 20px 40px -15px rgba(0,0,0,0.07);}h1{font-family:Outfit,sans-serif;font-size:30px;font-weight:700;margin-bottom:12px;color:#0f172a;}.sub{color:var(--text-muted);font-size:15px;line-height:1.6;margin-bottom:28px;}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:28px;}.stat{background:#f8fafc;border:1px solid var(--border);border-radius:14px;padding:16px;}.lbl{font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;margin-bottom:6px;}.val{font-family:Outfit,sans-serif;font-size:20px;font-weight:700;color:var(--accent);}.code{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:16px;font-family:"Fira Code",monospace;font-size:13px;color:#38bdf8;}</style></head><body><div class="container"><div class="header"><div class="brand"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21 16-9 5-9-5V8l9-5 9 5v8Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg><span>ThinkDome Gateway</span></div><div class="badge"><div class="pulse"></div><span>LIVE PREVIEW ONLINE</span></div></div><div class="card"><h1>Autonomous Web Preview</h1><p class="sub">Generated dynamically by LLM Orchestration and isolated inside a secure ephemeral container gateway.</p><div class="grid"><div class="stat"><div class="lbl">Web Engine</div><div class="val">HTTP / Apache</div></div><div class="stat"><div class="lbl">Isolation</div><div class="val" style="color:#059669;">Sandbox High</div></div><div class="stat"><div class="lbl">Auto TTL</div><div class="val" style="color:#7c3aed;">300 Seconds</div></div></div><div class="code">$ status: 200 OK &bull; memory: isolated &bull; proxy: active</div></div></div></body></html>', filename: 'report.html', site_name: 'llm_reports', port: 8080, ttl_sec: 300 } }
    };
}

/* =================== CUSTOM MODAL POPUPS =================== */
function showCustomAlert(title, message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal-card" style="max-width: 400px;">
            <div class="modal-header">
              <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent);">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="16" x2="12" y2="12"></line>
                  <line x1="12" y1="8" x2="12.01" y2="8"></line>
                </svg>
                ${title}
              </h3>
              <button class="close-modal-btn">&times;</button>
            </div>
            <div class="modal-body">
              <p style="color:var(--fg-muted); font-size:14px; line-height:1.5;">${message}</p>
            </div>
            <div class="modal-footer">
              <button class="btn btn-primary btn-ok">OK</button>
            </div>
          </div>
        `;
        document.body.appendChild(overlay);
        
        // Force reflow and add active class
        setTimeout(() => overlay.classList.add('active'), 10);
        
        const close = () => {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 250);
            resolve();
        };

        overlay.querySelector('.close-modal-btn').onclick = close;
        overlay.querySelector('.btn-ok').onclick = close;
    });
}

function showCustomConfirm(title, message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal-card" style="max-width: 400px;">
            <div class="modal-header">
              <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--danger);">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                  <line x1="12" y1="9" x2="12" y2="13"></line>
                  <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                Confirm Action
              </h3>
              <button class="close-modal-btn">&times;</button>
            </div>
            <div class="modal-body">
              <p style="color:var(--fg-muted); font-size:14px; line-height:1.5;">${message}</p>
            </div>
            <div class="modal-footer">
              <button class="btn btn-ghost btn-cancel">Cancel</button>
              <button class="btn btn-primary btn-confirm" style="background:var(--danger); color:#fff; border-color:var(--danger);">Confirm</button>
            </div>
          </div>
        `;
        document.body.appendChild(overlay);
        
        setTimeout(() => overlay.classList.add('active'), 10);
        
        const cleanup = (val) => {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 250);
            resolve(val);
        };

        overlay.querySelector('.close-modal-btn').onclick = () => cleanup(false);
        overlay.querySelector('.btn-cancel').onclick = () => cleanup(false);
        overlay.querySelector('.btn-confirm').onclick = () => cleanup(true);
    });
}

function showCustomPrompt(title, message, defaultValue = "", multiline = false) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        
        const inputHTML = multiline 
            ? `<textarea id="customPromptInput" style="flex: 1; border:none; outline:none; background:transparent; color:var(--fg); font-family:var(--font-mono); resize:vertical; padding:12px 14px; line-height:1.5; font-size:13px; min-height:80px;">${defaultValue}</textarea>`
            : `<input type="text" id="customPromptInput" value="${defaultValue}" style="color:var(--fg);" autocomplete="off" />`;

        overlay.innerHTML = `
          <div class="modal-card" style="max-width: 400px;">
            <div class="modal-header">
              <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent);">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                  <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
                ${title}
              </h3>
              <button class="close-modal-btn">&times;</button>
            </div>
            <div class="modal-body">
              <label style="color:var(--fg-muted); font-size:13px; font-weight:600; display:block; margin-bottom:8px;">${message}</label>
              <div class="input-shell">
                ${inputHTML}
              </div>
            </div>
            <div class="modal-footer" style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:11px; color:var(--fg-subtle); font-style:italic; opacity:0.7;">${multiline ? 'Ctrl+Enter to submit' : 'Enter to submit'}</span>
              <div style="display:flex; gap:12px;">
                <button class="btn btn-ghost btn-cancel">Cancel</button>
                <button class="btn btn-primary btn-submit">Submit</button>
              </div>
            </div>
          </div>
        `;
        document.body.appendChild(overlay);
        
        const input = overlay.querySelector('#customPromptInput');
        
        setTimeout(() => {
            overlay.classList.add('active');
            input.focus();
            if (typeof input.select === 'function') {
                input.select();
            }
        }, 10);
        
        const cleanup = (val) => {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 250);
            resolve(val);
        };

        overlay.querySelector('.close-modal-btn').onclick = () => cleanup(null);
        overlay.querySelector('.btn-cancel').onclick = () => cleanup(null);
        overlay.querySelector('.btn-submit').onclick = () => cleanup(input.value);
        
        input.onkeydown = (e) => {
            if (e.key === 'Enter') {
                if (multiline) {
                    if (e.ctrlKey) {
                        e.preventDefault();
                        cleanup(input.value);
                    }
                } else {
                    e.preventDefault();
                    cleanup(input.value);
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                cleanup(null);
            }
        };
    });
}
