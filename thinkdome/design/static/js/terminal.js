// static/js/terminal.js

/* =================== CONSOLE & LAYOUT SWITCHES =================== */
function switchConsoleMode(mode) {
    state.activeConsoleTab = mode;

    const isIde = mode === 'ide';
    const ideBtn = document.getElementById('btn-toggle-ide');
    const orchBtn = document.getElementById('btn-toggle-orchestrator');
    if (ideBtn) ideBtn.classList.toggle('active', isIde);
    if (orchBtn) orchBtn.classList.toggle('active', !isIde);

    const idePanel = document.getElementById('ideConsolePanel');
    const orchPanel = document.getElementById('orchestratorConsolePanel');
    if (idePanel) idePanel.classList.toggle('hidden', !isIde);
    if (orchPanel) orchPanel.classList.toggle('hidden', isIde);

    if (isIde) {
        if (typeof syncGutter === 'function') syncGutter();
        focusTerminalInput();
    }
}

function idePaneMode(pane, btn) {
    state.activeIdePane = pane;

    const parent = btn.parentElement;
    parent.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const editorPane = document.getElementById('editorPane');
    const toolusePane = document.getElementById('toolusePane');
    if (editorPane) editorPane.classList.toggle('hidden', pane !== 'editor');
    if (toolusePane) toolusePane.classList.toggle('hidden', pane !== 'tooluse');

    if (pane === 'editor') {
        if (typeof syncGutter === 'function') syncGutter();
    }
}

function switchRightTab(tab, btn) {
    state.activeRightTab = tab;

    const parent = btn.parentElement;
    parent.querySelectorAll('.rtab').forEach(r => r.classList.remove('active'));
    btn.classList.add('active');

    const rl = document.getElementById('rp-logs');
    const rr = document.getElementById('rp-result');
    const rm = document.getElementById('rp-metrics');
    if (rl) rl.classList.toggle('active', tab === 'logs');
    if (rr) rr.classList.toggle('active', tab === 'result');
    if (rm) rm.classList.toggle('active', tab === 'metrics');
}

/* =================== LOG BUFFERS =================== */
function addLogLine(level, message) {
    const timeStr = new Date().toTimeString().split(' ')[0] + '.' + String(new Date().getMilliseconds()).padStart(3, '0');
    state.logs.push({ ts: timeStr, lv: level, msg: message });

    renderLogsPane();
}

function renderLogsPane() {
    const container = document.getElementById('logOutputContainer');
    if (!container) return;
    container.innerHTML = state.logs.map(log => `
        <div class="log-line">
          <span class="ts">${log.ts}</span>
          <span class="lv lv-${log.lv}">${log.lv}</span>
          <span class="msg">${log.msg}</span>
        </div>
      `).join('');

    // Update logs count badge
    const badge = document.getElementById('logCountBadge');
    if (badge) badge.innerText = state.logs.length;

    // Auto Scroll to bottom
    const panel = document.getElementById('rp-logs');
    if (panel) panel.scrollTop = panel.scrollHeight;
}

function clearLogs() {
    state.logs = [];
    addLogLine('SYS', 'Logs cleared by admin.');
    renderLogsPane();
}

/* =================== INTERACTIVE SIMULATED SHELL =================== */
function focusTerminalInput() {
    const line = document.getElementById('terminalCommandLine');
    if (line) line.focus();
}

function handleTerminalCommand(e) {
    if (e.key === 'Enter') {
        const input = document.getElementById('terminalCommandLine');
        if (!input) return;
        const cmd = input.value.trim();
        if (!cmd) return;

        input.value = '';
        executeTerminalCmd(cmd);
    }
}

function executeTerminalCmd(cmd) {
    const terminal = document.getElementById('terminalConsoleBody');
    if (!terminal) return;
    const activeLine = terminal.lastElementChild; // input container line

    // Append command prompt line history before output
    const historyBlock = document.createElement('div');
    historyBlock.className = 'term-prompt-block';
    
    const hostEl = document.getElementById('terminalPromptHost');
    const pathEl = document.getElementById('terminalPromptPath');
    const host = hostEl ? hostEl.textContent : 'sbx_a91f';
    const path = pathEl ? pathEl.textContent : '~/workspace/demo';

    historyBlock.innerHTML = `
      <div class="term-prompt-line1">
        <span class="box-branch">┌──</span>
        <span class="prompt-paren">(</span>
        <span class="prompt-user">root</span>
        <span class="prompt-at">㉿</span>
        <span class="prompt-host">${host}</span>
        <span class="prompt-paren">)</span>
        <span class="prompt-dash">-</span>
        <span class="prompt-bracket">[</span>
        <span class="prompt-path">${path}</span>
        <span class="prompt-bracket">]</span>
      </div>
      <div class="term-prompt-line2">
        <span class="box-tail">└─</span>
        <span class="prompt-dollar">$</span>
        <span class="cmd-text">${cmd}</span>
      </div>
    `;
    terminal.insertBefore(historyBlock, activeLine);

    // Analyze command keywords
    if (cmd === 'clear') {
        // Clear all except the last input line
        while (terminal.childElementCount > 1) {
            terminal.removeChild(terminal.firstElementChild);
        }
        return;
    }

    const outLine = document.createElement('div');
    outLine.className = 'term-line';

    if (cmd.startsWith('pip install ')) {
        const pkg = cmd.replace('pip install ', '').trim();
        outLine.innerHTML = `<span class="cmd-out">Collecting ${pkg}...\n  Downloading ${pkg}-2.4.1-py3-none-any.whl (142 kB)\n  Installing collected packages: ${pkg}\nSuccessfully installed ${pkg}-2.4.1</span>`;
        addLogLine('SYS', `Pip runtime installed dependencies package: ${pkg}`);
        if (typeof addAuditEvent === 'function') {
            addAuditEvent(`Pip installed package ${pkg}`);
        }
    }
    else if (cmd.startsWith('python ')) {
        const filename = cmd.replace('python ', '').trim();
        const proj = state.projects[state.activeProject];

        if (proj && proj.files[filename]) {
            const content = proj.files[filename].content;
            let outputText = `Running ${filename}...\n`;
            if (content.includes('print')) {
                outputText += 'Sandbox runtime output: Standard validation stream output code 0\n';
            } else {
                outputText += 'Process executed with no output returned.\n';
            }
            outLine.innerHTML = `<span class="cmd-out" style="color:var(--success)">${outputText}</span>`;
            addLogLine('SYS', `CLI compiler command triggered python script: ${filename}`);
        } else {
            outLine.innerHTML = `<span class="cmd-out" style="color:var(--danger)">python: can't open file '${filename}': [Errno 2] No such file or directory</span>`;
        }
    }
    else if (cmd === 'ls' || cmd === 'dir') {
        const proj = state.projects[state.activeProject];
        if (proj) {
            const files = Object.keys(proj.files).join('    ');
            outLine.innerHTML = `<span class="cmd-out" style="color:#a5b4fc; font-weight:700;">${files}</span>`;
        }
    }
    else if (cmd === 'help') {
        outLine.innerHTML = `<span class="cmd-out">Available sandbox terminal commands:\n  ls, dir                       List workspace files\n  pip install &lt;package&gt;         Install third party packages\n  python &lt;script.py&gt;            Compile and run script\n  cat &lt;file&gt;                    Show file contents\n  clear                         Clear terminal prompt</span>`;
    }
    else if (cmd.startsWith('cat ')) {
        const filename = cmd.replace('cat ', '').trim();
        const proj = state.projects[state.activeProject];
        if (proj && proj.files[filename]) {
            outLine.innerHTML = `<span class="cmd-out" style="color:#e2e8f0">${proj.files[filename].content}</span>`;
        } else {
            outLine.innerHTML = `<span class="cmd-out" style="color:var(--danger)">cat: ${filename}: No such file or directory</span>`;
        }
    }
    else {
        outLine.innerHTML = `<span class="cmd-out" style="color:var(--fg-subtle)">bash: command not found: ${cmd}. Type 'help' for support.</span>`;
    }

    terminal.insertBefore(outLine, activeLine);
    terminal.scrollTop = terminal.scrollHeight;
}

/* =================== ORIGINAL ORCHESTRATION CONSOLE PAYLOADS =================== */
function loadPresetsOrch(key) {
    const payload = presetsOrch[key];
    const raw = document.getElementById('orchRawJsonInput');
    if (payload && raw) {
        raw.value = JSON.stringify(payload, null, 2);
    }
}

async function executeOrchConsolePayload() {
    const rawInput = document.getElementById('orchRawJsonInput');
    if (!rawInput) return;
    const raw = rawInput.value.trim();
    const output = document.getElementById('orchResultOutputPanel');
    if (!raw) {
        await showCustomAlert("Console Error", "Payload structure empty.");
        return;
    }

    try {
        const parsed = JSON.parse(raw);
        if (output) {
            output.innerHTML = `
              <div style="font-size:10px;font-weight:700;color:var(--success);margin-bottom:6px;">HTTP/1.1 200 OK</div>
              <pre class="mono" style="font-size:12.5px;color:var(--fg-muted);white-space:pre-wrap;">${JSON.stringify({
                tool_use_id: parsed.id || 'toolu_99x',
                status: 'success',
                result: `Processed successfully. Subprocess exited.`,
                details: {
                    timestamp: new Date().toISOString(),
                    target_sandbox: parsed.input ? parsed.input.sandbox : 'sbx_a91f'
                }
            }, null, 2)}</pre>
            `;
        }
        addLogLine('SYS', `Engine API call completed: ${parsed.name || 'custom'}`);
    } catch (err) {
        if (output) {
            output.innerHTML = `<pre class="mono" style="color:var(--danger);font-size:12.5px;">Invalid JSON: ${err.message}</pre>`;
        }
    }
}

/* =================== TERMINAL SYNC & DRAWER PARAMETERS =================== */
function updateTerminalLabel() {
    const label = document.getElementById('terminalSbxLabel');
    const promptHost = document.getElementById('terminalPromptHost');
    const sb = state.sandboxes[state.activeSbx];
    const sbId = sb ? sb.id : state.activeSbx;
    
    if (label) {
        label.textContent = sbId;
    }
    if (promptHost) {
        promptHost.textContent = sbId;
    }
}

function updateTerminalPromptPath() {
    const promptPath = document.getElementById('terminalPromptPath');
    if (promptPath) {
        promptPath.textContent = `~/workspace/${state.activeProject}`;
    }
}

function triggerEditorLayout() {
    if (typeof editorInstance !== 'undefined' && editorInstance) {
        editorInstance.layout();
        setTimeout(() => {
            if (typeof editorInstance !== 'undefined' && editorInstance) editorInstance.layout();
        }, 220);
    }
}

function toggleTerminalDrawer() {
    const drawer = document.querySelector('.terminal-drawer');
    const toggleBtn = document.getElementById('btn-toggle-terminal');
    if (!drawer) return;

    if (drawer.classList.contains('closed')) {
        drawer.classList.remove('closed');
        if (toggleBtn) toggleBtn.classList.add('active');
        focusTerminalInput();
    } else {
        drawer.classList.add('closed');
        if (toggleBtn) toggleBtn.classList.remove('active');
    }
    triggerEditorLayout();
}

function closeTerminal() {
    const drawer = document.querySelector('.terminal-drawer');
    const toggleBtn = document.getElementById('btn-toggle-terminal');
    if (drawer) {
        drawer.classList.add('closed');
        if (toggleBtn) toggleBtn.classList.remove('active');
        triggerEditorLayout();
    }
}

function minimizeTerminal() {
    const drawer = document.querySelector('.terminal-drawer');
    if (drawer) {
        drawer.classList.remove('maximized');
        drawer.classList.toggle('minimized');
        triggerEditorLayout();
    }
}

function maximizeTerminal() {
    const drawer = document.querySelector('.terminal-drawer');
    if (drawer) {
        drawer.classList.remove('minimized');
        drawer.classList.toggle('maximized');
        triggerEditorLayout();
    }
}
