// static/js/state.js

/* =================== INITIAL STATE & DATA =================== */
const state = {
    theme: 'dark', // default theme state, will sync on load
    activePage: 'dashboard',
    activeSbx: 'prod-runner-01',
    activeConsoleTab: 'ide', // ide or orchestrator
    activeIdePane: 'editor', // editor or tooluse
    activeRightTab: 'logs', // logs, result, metrics

    // Sandbox Nodes mock data
    sandboxes: {
        'prod-runner-01': { id: 'sbx_a91f', name: 'prod-runner-01', runtime: 'python:3.12', cores: 2, ram: '4 GB', region: 'us-east-1', uptime: '102h', spend: 8.57, rate: 0.08, ramUsage: 71, status: 'running', executions: '18.40', subtotal: 26.97 },
        'agent-worker-02': { id: 'sbx_7c20', name: 'agent-worker-02', runtime: 'node:22', cores: 4, ram: '8 GB', region: 'eu-west-1', uptime: '35h', spend: 5.67, rate: 0.16, ramUsage: 44, status: 'running', executions: '9.10', subtotal: 14.77 },
        'batch-eval-03': { id: 'sbx_3de8', name: 'batch-eval-03', runtime: 'python:3.12', cores: 8, ram: '16 GB', region: 'us-west-2', uptime: '7h', spend: 2.27, rate: 0.32, ramUsage: 79, status: 'running', executions: '12.20', subtotal: 14.47 },
        'staging-test-04': { id: 'sbx_0b5a', name: 'staging-test-04', runtime: 'node:20', cores: 1, ram: '2 GB', region: 'us-east-1', uptime: '0h', spend: 0.00, rate: 0.04, ramUsage: 0, status: 'stopped', executions: '0.00', subtotal: 0.00 }
    },

    // Workspace Projects mock data
    projects: {
        demo: {
            name: 'Demo Sandbox Agent',
            files: {
                'main.py': { name: 'main.py', path: 'main.py', content: 'print("Running sandbox init agent...")\nimport sys\nprint("Sandbox runtime python environment:", sys.version)\n', type: 'file' },
                'agent.py': { name: 'agent.py', path: 'agent.py', content: '# Intelligent mock assistant logic\ndef solve_problem(task):\n    print(f"Deciphering task instructions: {task}")\n    return "Agent completed successfully."\n\nprint(solve_problem("Analyze storage leaks"))\n', type: 'file' },
                'requirements.txt': { name: 'requirements.txt', path: 'requirements.txt', content: 'numpy>=1.22.0\nmatplotlib>=3.5.0\nopenai>=1.2.0\n', type: 'file' }
            },
            activeFile: 'main.py',
            openTabs: ['main.py']
        },
        data: {
            name: 'Data Science & Plotting',
            files: {
                'visualize.py': { name: 'visualize.py', path: 'visualize.py', content: 'import matplotlib.pyplot as plt\nimport numpy as np\n\nprint("Generating custom evaluation metrics...")\nx = np.linspace(0, 10, 100)\ny = np.sin(x)\n\nplt.figure(figsize=(6, 4))\nplt.plot(x, y, label="Sinewave Signal", color="indigo")\nplt.title("ThinkDome Live Visualizer Output")\nplt.legend()\nplt.show()\n', type: 'file' },
                'dataset.json': { name: 'dataset.json', path: 'dataset.json', content: '{\n  "runs": [1, 2, 3],\n  "accuracy": [0.89, 0.94, 0.97]\n}\n', type: 'file' }
            },
            activeFile: 'visualize.py',
            openTabs: ['visualize.py']
        },
        ml: {
            name: 'LLM Evaluation Worker',
            files: {
                'eval_pipeline.py': { name: 'eval_pipeline.py', path: 'eval_pipeline.py', content: 'import os\nprint("Connecting to secure proxy endpoints...")\n# Load local configurations\nprint("Evaluating pipeline accuracy: 96.2%")\n', type: 'file' }
            },
            activeFile: 'eval_pipeline.py',
            openTabs: ['eval_pipeline.py']
        }
    },
    activeProject: 'demo',

    // Logs collection
    logs: [
        { ts: '18:55:41.946', lv: 'SYS', msg: 'ThinkDome orchestrator ready · region us-east-1' },
        { ts: '18:55:41.949', lv: 'INFO', msg: 'Waiting for execution context instruction...' }
    ],

    // API Keys
    apiKeys: [
        { name: 'production-key', token: 'gsk_fab81c3a0df4521ed2', type: 'LLM', status: 'ACTIVE' },
        { name: 'ci-pipeline', token: 'gsk_df5a02e49c719852b2', type: 'LLM', status: 'ACTIVE' }
    ],

    // Infrastructure Events
    auditEvents: [
        { ts: '18:32:00', actor: 'admin', detail: 'API Key production-key used for code execution context' },
        { ts: '18:28:30', actor: 'admin', detail: 'Saved changes into file main.py via console interface' },
        { ts: '18:22:10', actor: 'system', detail: 'Execution blocked on staging-test-04: Node stopped state' },
        { ts: '18:05:51', actor: 'admin', detail: 'API Key ci-pipeline generated successfully' },
        { ts: '17:58:22', actor: 'admin', detail: 'Admin session started from IP 127.0.0.1' }
    ]
};

// Preset configurations for original LLM Orchestration Console
const presetsOrch = {
    run_code: { type: 'tool_use', id: 'toolu_01', name: 'run_code', input: { sandbox: 'sbx_a91f', language: 'python', code: 'print("Hello World from ThinkDome")' } },
    read_file: { type: 'tool_use', id: 'toolu_02', name: 'read_file', input: { sandbox: 'sbx_a91f', path: '/app/main.py' } },
    write_file: { type: 'tool_use', id: 'toolu_03', name: 'write_file', input: { sandbox: 'sbx_a91f', path: '/app/note.txt', content: 'Successfully written from orchestrator.' } },
    list_dir: { type: 'tool_use', id: 'toolu_04', name: 'list_dir', input: { sandbox: 'sbx_a91f', path: '/app' } },
    web_search: { type: 'tool_use', id: 'toolu_05', name: 'web_search', input: { sandbox: 'sbx_a91f', query: 'thinkdome orchestrator documentation' } }
};

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
