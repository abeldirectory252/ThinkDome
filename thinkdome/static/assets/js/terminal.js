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
    const mcpPane = document.getElementById('mcpPane');
    if (editorPane) editorPane.classList.toggle('hidden', pane !== 'editor');
    if (toolusePane) toolusePane.classList.toggle('hidden', pane !== 'tooluse');
    if (mcpPane) mcpPane.classList.toggle('hidden', pane !== 'mcp');

    if (pane === 'mcp') {
        renderIdeMcpTools();
    }

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
let _terminalBusy = false;
let _activeAbortController = null;

function focusTerminalInput() {
    const line = document.getElementById('terminalCommandLine');
    if (line && !_terminalBusy) line.focus();
}

function handleTerminalCommand(e) {
    const input = document.getElementById('terminalCommandLine');
    if (!input) return;

    if (!state.terminalHistory) {
        state.terminalHistory = [];
        state.terminalHistoryIdx = -1;
    }

    if (e.key === 'Enter') {
        if (_terminalBusy) return;
        const cmd = input.value.trim();
        if (!cmd) return;

        if (state.terminalHistory.length === 0 || state.terminalHistory[state.terminalHistory.length - 1] !== cmd) {
            state.terminalHistory.push(cmd);
        }
        state.terminalHistoryIdx = -1;

        input.value = '';
        executeTerminalCmd(cmd);
    } else if (e.key === 'ArrowUp') {
        if (_terminalBusy) return;
        e.preventDefault();
        if (state.terminalHistory.length > 0) {
            if (state.terminalHistoryIdx === -1) {
                state.terminalHistoryIdx = state.terminalHistory.length - 1;
            } else if (state.terminalHistoryIdx > 0) {
                state.terminalHistoryIdx--;
            }
            input.value = state.terminalHistory[state.terminalHistoryIdx];
            setTimeout(() => { input.selectionStart = input.selectionEnd = input.value.length; }, 0);
        }
    } else if (e.key === 'ArrowDown') {
        if (_terminalBusy) return;
        e.preventDefault();
        if (state.terminalHistoryIdx !== -1) {
            if (state.terminalHistoryIdx < state.terminalHistory.length - 1) {
                state.terminalHistoryIdx++;
                input.value = state.terminalHistory[state.terminalHistoryIdx];
            } else {
                state.terminalHistoryIdx = -1;
                input.value = '';
            }
            setTimeout(() => { input.selectionStart = input.selectionEnd = input.value.length; }, 0);
        }
    } else if (e.ctrlKey && e.key.toLowerCase() === 'c') {
        if (!_terminalBusy) {
            e.preventDefault();
            const cmd = input.value;
            input.value = '';
            
            const terminal = document.getElementById('terminalConsoleBody');
            if (terminal) {
                const activeLine = terminal.lastElementChild;
                const historyBlock = document.createElement('div');
                historyBlock.className = 'term-prompt-block';
                
                const hostEl = document.getElementById('terminalPromptHost');
                const pathEl = document.getElementById('terminalPromptPath');
                const host = hostEl ? hostEl.textContent : 'sandbox';
                const path = pathEl ? pathEl.textContent : '~/workspace';
                
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
                    <span class="cmd-text">${cmd}^C</span>
                  </div>
                `;
                terminal.insertBefore(historyBlock, activeLine);
                terminal.scrollTop = terminal.scrollHeight;
            }
            state.terminalHistoryIdx = -1;
        }
    }
}

async function executeTerminalCmd(cmd) {
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

    if (cmd === 'clear') {
        while (terminal.childElementCount > 1) {
            terminal.removeChild(terminal.firstElementChild);
        }
        return;
    }

    // ── Lock terminal: hide prompt row, disable input ──
    _terminalBusy = true;
    const inputEl = document.getElementById('terminalCommandLine');
    if (inputEl) inputEl.disabled = true;
    if (activeLine) activeLine.style.display = 'none';

    const outLine = document.createElement('div');
    outLine.className = 'term-line';
    outLine.innerHTML = `<span class="cmd-out" style="color:var(--fg-subtle);"><span class="spinner" style="width: 10px; height: 10px; border-width: 1.5px; border-top-color: #fff; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> Running command...</span>`;
    terminal.insertBefore(outLine, activeLine);
    terminal.scrollTop = terminal.scrollHeight;

    const token = localStorage.getItem('thinkdome_token');
    const sb = state.sandboxes[state.activeSbx];
    const sandboxId = sb ? sb.id : '';

    try {
        if (!window.API || !token || !sandboxId) {
            throw new Error("Offline or Sandbox disconnected");
        }
        if (!sb || sb.status !== 'running') {
            throw new Error("Active sandbox node is not running. Start the node before running terminal commands.");
        }

        if (cmd.startsWith('pip install ')) {
            const pkg = cmd.replace('pip install ', '').trim();
            const code = `import subprocess, sys
try:
    cmd = [sys.executable, '-m', 'pip', 'install', '${pkg.replace(/'/g, "\\'")}']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
            await runCodeStreaming(code, token, sandboxId, outLine, `Pip runtime installed dependencies package: ${pkg}`);
        }
        else if (cmd.startsWith('pip uninstall ')) {
            const pkg = cmd.replace('pip uninstall ', '').trim();
            const code = `import subprocess, sys
try:
    cmd = [sys.executable, '-m', 'pip', 'uninstall', '-y', '${pkg.replace(/'/g, "\\'")}']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
            await runCodeStreaming(code, token, sandboxId, outLine, `Pip runtime uninstalled package: ${pkg}`);
        }
        else if (cmd === 'pip list' || cmd === 'pip freeze') {
            const code = `import subprocess, sys
try:
    cmd = [sys.executable, '-m', 'pip', '${cmd === 'pip freeze' ? 'freeze' : 'list'}']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd === 'python --version' || cmd === 'python -V' || cmd === 'python3 --version') {
            const { data, error } = await window.API.orchestrate({
                type: "tool_use",
                id: "toolu_term_pyver",
                name: "run_code",
                input: {
                    sandbox: sandboxId,
                    language: "python",
                    code: "import sys; print(f'Python {sys.version}')"
                }
            }, token, sandboxId);
            if (error) throw new Error(error);
            const parsed = _tryParseJSON(data.content || data);
            const out = parsed ? (parsed.stdout || "") : (data.content || "");
            outLine.innerHTML = `<span class="cmd-out" style="color:var(--success)">${_escapeHtml(out.trim())}</span>`;
        }
        else if (cmd.startsWith('python ')) {
            const filename = cmd.replace('python ', '').trim();
            if (filename.startsWith('-')) {
                const code = `import subprocess, sys
try:
    cmd = [sys.executable, '${filename.replace(/'/g, "\\'")}']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
                await runCodeStreaming(code, token, sandboxId, outLine);
            } else {
                const fileRes = await window.API.readFile(filename, token, sandboxId);
                if (fileRes.error) throw new Error(`python: can't open file '${filename}': No such file`);
                await runCodeStreaming(fileRes.data, token, sandboxId, outLine, `CLI compiler command triggered python script: ${filename}`);
            }
        }
        else if (cmd === 'ls' || cmd.startsWith('ls ') || cmd === 'dir' || cmd.startsWith('dir ')) {
            const isDirCmd = cmd.startsWith('dir');
            const cmdName = isDirCmd ? 'dir' : 'ls';
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import os, sys, datetime, stat

def emulate_ls(args):
    show_all = False
    long_format = ${isDirCmd ? 'True' : 'False'}
    reverse = False
    sort_time = False
    show_inode = False
    human_readable = False
    
    paths = []
    for arg in args:
        if arg.startswith('-'):
            flags = arg.lstrip('-')
            for f in flags:
                if f == 'a': show_all = True
                elif f == 'l': long_format = True
                elif f == 'r': reverse = True
                elif f == 't': sort_time = True
                elif f == 'i': show_inode = True
                elif f == 'h': human_readable = True
        else:
            paths.append(arg)
            
    target_dir = paths[0] if paths else '.'
    try:
        entries = os.listdir(target_dir)
    except Exception as e:
        print(f"${cmdName}: cannot access '{target_dir}': {e}", file=sys.stderr)
        sys.exit(1)
        
    if not show_all:
        entries = [e for e in entries if not e.startswith('.')]
        
    details = []
    for name in entries:
        full_path = os.path.join(target_dir, name)
        try:
            st = os.stat(full_path)
            mtime = st.st_mtime
            size = st.st_size
            inode = st.st_ino
            is_dir = stat.S_ISDIR(st.st_mode)
            mode_str = stat.filemode(st.st_mode)
        except Exception:
            mtime = 0
            size = 0
            inode = 0
            is_dir = False
            mode_str = '----------'
            
        details.append({
            'name': name,
            'is_dir': is_dir,
            'mode_str': mode_str,
            'size': size,
            'mtime': mtime,
            'inode': inode
        })
        
    if sort_time:
        details.sort(key=lambda x: x['mtime'], reverse=True)
    else:
        details.sort(key=lambda x: x['name'].lower())
        
    if reverse:
        details.reverse()
        
    def get_size_str(size):
        if not human_readable:
            return str(size)
        for unit in ['B', 'K', 'M', 'G']:
            if size < 1024:
                return f"{size:.1f}{unit}" if unit != 'B' else f"{size}{unit}"
            size /= 1024
        return f"{size:.1f}T"
        
    if long_format:
        total_blocks = sum(d['size'] for d in details) // 512
        print(f"total {total_blocks}")
        for d in details:
            inode_prefix = f"{d['inode']} " if show_inode else ""
            mtime_dt = datetime.datetime.fromtimestamp(d['mtime'])
            date_str = mtime_dt.strftime("%b %d %H:%M")
            size_str = get_size_str(d['size']).rjust(8)
            print(f"{inode_prefix}{d['mode_str']} 1 root root {size_str} {date_str} {d['name']}")
    else:
        output = []
        for d in details:
            inode_prefix = f"{d['inode']} " if show_inode else ""
            output.append(f"{inode_prefix}{d['name']}")
        print("    ".join(output))

emulate_ls(${JSON.stringify(args)})
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('mkdir ')) {
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import os, sys
args = ${JSON.stringify(args)}
paths = [a for a in args if not a.startswith('-')]
parents = '-p' in args or '--parents' in args
for path in paths:
    try:
        if parents:
            os.makedirs(path, exist_ok=True)
        else:
            os.mkdir(path)
    except Exception as e:
        print(f"mkdir: cannot create directory '{path}': {e}", file=sys.stderr)
        sys.exit(1)
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('rm ')) {
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import os, sys, shutil
args = ${JSON.stringify(args)}
paths = [a for a in args if not a.startswith('-')]
recursive = '-r' in args or '-R' in args or '--recursive' in args
force = '-f' in args or '--force' in args
for path in paths:
    try:
        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
            else:
                print(f"rm: cannot remove '{path}': Is a directory", file=sys.stderr)
                sys.exit(1)
        else:
            os.remove(path)
    except Exception as e:
        if not force:
            print(f"rm: cannot remove '{path}': {e}", file=sys.stderr)
            sys.exit(1)
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('touch ')) {
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import sys, pathlib
args = ${JSON.stringify(args)}
paths = [a for a in args if not a.startswith('-')]
for path in paths:
    try:
        pathlib.Path(path).touch()
    except Exception as e:
        print(f"touch: cannot touch '{path}': {e}", file=sys.stderr)
        sys.exit(1)
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('cp ')) {
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import sys, shutil, os
args = ${JSON.stringify(args)}
paths = [a for a in args if not a.startswith('-')]
recursive = '-r' in args or '-R' in args or '--recursive' in args
if len(paths) < 2:
    print("cp: missing file operand", file=sys.stderr)
    sys.exit(1)
dest = paths[-1]
sources = paths[:-1]
for src in sources:
    try:
        if os.path.isdir(src):
            if recursive:
                if os.path.isdir(dest):
                    shutil.copytree(src, os.path.join(dest, os.path.basename(src)))
                else:
                    shutil.copytree(src, dest)
            else:
                print(f"cp: -r not specified; omitting directory '{src}'", file=sys.stderr)
                sys.exit(1)
        else:
            if os.path.isdir(dest):
                shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
            else:
                shutil.copy2(src, dest)
    except Exception as e:
        print(f"cp: error: {e}", file=sys.stderr)
        sys.exit(1)
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('mv ')) {
            const parts = cmd.split(/\s+/);
            const args = parts.slice(1);
            const code = `
import sys, shutil, os
args = ${JSON.stringify(args)}
paths = [a for a in args if not a.startswith('-')]
if len(paths) < 2:
    print("mv: missing file operand", file=sys.stderr)
    sys.exit(1)
dest = paths[-1]
sources = paths[:-1]
for src in sources:
    try:
        if os.path.isdir(dest):
            shutil.move(src, os.path.join(dest, os.path.basename(src)))
        else:
            shutil.move(src, dest)
    except Exception as e:
        print(f"mv: error: {e}", file=sys.stderr)
        sys.exit(1)
`;
            await runCodeStreaming(code, token, sandboxId, outLine);
        }
        else if (cmd.startsWith('cat ')) {
            const filename = cmd.replace('cat ', '').trim();
            const { data, error } = await window.API.readFile(filename, token, sandboxId);
            if (error) throw new Error(error);

            outLine.innerHTML = `<span class="cmd-out" style="color:#e2e8f0; white-space: pre-wrap;">${_escapeHtml(data)}</span>`;
        }
        else if (cmd === 'pwd') {
            outLine.innerHTML = `<span class="cmd-out" style="color:#a5b4fc;">/workspace</span>`;
        }
        else if (cmd === 'whoami') {
            const user = localStorage.getItem('thinkdome_username') || 'root';
            outLine.innerHTML = `<span class="cmd-out" style="color:#a5b4fc;">${user}</span>`;
        }
        else if (cmd === 'help') {
            outLine.innerHTML = `<span class="cmd-out" style="white-space: pre-wrap;">Available sandbox terminal commands:
  ls, dir                       List workspace files
  cat &lt;file&gt;                    Show file contents
  python &lt;script.py&gt;            Compile and run script
  python --version              Show Python version
  pip install &lt;package&gt;         Install packages (persistent)
  pip uninstall &lt;package&gt;       Uninstall packages
  pip list / pip freeze          List installed packages
  ping &lt;host&gt;                   Ping a host
  pwd                           Show current directory
  whoami                        Show current user
  echo &lt;text&gt;                   Print text
  clear                         Clear terminal prompt

  Any other command will be executed as a shell command.</span>`;
        }
        else if (cmd.startsWith('ping ')) {
            const shellCode = `import subprocess, sys, platform
try:
    cmd = ${JSON.stringify(cmd)}
    parts = cmd.split()
    host = parts[-1]
    has_count = any(opt in cmd for opt in ['-c', '-n', '-t'])
    if not has_count:
        if platform.system().lower() == 'windows':
            cmd = f"ping -n 4 {host}"
        else:
            cmd = f"ping -c 4 {host}"
    
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
            await runCodeStreaming(shellCode, token, sandboxId, outLine, `Ping command executed: ${cmd}`);
        }
        else {
            // ── Generic shell command: run via subprocess in the sandbox ──
            const shellCode = `import subprocess, sys
try:
    cmd = ${JSON.stringify(cmd)}
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
    process.wait()
    sys.exit(process.returncode)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)`;
            await runCodeStreaming(shellCode, token, sandboxId, outLine, `Shell command executed: ${cmd}`);
        }

    } catch (err) {
        outLine.innerHTML = `<span class="cmd-out" style="color:var(--danger)">⚠️ Error executing command: ${err.message || err}</span>`;
    } finally {
        // ── Unlock terminal: show prompt row, re-enable input ──
        _terminalBusy = false;
        const inputEl2 = document.getElementById('terminalCommandLine');
        if (inputEl2) inputEl2.disabled = false;
        if (activeLine) activeLine.style.display = '';
        focusTerminalInput();
    }

    terminal.scrollTop = terminal.scrollHeight;
}

/* =================== ORIGINAL ORCHESTRATION CONSOLE PAYLOADS =================== */
function loadPresetsOrch(key) {
    const payload = getPresetsOrch()[key];
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

    if (output) {
        output.innerHTML = `<div style="padding:10px; color:var(--fg-muted);"><span class="spinner" style="display:inline-block; margin-right:6px;"></span> Sending orchestration payload...</div>`;
    }

    try {
        const parsed = JSON.parse(raw);
        const token = localStorage.getItem('thinkdome_token');
        const sb = state.sandboxes[state.activeSbx];
        const sandboxId = sb ? sb.id : '';

        if (!window.API || !token || !sandboxId) {
            throw new Error("Offline Mode or Sandbox disconnected");
        }

        const { data, error } = await window.API.orchestrate(parsed, token, sandboxId);
        if (error) throw new Error(error);

        if (output) {
            output.innerHTML = `
              <div style="font-size:10px;font-weight:700;color:var(--success);margin-bottom:6px;">HTTP/1.1 200 OK</div>
              <pre class="mono" style="font-size:12.5px;color:var(--fg-muted);white-space:pre-wrap;">${JSON.stringify(data, null, 2)}</pre>
            `;
        }
        addLogLine('SYS', `Engine API call completed: ${parsed.name || 'custom'}`);
    } catch (err) {
        if (output) {
            output.innerHTML = `<pre class="mono" style="color:var(--danger);font-size:12.5px;">Error: ${err.message}</pre>`;
        }
        addLogLine('ERR', `Orchestrator payload failed: ${err.message}`);
    }
}

/* =================== TERMINAL SYNC & DRAWER PARAMETERS =================== */
function updateTerminalLabel() {
    const label = document.getElementById('terminalSbxLabel');
    const promptHost = document.getElementById('terminalPromptHost');
    const statusContainer = document.getElementById('terminalStatusContainer');
    const statusDot = document.getElementById('terminalStatusDot');
    const statusText = document.getElementById('terminalStatusText');
    
    const sb = state.sandboxes[state.activeSbx];
    const sbId = sb ? sb.id : state.activeSbx;
    const isRunning = sb && sb.status === 'running';

    if (label) {
        label.textContent = sbId || '—';
    }
    if (promptHost) {
        promptHost.textContent = sbId || 'sandbox';
    }

    if (statusContainer && statusDot && statusText) {
        if (isRunning) {
            statusContainer.style.color = '#22c55e'; // green
            statusText.textContent = 'connected';
        } else {
            statusContainer.style.color = '#64748b'; // gray/muted
            statusText.textContent = 'disconnected';
        }
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

function _tryParseJSON(str) {
    try {
        if (typeof str === 'object') return str;
        return JSON.parse(str);
    } catch (e) {
        return null;
    }
}

function _escapeHtml(text) {
    if (text === null || text === undefined) return '';
    if (typeof text !== 'string') {
        text = String(text);
    }
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

async function executeStreamHelper(code, language, sandboxId, token, onChunk, onDone, onError) {
    _activeAbortController = new AbortController();
    try {
        const username = localStorage.getItem('thinkdome_username') || 'anonymous';
        const response = await fetch('/v1/execute/stream', {
            method: 'POST',
            signal: _activeAbortController.signal,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
                'X-Sandbox-Id': sandboxId
            },
            body: JSON.stringify({
                code: code,
                language: language,
                username: username,
                allow_network: true,
                security_profile: "HIGH_SECURITY",
                timeout_ms: 25000
            })
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(errText || `Server returned ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const payload = JSON.parse(line.substring(6));
                        if (payload.event === "stdout" || payload.event === "stderr") {
                            onChunk(payload.data);
                        } else if (payload.event === "done") {
                            onDone(payload);
                        }
                    } catch (e) {
                        console.error("Failed to parse SSE line:", line, e);
                    }
                }
            }
        }
        onDone({ event: "done" });
    } catch (err) {
        if (err.name === 'AbortError') {
            onError(new Error("Command terminated by user (Ctrl+C)."));
        } else {
            onError(err);
        }
    } finally {
        _activeAbortController = null;
    }
}

async function runCodeStreaming(code, token, sandboxId, outLine, onDoneLog = null) {
    outLine.innerHTML = '<span class="cmd-out" style="white-space:pre-wrap; font-family:inherit;"></span>';
    const span = outLine.firstChild;
    await executeStreamHelper(code, "python", sandboxId, token,
        (chunk) => {
            span.textContent += chunk;
            const terminal = document.getElementById('terminalConsoleBody');
            if (terminal) terminal.scrollTop = terminal.scrollHeight;
        },
        (done) => {
            if (onDoneLog) addLogLine('SYS', onDoneLog);
        },
        (err) => {
            const errSpan = document.createElement('span');
            errSpan.className = 'cmd-out';
            errSpan.style.color = 'var(--danger)';
            errSpan.textContent = `\n⚠️ Streaming error: ${err.message || err}`;
            outLine.appendChild(errSpan);
            const terminal = document.getElementById('terminalConsoleBody');
            if (terminal) terminal.scrollTop = terminal.scrollHeight;
        }
    );
}

// Global listener for Ctrl+C to terminate running process
window.addEventListener('keydown', (e) => {
    const drawer = document.querySelector('.terminal-drawer');
    const isTerminalOpen = drawer && !drawer.classList.contains('closed');
    if (isTerminalOpen && _terminalBusy) {
        if (e.ctrlKey && e.key.toLowerCase() === 'c') {
            e.preventDefault();
            if (_activeAbortController) {
                _activeAbortController.abort();
            }
        }
    }
});

async function renderIdeMcpTools() {
    const list = document.getElementById('ideMcpToolsList');
    if (!list) return;
    list.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--fg-muted); padding: 40px 0;"><span class="spinner" style="display:inline-block; margin-right:6px;"></span> Loading registered tools...</div>`;

    const token = localStorage.getItem('thinkdome_token');
    try {
        if (!window.API || !token) throw new Error("Offline");
        const { data, error } = await window.API.getTools(token);
        if (error) throw new Error(error);

        if (data && Array.isArray(data)) {
            let html = "";
            data.forEach(t => {
                const statusDot = t.is_active 
                    ? `<span style="display:inline-block; width:8px; height:8px; background:#10b981; border-radius:50%; margin-right:6px;"></span>`
                    : `<span style="display:inline-block; width:8px; height:8px; background:#ef4444; border-radius:50%; margin-right:6px;"></span>`;
                
                html += `
                    <div class="card" style="padding: 12px; cursor: pointer; border: 1px solid var(--border); transition: border-color 0.2s;" 
                         onclick="loadMcpPresetInIde('${t.name}')" 
                         onmouseover="this.style.borderColor='var(--accent)'" 
                         onmouseout="this.style.borderColor='var(--border)'">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-family: monospace; font-weight: 600; color: var(--text-heading); font-size: 13px;">${t.name}</span>
                            <span style="font-size: 11px; display: flex; align-items: center;">${statusDot} ${t.is_active ? 'Active' : 'Disabled'}</span>
                        </div>
                        <div class="faint" style="font-size: 12px; line-height: 1.4; height: 34px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">
                            ${t.description}
                        </div>
                    </div>
                `;
            });
            list.innerHTML = html || `<div style="grid-column: 1/-1; text-align: center; color: var(--fg-muted); padding: 40px 0;">No tools found in registry.</div>`;
        }
    } catch (err) {
        list.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger); padding: 40px 0;">Failed to load tools: ${err.message}</div>`;
    }
}

function loadMcpPresetInIde(toolName) {
    const sb = state.sandboxes[state.activeSbx];
    const sbxId = sb ? sb.id : '';
    
    const templates = {
        run_code: { sandbox: sbxId, language: "python", code: "print('Hello from MCP')" },
        read_file: { sandbox: sbxId, path: "README.md" },
        write_file: { sandbox: sbxId, path: "new_file.txt", content: "File content here" },
        list_dir: { sandbox: sbxId, path: "." },
        file_exists: { sandbox: sbxId, path: "README.md" },
        make_dir: { sandbox: sbxId, path: "new_folder" },
        remove_file: { sandbox: sbxId, path: "file_to_delete.txt" },
        remove_dir: { sandbox: sbxId, path: "folder_to_delete" },
        move_file: { sandbox: sbxId, src: "old.txt", dest: "new.txt" },
        copy_file: { sandbox: sbxId, src: "source.txt", dest: "dest.txt" },
        grep_search: { sandbox: sbxId, pattern: "TODO", path: "." },
        find_files: { sandbox: sbxId, pattern: "*.py", path: "." },
        get_file_info: { sandbox: sbxId, path: "README.md" },
        hash_file: { sandbox: sbxId, path: "README.md", algorithm: "sha256" },
        web_search: { sandbox: sbxId, query: "Google DeepMind" },
        http_request: { sandbox: sbxId, url: "https://httpbin.org/get", method: "GET" },
        memory_store: { sandbox: sbxId, key: "my_key", content: "my_value" },
        memory_retrieve: { sandbox: sbxId, key: "my_key" },
        memory_search: { sandbox: sbxId, query: "my_value" },
        memory_delete: { sandbox: sbxId, key: "my_key" },
        memory_list: { sandbox: sbxId, tags: [] },
        shell_exec: { sandbox: sbxId, command: "ls -la" },
        send_email: { sandbox: sbxId, to: "user@example.com", subject: "Hello", body: "World" },
        send_telegram: { sandbox: sbxId, chat_id: "123456", message: "Hello World" }
    };
    
    const input = templates[toolName] || { sandbox: sbxId };
    const payload = {
        type: "tool_use",
        id: "toolu_" + Math.random().toString(36).substring(2, 9),
        name: toolName,
        input: input
    };
    
    const textInput = document.getElementById('toolCallJsonInput');
    if (textInput) {
        textInput.value = JSON.stringify(payload, null, 2);
    }
    
    const segButtons = document.querySelectorAll('#idePaneSelectorSeg button');
    if (segButtons.length >= 2) {
        idePaneMode('tooluse', segButtons[1]); // Tool JSON is at index 1, Editor at 0, MCP Tools at 2
    }
}




