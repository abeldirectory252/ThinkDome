// static/js/state.js

/* =================== INITIAL STATE & DATA =================== */
const state = {
    theme: 'dark', // default theme state, will sync on load
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
        read_file: { type: 'tool_use', id: 'toolu_02', name: 'read_file', input: { sandbox: sbxId, path: '/app/main.py' } },
        write_file: { type: 'tool_use', id: 'toolu_03', name: 'write_file', input: { sandbox: sbxId, path: '/app/note.txt', content: 'Successfully written from orchestrator.' } },
        list_dir: { type: 'tool_use', id: 'toolu_04', name: 'list_dir', input: { sandbox: sbxId, path: '/app' } },
        web_search: { type: 'tool_use', id: 'toolu_05', name: 'web_search', input: { sandbox: sbxId, query: 'thinkdome orchestrator documentation' } }
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
