// static/js/editor.js

let editorInstance = null;

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function initMonaco() {
    if (typeof require === 'undefined') {
        setTimeout(initMonaco, 50);
        return;
    }
    require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs' } });
    require(['vs/editor/editor.main'], function () {
        const container = document.getElementById('editorContainer');
        if (!container) return;
        container.innerHTML = '';

        editorInstance = monaco.editor.create(container, {
            value: '',
            language: 'python',
            theme: state.theme === 'dark' ? 'vs-dark' : 'vs',
            automaticLayout: true,
            fontSize: 13,
            fontFamily: 'Fira Code, var(--font-mono)',
            minimap: { enabled: true },
            scrollbar: {
                vertical: 'visible',
                horizontal: 'visible',
                useShadows: false
            },
            wordWrap: 'on',
            tabSize: 4,
            cursorBlinking: 'smooth',
            smoothScrolling: true
        });

        editorInstance.onDidChangeModelContent(() => {
            const proj = state.projects[state.activeProject];
            if (proj && proj.activeFile && proj.files[proj.activeFile]) {
                proj.files[proj.activeFile].content = editorInstance.getValue();
            }
        });

        editorInstance.onDidChangeCursorPosition((e) => {
            const pos = e.position;
            const posLabel = document.getElementById('editorPosLabel');
            if (posLabel) {
                posLabel.innerText = `Ln ${pos.lineNumber}, Col ${pos.column}`;
            }
        });

        // Keyboard shortcut: Ctrl+S / Cmd+S to save file
        editorInstance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, function () {
            if (typeof saveActiveEditorFile === 'function') {
                saveActiveEditorFile();
            }
        });

        renderActiveFileContent();
        fetchExplorerFiles().then(() => {
            renderFileExplorer();
            const proj = state.projects[state.activeProject];
            if (proj && !proj.activeFile) {
                const files = Object.keys(proj.files).filter(k => proj.files[k].type === 'file');
                if (files.length > 0) {
                    openFile(files[0]);
                }
            }
        });
    });
}
initMonaco();

/* =================== PROJECTS LIFE CYCLE =================== */
async function fetchExplorerFiles() {
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    const token = localStorage.getItem('thinkdome_token');
    const container = document.getElementById('fileListContainer');
    if (container) {
        container.innerHTML = `
          <div style="padding: 14px; text-align:center; color:var(--fg-subtle); font-size:12px;">
            <span class="spinner" style="display:inline-block; margin-right:6px;"></span> Loading ${state.activeProject === 'filebox' ? 'Filebox filesystem' : 'workspace directory'}...
          </div>
        `;
    }

    try {
        if (!window.API || !token) {
            renderFileExplorer();
            return;
        }

        if (state.activeProject === 'filebox') {
            // Load live hierarchical directory tree from Filebox Browse API
            const res = await window.API.fileboxGetTree('', 6, null, token);
            if (res.data) {
                const updatedFiles = {};

                function processNode(node) {
                    if (node.type === 'directory') {
                        if (node.path) {
                            updatedFiles[node.path] = {
                                name: node.name,
                                path: node.path,
                                type: 'folder',
                                isOpen: true,
                                category: node.category || ''
                            };
                        }
                        if (Array.isArray(node.children)) {
                            node.children.forEach(processNode);
                        }
                    } else if (node.type === 'file') {
                        const existing = proj.files ? proj.files[node.path] : null;
                        updatedFiles[node.path] = {
                            name: node.name,
                            path: node.path,
                            type: 'file',
                            content: existing ? existing.content : '',
                            size: node.size,
                            category: node.category || '',
                            modified: node.modified || ''
                        };
                    }
                }

                if (Array.isArray(res.data.children)) {
                    res.data.children.forEach(processNode);
                }
                proj.files = updatedFiles;
            } else if (res.error) {
                console.warn('Filebox tree response warning:', res.error);
            }
        } else {
            // Legacy / Sandbox container volume files
            const { data, error } = await window.API.listFileBoxes(token);
            if (!error && data && Array.isArray(data.fileboxes)) {
                const updatedFiles = {};
                (data.folders || []).forEach(name => {
                    updatedFiles[name] = { name, path: name, type: 'folder', content: '', isOpen: true };
                });
                data.fileboxes.forEach(item => {
                    updatedFiles[item.path] = {
                        name: item.filename,
                        path: item.filename,
                        type: 'file',
                        content: '',
                        isOpen: true,
                        fileboxId: item.id
                    };
                });
                proj.files = updatedFiles;
            }
        }
    } catch (err) {
        console.warn('Could not fetch explorer files:', err);
    }
}

async function refreshFileExplorer(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    await fetchExplorerFiles();
    renderFileExplorer();
    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Refreshed ${state.activeProject === 'filebox' ? 'Filebox' : 'workspace'} files.`);
    }
}

async function switchProject(projKey) {
    state.activeProject = projKey;
    if (!state.projects[projKey]) {
        state.projects[projKey] = {
            name: projKey === 'filebox' ? 'Agent Filebox (Persistent)' : projKey,
            files: {},
            activeFile: null,
            openTabs: []
        };
    }
    await fetchExplorerFiles();
    renderFileExplorer();

    // Auto open first file in project
    const proj = state.projects[projKey];
    if (!proj) return;
    const files = Object.keys(proj.files).filter(k => proj.files[k].type === 'file');
    if (files.length > 0) {
        if (!proj.activeFile || !proj.files[proj.activeFile]) {
            await openFile(files[0]);
        }
    } else {
        proj.activeFile = null;
        renderTabs();
        renderActiveFileContent();
    }
}

function openCreateProjectModal() {
    const modal = document.getElementById('createProjectModal');
    if (modal) {
        document.getElementById('projectNameInput').value = '';
        document.getElementById('projectPresetInput').value = 'python';
        modal.classList.add('active');
    }
}

function closeCreateProjectModal() {
    const modal = document.getElementById('createProjectModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function submitCreateProjectModal(e) {
    e.preventDefault();
    const name = document.getElementById('projectNameInput').value.trim();
    const preset = document.getElementById('projectPresetInput').value;

    if (!name) return;

    // Generate unique slug/key
    const key = name.toLowerCase().replace(/[^a-z0-9]/g, '-');
    if (state.projects[key]) {
        showCustomAlert("Project Error", "A project with that name already exists!");
        return;
    }

    // Set up initial files based on preset
    let files = {};
    let activeFile = null;
    let openTabs = [];

    if (preset === 'python') {
        files['main.py'] = { name: 'main.py', path: 'main.py', content: 'print("Hello from your new Python project!")\n', type: 'file' };
        files['requirements.txt'] = { name: 'requirements.txt', path: 'requirements.txt', content: 'numpy\n', type: 'file' };
        activeFile = 'main.py';
        openTabs = ['main.py'];
    } else if (preset === 'node') {
        files['index.js'] = { name: 'index.js', path: 'index.js', content: 'console.log("Hello from your new Node.js project!");\n', type: 'file' };
        files['package.json'] = { name: 'package.json', path: 'package.json', content: '{\n  "name": "' + key + '",\n  "version": "1.0.0",\n  "main": "index.js"\n}\n', type: 'file' };
        activeFile = 'index.js';
        openTabs = ['index.js'];
    }

    // Create the project in state
    state.projects[key] = {
        name: name,
        files: files,
        activeFile: activeFile,
        openTabs: openTabs
    };

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Created new project workspace: ${name} [${preset}]`);
    }
    if (typeof addAuditEvent === 'function') {
        addAuditEvent(`Created project workspace: ${name}`);
    }

    closeCreateProjectModal();
    
    // Switch to the newly created project
    switchProject(key);
    renderAllViews();
}

function renderProjectDropdown() {
    const select = document.getElementById('ideProjectSelect');
    if (!select) return;
    
    // Save current selection value
    const curVal = select.value || state.activeProject;
    
    // Clear option children
    select.innerHTML = '';
    
    // Populate from state.projects
    Object.keys(state.projects).forEach(key => {
        const proj = state.projects[key];
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = `📁 ${proj.name}`;
        select.appendChild(opt);
    });
    
    // Restore selection
    if (state.projects[curVal]) {
        select.value = curVal;
    }
}

/* =================== FILE EXPLORER TREE GENERATOR =================== */
function buildTree(files) {
    const root = { name: 'root', type: 'folder', children: {}, path: '' };

    // First, add all folder structures explicitly registered in state
    Object.keys(files).forEach(path => {
        const item = files[path];
        if (item.type === 'folder') {
            const parts = path.split('/');
            let current = root;
            let curPath = '';
            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                curPath = curPath ? `${curPath}/${part}` : part;
                if (!current.children[part]) {
                    current.children[part] = {
                        name: part,
                        type: 'folder',
                        path: curPath,
                        isOpen: item.isOpen !== undefined ? item.isOpen : true,
                        children: {}
                    };
                }
                current = current.children[part];
            }
        }
    });

    // Next, add all files. Auto-create parent folders if they don't exist in state
    Object.keys(files).forEach(path => {
        const item = files[path];
        if (item.type === 'file') {
            const parts = path.split('/');
            let current = root;
            let curPath = '';
            for (let i = 0; i < parts.length - 1; i++) {
                const part = parts[i];
                curPath = curPath ? `${curPath}/${part}` : part;
                if (!current.children[part]) {
                    current.children[part] = {
                        name: part,
                        type: 'folder',
                        path: curPath,
                        isOpen: true,
                        children: {}
                    };
                }
                current = current.children[part];
            }
            const fileName = parts[parts.length - 1];
            current.children[fileName] = {
                name: fileName,
                type: 'file',
                path: path
            };
        }
    });

    return root;
}

function getFileIconSvg(filePath) {
    const fileName = filePath.split('/').pop();
    const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';

    switch (ext) {
        case 'py':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon python-ico" title="Python File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 12a2 2 0 0 1 2-2h2v4h2a2 2 0 0 1-2-2" stroke-width="1.5"></path></svg>`;
        case 'json':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon json-ico" title="JSON File"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><path d="M9 10L10.5 12L9 14M15 14L13.5 12L15 10"></path></svg>`;
        case 'yaml':
        case 'yml':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon yaml-ico" title="YAML File" style="color:var(--warn);"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><path d="M8 9l4 4 4-4M12 13v4" stroke-width="1.5"></path></svg>`;
        case 'js':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon js-ico" title="JavaScript File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M10 12h2v3a1 1 0 0 1-1 1H9M13 16h2" stroke-width="1.5"></path></svg>`;
        case 'html':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon html-ico" title="HTML File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 12l-2 2 2 2M16 12l2 2-2 2M11 11l2 6" stroke-width="1.5"></path></svg>`;
        case 'css':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon css-ico" title="CSS File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 12h8M8 15h8M12 12v3" stroke-width="1.5"></path></svg>`;
        case 'md':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon md-ico" title="Markdown File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M7 12v3h2v-3h2v3h2v-3M16 12l2 2-2 2" stroke-width="1.5"></path></svg>`;
        case 'sh':
        case 'bash':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon sh-ico" title="Shell Script" style="color:var(--accent-emerald);"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>`;
        case 'sql':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon sql-ico" title="SQL Query" style="color:var(--accent);"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>`;
        case 'txt':
        case 'log':
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon txt-ico" title="Text File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="8" y1="12" x2="16" y2="12"></line><line x1="8" y1="16" x2="16" y2="16"></line></svg>`;
        default:
            return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="file-type-icon default-ico" title="File"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
    }
}

function getFolderIconSvg(isOpen, folderName = '') {
    const fn = (folderName || '').toLowerCase();
    if (fn === 'memory') return '🧠';
    if (fn === 'skills') return '⚡';
    if (fn === 'knowledge') return '📚';
    if (fn === 'workspace') return '💼';
    if (fn === 'identity') return '🆔';
    if (fn === 'config') return '⚙️';
    if (fn === 'state') return '⏱️';
    if (fn === 'logs') return '📋';

    if (isOpen) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"></path><path d="M2 10h20"></path></svg>`;
    } else {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"></path></svg>`;
    }
}

function renderTreeNode(node, depth = 0) {
    if (node.name === 'root') {
        return Object.keys(node.children)
            .map(key => renderTreeNode(node.children[key], depth))
            .join('');
    }

    const isFolder = node.type === 'folder';

    if (isFolder) {
        const chevronSvg = node.isOpen ?
            `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="chevron-ico" style="transform: rotate(0deg);"><polyline points="6 9 12 15 18 9"></polyline></svg>` :
            `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="chevron-ico" style="transform: rotate(-90deg);"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
        const folderIconSvg = getFolderIconSvg(node.isOpen, node.name);

        let html = `
          <div class="folder-row" 
               draggable="true"
               ondragstart="handleDragStart(event, '${node.path}')"
               ondragover="handleDragOver(event)"
               ondragenter="handleDragEnter(event, this)"
               ondragleave="handleDragLeave(event, this)"
               ondrop="handleDrop(event, '${node.path}')"
               onclick="toggleFolderOpen(event, '${node.path}')">
            <div class="folder-row-title">
              ${chevronSvg}
              <span class="folder-icon">${folderIconSvg}</span>
              <span class="folder-name">${node.name}</span>
            </div>
            <div class="folder-actions">
              <button onclick="promptCreateFileInFolder(event, '${node.path}')" title="Create File">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              </button>
              <button onclick="promptRenameItem(event, '${node.path}')" title="Rename Folder">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
              </button>
              <button onclick="deleteFolder(event, '${node.path}')" title="Delete Folder">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path></svg>
              </button>
            </div>
          </div>
        `;

        if (node.isOpen) {
            html += `
            <div class="folder-children-container">
              ${Object.keys(node.children).map(key => renderTreeNode(node.children[key], depth + 1)).join('')}
            </div>
          `;
        }
        return html;
    } else {
        const proj = state.projects[state.activeProject];
        const isActive = proj.activeFile === node.path ? 'active' : '';
        const fileIconSvg = getFileIconSvg(node.path);

        return `
          <div class="file-item file-row ${isActive}" 
               draggable="true" 
               ondragstart="handleDragStart(event, '${node.path}')"
               ondragover="handleDragOver(event)"
               ondragenter="handleDragEnter(event, this)"
               ondragleave="handleDragLeave(event, this)"
               ondrop="handleDrop(event, '${node.path}')"
               onclick="openFile('${node.path}')">
            <div class="file-item-title">
              ${fileIconSvg}
              <span class="file-name">${node.name}</span>
            </div>
            <div class="file-actions">
              <button onclick="promptRenameItem(event, '${node.path}')" title="Rename File">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
              </button>
              <button onclick="duplicateFile(event, '${node.path}')" title="Duplicate File">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              </button>
              <button onclick="deleteFile(event, '${node.path}')" title="Delete File">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path></svg>
              </button>
            </div>
          </div>
        `;
    }
}

function renderFileExplorer() {
    const proj = state.projects[state.activeProject];
    if (!proj) return;
    const container = document.getElementById('fileListContainer');
    if (!container) return;

    const tree = buildTree(proj.files);
    container.innerHTML = renderTreeNode(tree);
}

function toggleFolderOpen(e, folderPath) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];

    // Ensure the folder exists in state, toggle its open state
    if (!proj.files[folderPath]) {
        proj.files[folderPath] = { name: folderPath.split('/').pop(), path: folderPath, type: 'folder', isOpen: true };
    }

    const folder = proj.files[folderPath];
    folder.isOpen = folder.isOpen === undefined ? false : !folder.isOpen;

    renderFileExplorer();
}

/* =================== FILE CRUD UTILS =================== */
async function promptCreateFile() {
    const promptPlaceholder = state.activeProject === 'filebox' ? "workspace/model.py" : "model.py";
    const name = await showCustomPrompt("Create New File", `Enter new file path (${state.activeProject === 'filebox' ? 'e.g. workspace/script.py or memory/note.md' : 'at root'}):`, promptPlaceholder);
    if (!name) return;
    await createFileInProject(name.trim());
}

async function promptCreateFileInFolder(e, folderPath) {
    e.stopPropagation();
    const name = await showCustomPrompt("Create New File", `Enter new filename inside ${folderPath}/:`, "script.py");
    if (!name) return;
    const cleanName = name.trim().replace(/^\/+/, '');
    await createFileInProject(folderPath + '/' + cleanName);
}

async function createFileInProject(fullPath) {
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    let targetPath = fullPath.trim().replace(/^\/+/, '');
    if (state.activeProject === 'filebox' && !targetPath.includes('/')) {
        // Default relative files without directory to workspace/
        targetPath = 'workspace/' + targetPath;
    }

    if (proj.files[targetPath]) {
        await showCustomAlert("File Action Error", `A file with path "${targetPath}" already exists.`);
        return;
    }

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (!token) {
            throw new Error("You must be logged in to create files.");
        }

        if (state.activeProject === 'filebox') {
            if (!window.API?.fileboxWriteFile) {
                throw new Error("Filebox API is unavailable");
            }
            const ext = targetPath.split('.').pop().toLowerCase();
            let defaultContent = `# ${targetPath.split('/').pop()}\n\n`;
            if (ext === 'json') defaultContent = '{\n  \n}\n';
            else if (ext === 'yaml' || ext === 'yml') defaultContent = '# Configuration\n';
            else if (ext === 'md') defaultContent = `# ${targetPath.split('/').pop()}\n\n`;
            else if (ext === 'js') defaultContent = `// ${targetPath.split('/').pop()}\n\n`;
            else if (ext === 'html') defaultContent = `<!DOCTYPE html>\n<html>\n<head>\n  <title>Document</title>\n</head>\n<body>\n\n</body>\n</html>\n`;

            const res = await window.API.fileboxWriteFile(targetPath, defaultContent, "Created via Web IDE", null, token);
            if (res.error) throw new Error(res.error);

            proj.files[targetPath] = {
                name: targetPath.split('/').pop(),
                path: targetPath,
                content: defaultContent,
                type: 'file'
            };

            await fetchExplorerFiles();
            renderFileExplorer();
            await openFile(targetPath);

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Created file ${targetPath} in Filebox.`);
            }
        } else {
            const sb = state.sandboxes[state.activeSbx];
            const sandboxId = sb ? sb.id : '';
            if (!sandboxId) {
                throw new Error("Sandbox disconnected. Switch to '📦 Agent Filebox' for persistent storage.");
            }
            const { error } = await window.API.writeFile(targetPath, "# New file created\n", token, sandboxId);
            if (error) throw new Error(error);

            proj.files[targetPath] = {
                name: targetPath.split('/').pop(),
                path: targetPath,
                content: `# New file created\n`,
                type: 'file'
            };

            await openFile(targetPath);
            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Created file ${targetPath} in sandbox workspace.`);
            }
        }
    } catch (err) {
        await showCustomAlert("Failed to Create File", `Could not create file: ${err.message}`);
    }
}

async function promptCreateFolder() {
    const promptPlaceholder = state.activeProject === 'filebox' ? "workspace/my_project" : "src";
    const name = await showCustomPrompt("Create New Folder", `Enter folder path (${state.activeProject === 'filebox' ? 'e.g. workspace/my_project' : 'at root'}):`, promptPlaceholder);
    if (!name) return;
    await createFolderInProject(name.trim());
}

async function createFolderInProject(folderPath) {
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    let targetPath = folderPath.trim().replace(/^\/+/, '').replace(/\/+$/, '');
    if (state.activeProject === 'filebox' && !targetPath.includes('/')) {
        targetPath = 'workspace/' + targetPath;
    }

    if (proj.files[targetPath]) {
        await showCustomAlert("Folder Action Error", `A folder or file at "${targetPath}" already exists.`);
        return;
    }

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (state.activeProject === 'filebox') {
            if (window.API?.fileboxMkdir && token) {
                const res = await window.API.fileboxMkdir(targetPath, null, token);
                if (res.error) throw new Error(res.error);
            }
        }

        proj.files[targetPath] = {
            name: targetPath.split('/').pop(),
            path: targetPath,
            type: 'folder',
            isOpen: true
        };

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Created folder ${targetPath}`);
        }
        await fetchExplorerFiles();
        renderFileExplorer();
    } catch (err) {
        await showCustomAlert("Failed to Create Folder", `Could not create folder: ${err.message}`);
    }
}

async function deleteFolder(e, folderPath) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    const ok = await showCustomConfirm("Delete Folder", `Delete folder "${folderPath}" and all its contents recursively?`);
    if (!ok) return;

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (state.activeProject === 'filebox') {
            if (window.API?.fileboxDelete && token) {
                const res = await window.API.fileboxDelete(folderPath, "Deleted folder via Web IDE", null, token);
                if (res.error) throw new Error(res.error);
            }
        }

        // Delete all matching items in flat files directory
        Object.keys(proj.files).forEach(path => {
            if (path === folderPath || path.startsWith(folderPath + '/')) {
                delete proj.files[path];
                proj.openTabs = proj.openTabs.filter(t => t !== path);
            }
        });

        // Set active file to something else if active was deleted
        if (proj.activeFile && !proj.files[proj.activeFile]) {
            const fileKeys = Object.keys(proj.files).filter(k => proj.files[k].type === 'file');
            proj.activeFile = fileKeys[0] || null;
        }

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Recursively deleted folder ${folderPath}.`);
        }
        await fetchExplorerFiles();
        renderFileExplorer();
        renderTabs();
        renderActiveFileContent();
    } catch (err) {
        await showCustomAlert("Delete Failed", `Could not delete folder: ${err.message}`);
    }
}

async function openFile(fKey) {
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    if (!proj.files[fKey]) {
        proj.files[fKey] = {
            name: fKey.split('/').pop(),
            path: fKey,
            type: 'file',
            content: ''
        };
    }

    proj.activeFile = fKey;

    if (!proj.openTabs.includes(fKey)) {
        proj.openTabs.push(fKey);
    }

    // Sync Language pill
    const ext = fKey.includes('.') ? fKey.split('.').pop().toLowerCase() : '';
    const langLabel = document.getElementById('editorLangLabel');
    if (langLabel) {
        langLabel.innerText = ext || 'text';
    }

    // Load content dynamically from backend if empty or not yet loaded
    const file = proj.files[fKey];
    if (file && file.type === 'file' && (file.content === '' || file.content === undefined)) {
        const token = localStorage.getItem('thinkdome_token');

        if (editorInstance) {
            editorInstance.setValue("# Loading file content...");
            editorInstance.updateOptions({ readOnly: true });
        }

        try {
            if (state.activeProject === 'filebox') {
                if (window.API?.fileboxReadFile && token) {
                    const res = await window.API.fileboxReadFile(fKey, null, token);
                    if (res.data) {
                        file.content = res.data.content || '';
                    } else if (res.error) {
                        file.content = `# Error loading file: ${res.error}\n`;
                    }
                } else {
                    file.content = `# Unable to connect to Filebox API. Ensure you are logged in.\n`;
                }
            } else {
                const sb = state.sandboxes[state.activeSbx];
                const sandboxId = sb ? sb.id : '';
                if (!window.API || !token || !sandboxId) {
                    throw new Error("Offline or Sandbox disconnected");
                }
                const { data, error } = await window.API.readFile(fKey, token, sandboxId);
                if (error) throw new Error(error);
                file.content = data;
            }
        } catch (err) {
            file.content = `# Unable to load file content.\n# ${err.message}\n`;
        }
    }

    renderFileExplorer();
    renderTabs();
    renderActiveFileContent();
}

function renderTabs() {
    const proj = state.projects[state.activeProject];
    const bar = document.getElementById('ideTabsBar');
    if (!bar) return;

    bar.innerHTML = proj.openTabs.map(tKey => {
        const fileName = tKey.split('/').pop();
        const iconSvg = getFileIconSvg(tKey);
        return `
          <div class="ide-tab ${proj.activeFile === tKey ? 'active' : ''}" onclick="openFile('${tKey}')">
            ${iconSvg}
            <span>${fileName}</span>
            <span class="close-tab" onclick="closeTab(event, '${tKey}')">&times;</span>
          </div>
        `;
    }).join('');
}

function closeTab(e, tKey) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];
    proj.openTabs = proj.openTabs.filter(t => t !== tKey);

    if (proj.activeFile === tKey && proj.openTabs.length > 0) {
        proj.activeFile = proj.openTabs[proj.openTabs.length - 1];
    } else if (proj.openTabs.length === 0) {
        proj.activeFile = null;
    }

    renderTabs();
    renderFileExplorer();
    renderActiveFileContent();
}

function renderActiveFileContent() {
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    if (editorInstance) {
        if (proj.activeFile && proj.files[proj.activeFile]) {
            const file = proj.files[proj.activeFile];
            if (editorInstance.getValue() !== file.content) {
                editorInstance.setValue(file.content);
            }

            const ext = file.path.split('.').pop().toLowerCase();
            let lang = 'plaintext';
            if (ext === 'py') lang = 'python';
            else if (ext === 'json') lang = 'json';
            else if (ext === 'js') lang = 'javascript';
            else if (ext === 'ts') lang = 'typescript';
            else if (ext === 'css') lang = 'css';
            else if (ext === 'html') lang = 'html';
            else if (ext === 'md') lang = 'markdown';
            else if (ext === 'yaml' || ext === 'yml') lang = 'yaml';
            else if (ext === 'sh' || ext === 'bash') lang = 'shell';
            else if (ext === 'sql') lang = 'sql';

            const model = editorInstance.getModel();
            if (model) {
                monaco.editor.setModelLanguage(model, lang);
            }

            editorInstance.updateOptions({ readOnly: false });
        } else {
            editorInstance.setValue('# No active document. Create or open a file to edit.');
            editorInstance.updateOptions({ readOnly: true });
        }
    }

    updateBreadcrumb();
}

async function saveActiveEditorFile() {
    const proj = state.projects[state.activeProject];
    if (!proj || !proj.activeFile || !editorInstance) return;

    const token = localStorage.getItem('thinkdome_token');
    const code = editorInstance.getValue();
    const saveBtn = document.getElementById('btn-save-file');
    const saveLabel = document.getElementById('btn-save-file-label');

    try {
        if (state.activeProject === 'filebox') {
            if (!window.API?.fileboxWriteFile || !token) {
                throw new Error("Filebox API offline or not authenticated");
            }
            const res = await window.API.fileboxWriteFile(proj.activeFile, code, "Saved via Web IDE", null, token);
            if (res.error) throw new Error(res.error);

            if (proj.files[proj.activeFile]) {
                proj.files[proj.activeFile].content = code;
            }

            if (saveLabel) {
                saveLabel.textContent = "✓ Saved";
                if (saveBtn) saveBtn.style.color = "var(--success)";
                setTimeout(() => {
                    saveLabel.textContent = "Save";
                    if (saveBtn) saveBtn.style.color = "";
                }, 1500);
            }

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Saved ${proj.activeFile} to Filebox.`);
            }
        } else {
            const sb = state.sandboxes[state.activeSbx];
            const sandboxId = sb ? sb.id : '';
            if (!sandboxId) {
                throw new Error("No active sandbox connected to save file.");
            }
            const { error } = await window.API.writeFile(proj.activeFile, code, token, sandboxId);
            if (error) throw new Error(error);

            if (proj.files[proj.activeFile]) {
                proj.files[proj.activeFile].content = code;
            }

            if (saveLabel) {
                saveLabel.textContent = "✓ Saved";
                if (saveBtn) saveBtn.style.color = "var(--success)";
                setTimeout(() => {
                    saveLabel.textContent = "Save";
                    if (saveBtn) saveBtn.style.color = "";
                }, 1500);
            }

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Saved ${proj.activeFile} to sandbox.`);
            }
        }
    } catch (err) {
        await showCustomAlert("Save Failed", `Could not save file: ${err.message}`);
    }
}

async function deleteFile(e, fKey) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];
    if (!proj) return;

    const ok = await showCustomConfirm("Delete File", `Are you sure you want to permanently delete file "${fKey}"?`);
    if (!ok) return;

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (state.activeProject === 'filebox') {
            if (!window.API?.fileboxDelete || !token) {
                throw new Error("Filebox API offline or not authenticated");
            }
            const res = await window.API.fileboxDelete(fKey, "Deleted via Web IDE", null, token);
            if (res.error) throw new Error(res.error);

            delete proj.files[fKey];
            proj.openTabs = proj.openTabs.filter(t => t !== fKey);

            if (proj.activeFile === fKey) {
                const fileKeys = Object.keys(proj.files).filter(k => proj.files[k].type === 'file');
                proj.activeFile = fileKeys[0] || null;
            }

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Deleted file ${fKey} from Filebox.`);
            }
            await fetchExplorerFiles();
            renderFileExplorer();
            renderTabs();
            renderActiveFileContent();
        } else {
            const sb = state.sandboxes[state.activeSbx];
            const sandboxId = sb ? sb.id : '';
            if (!sandboxId) {
                throw new Error("Sandbox disconnected");
            }

            const { error } = await window.API.orchestrate({
                type: "tool_use",
                id: "toolu_delete_file",
                name: "run_code",
                input: {
                    sandbox: sandboxId,
                    language: "python",
                    code: `import os; os.remove('${fKey}')`
                }
            }, token, sandboxId);
            if (error) throw new Error(error);

            delete proj.files[fKey];
            proj.openTabs = proj.openTabs.filter(t => t !== fKey);

            if (proj.activeFile === fKey) {
                const fileKeys = Object.keys(proj.files).filter(k => proj.files[k].type === 'file');
                proj.activeFile = fileKeys[0] || null;
            }

            if (typeof addLogLine === 'function') {
                addLogLine('SYS', `Deleted file ${fKey} from workspace.`);
            }
            await fetchExplorerFiles();
            renderFileExplorer();
            renderTabs();
            renderActiveFileContent();
        }
    } catch (err) {
        await showCustomAlert("Delete Failed", `Could not delete file: ${err.message}`);
    }
}

/* =================== GUTTER CONTROLS =================== */
function syncGutter() { }
function syncGutterScroll() { }

/* =================== RUN ACTIVE CODE AND SIMULATORS =================== */
async function runActiveEditorCode() {
    const proj = state.projects[state.activeProject];
    if (!proj || !proj.activeFile) {
        await showCustomAlert("Code Compile Error", "No active python file loaded to compile.");
        return;
    }

    const code = editorInstance ? editorInstance.getValue() : (proj.files[proj.activeFile] ? proj.files[proj.activeFile].content : '');
    
    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Initializing execution flow for ${proj.activeFile} on node ${state.activeSbx}`);
        addLogLine('INFO', 'Validating virtual environment libraries...');
    }

    const outputBox = document.getElementById('resultOutputContainer');
    const metricsBox = document.getElementById('metricsOutputContainer');

    if (outputBox) outputBox.innerHTML = `<div style="padding:20px; text-align:center;"><span class="spinner" style="display:inline-block; margin-right:6px;"></span> Preparing execution...</div>`;
    if (metricsBox) metricsBox.innerHTML = `<div style="padding:20px; text-align:center;"><span class="spinner" style="display:inline-block; margin-right:6px;"></span> Collecting metrics...</div>`;

    const token = localStorage.getItem('thinkdome_token');
    const sb = state.sandboxes[state.activeSbx];
    const sandboxId = sb ? sb.id : '';

    try {
        if (state.activeProject === 'filebox') {
            await saveActiveEditorFile();
        }

        if (!sandboxId) {
            if (state.activeProject === 'filebox') {
                if (outputBox) {
                    outputBox.innerHTML = `
                      <div style="background:var(--surface-raised);border:1px solid var(--border);border-radius:10px;padding:16px;">
                        <div style="color:var(--success);font-weight:600;margin-bottom:8px;">✓ Saved to Filebox (${escapeHtml(proj.activeFile)})</div>
                        <p style="color:var(--fg-muted);font-size:12px;line-height:1.5;margin:0;">
                          Your file has been saved to the persistent Filebox filesystem.<br>
                          To execute this code in an isolated container, select a running sandbox from the target dropdown above.
                        </p>
                      </div>
                    `;
                }
                if (metricsBox) {
                    metricsBox.innerHTML = `
                      <div style="padding:16px;text-align:center;color:var(--fg-muted);font-size:12px;">
                        Filebox persistent file • Ready for sandbox execution
                      </div>
                    `;
                }
                return;
            }
            throw new Error("Offline Mode or Sandbox disconnected");
        }

        if (!window.API || !token) {
            throw new Error("Authentication required");
        }

        await window.API.writeFile(proj.activeFile, code, token, sandboxId);

        const ext = proj.activeFile.split('.').pop().toLowerCase();
        const startTs = performance.now();
        const { data, error } = await window.API.orchestrate({
            type: "tool_use",
            id: "toolu_run_editor",
            name: "run_code",
            input: {
                sandbox: sandboxId,
                language: ext === 'js' ? 'javascript' : 'python',
                code: code
            }
        }, token, sandboxId);
        const duration = ((performance.now() - startTs) / 1000).toFixed(2);

        if (error) throw new Error(error);

        let outText = data.content || '';
        const isErr = data.is_error;

        if (outputBox) {
            outputBox.innerHTML = `<pre class="mono" style="font-size:13px;color:${isErr ? 'var(--danger)' : 'var(--fg-muted)'};background:var(--surface-raised);border:1px solid var(--border);border-radius:10px;padding:14px;white-space:pre-wrap;margin-bottom:12px;">${outText}</pre>`;
        }

        if (metricsBox) {
            metricsBox.innerHTML = `
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                <div class="billing-sub-card">
                  <div class="label" style="font-size:11px;">Execution Time</div>
                  <div class="value" style="font-size:20px;margin-top:4px;">${duration}s</div>
                  <div class="stat-sub">Sandbox processing overhead</div>
                </div>
                <div class="billing-sub-card">
                  <div class="label" style="font-size:11px;">Status</div>
                  <div class="value" style="font-size:20px;margin-top:4px;color:${isErr ? 'var(--danger)' : 'var(--success)'};">${isErr ? 'Error' : 'Success'}</div>
                  <div class="stat-sub">Return status code</div>
                </div>
              </div>
            `;
        }

        if (typeof addLogLine === 'function') {
            if (isErr) {
                addLogLine('ERR', `Execution failed: ${outText.substring(0, 60)}`);
            } else {
                addLogLine('SUCCESS', `Code execution complete. Output piped inside container.`);
            }
        }

    } catch (err) {
        if (outputBox) {
            outputBox.innerHTML = `<pre class="mono" style="font-size:13px;color:var(--danger);background:var(--surface-raised);border:1px solid var(--border);border-radius:10px;padding:14px;white-space:pre-wrap;margin-bottom:12px;">⚠️ Execution Failed: ${err.message || err}</pre>`;
        }
        if (metricsBox) {
            metricsBox.innerHTML = `
              <div style="display:grid;grid-template-columns:1fr;gap:14px;">
                <div class="billing-sub-card">
                  <div class="label" style="font-size:11px;">Status</div>
                  <div class="value" style="font-size:20px;margin-top:4px;color:var(--fg-muted);">Unavailable</div>
                  <div class="stat-sub">Container runtime is not reachable</div>
                </div>
              </div>
            `;
        }
        if (typeof addLogLine === 'function') {
            addLogLine('ERR', `Execution request failed: ${err.message || err}`);
        }
    }

    if (typeof switchRightTab === 'function') {
        switchRightTab('result', document.querySelectorAll('.rtab')[1]);
    }
}

async function executeIdeToolUse() {
    const rawInput = document.getElementById('toolCallJsonInput');
    if (!rawInput) return;
    const raw = rawInput.value;
    if (typeof addLogLine === 'function') {
        addLogLine('SYS', 'Parsing input Anthropic tool call descriptor payload...');
    }
    try {
        const parsed = JSON.parse(raw);
        if (typeof addLogLine === 'function') {
            addLogLine('INFO', `Routing API trigger for command schema [${parsed.name || 'unknown'}]`);
        }

        const out = document.getElementById('resultOutputContainer');
        if (out) {
            out.innerHTML = `<div style="padding:20px; text-align:center;"><span class="spinner" style="display:inline-block; margin-right:6px;"></span> Sending tool request to orchestrator...</div>`;
        }

        const token = localStorage.getItem('thinkdome_token');
        const sb = state.sandboxes[state.activeSbx];
        const sandboxId = sb ? sb.id : '';

        if (!window.API || !token || !sandboxId) {
            throw new Error("Offline Mode or Sandbox disconnected");
        }

        const { data, error } = await window.API.orchestrate(parsed, token, sandboxId);
        if (error) throw new Error(error);

        if (out) {
            out.innerHTML = `
                <div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:8px;text-transform:uppercase;">API Tool Result Payload</div>
                <pre class="mono" style="font-size:13px;color:var(--fg-muted);background:var(--surface-raised);border:1px solid var(--border);border-radius:10px;padding:14px;white-space:pre-wrap;">${JSON.stringify(data, null, 2)}</pre>
            `;
        }

        if (typeof addLogLine === 'function') {
            addLogLine('SUCCESS', 'API JSON evaluation routed successfully.');
        }
        if (typeof switchRightTab === 'function') {
            switchRightTab('result', document.querySelectorAll('.rtab')[1]);
        }
    } catch (err) {
        if (typeof addLogLine === 'function') {
            addLogLine('ERR', `Tool Use Execution failed: ${err.message}`);
        }
        const out = document.getElementById('resultOutputContainer');
        if (out) {
            out.innerHTML = `
                <div style="font-size:11px;font-weight:700;color:var(--danger);margin-bottom:8px;text-transform:uppercase;">Execution Error</div>
                <pre class="mono" style="font-size:13px;color:var(--danger);background:var(--surface-raised);border:1px solid var(--border);border-radius:10px;padding:14px;white-space:pre-wrap;">Error: ${err.message}</pre>
            `;
        }
        await showCustomAlert("Tool Use Execution Failure", err.message);
    }
}

/* =================== DRAG & DROP FILE MANAGEMENT =================== */
function handleDragStart(e, itemPath) {
    e.stopPropagation();
    e.dataTransfer.setData('text/plain', itemPath);
    e.dataTransfer.effectAllowed = 'move';
    e.currentTarget.style.opacity = '0.4';
    setTimeout(() => { e.currentTarget.style.opacity = '1'; }, 300);
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e, el) {
    e.preventDefault();
    el.classList.add('drag-over');
}

function handleDragLeave(e, el) {
    el.classList.remove('drag-over');
}

async function handleDrop(e, targetFolderPath) {
    e.preventDefault();
    e.stopPropagation();

    // Remove all drag-over highlights
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));

    const sourcePath = e.dataTransfer.getData('text/plain');
    if (!sourcePath || sourcePath === targetFolderPath) return;

    const proj = state.projects[state.activeProject];
    const sourceItem = proj.files[sourcePath];
    if (!sourceItem) return;

    const sourceName = sourcePath.split('/').pop();
    const newPath = targetFolderPath ? `${targetFolderPath}/${sourceName}` : sourceName;

    if (newPath === sourcePath) return;
    if (proj.files[newPath]) {
        await showCustomAlert("Move Error", `A file or folder named "${sourceName}" already exists in that location.`);
        return;
    }

    if (sourceItem.type === 'file') {
        proj.files[newPath] = { ...sourceItem, path: newPath, name: sourceName };
        delete proj.files[sourcePath];

        // Update tabs
        const tabIdx = proj.openTabs.indexOf(sourcePath);
        if (tabIdx !== -1) proj.openTabs[tabIdx] = newPath;
        if (proj.activeFile === sourcePath) proj.activeFile = newPath;

    } else if (sourceItem.type === 'folder') {
        // Move folder and all children
        const keysToMove = Object.keys(proj.files).filter(k => k === sourcePath || k.startsWith(sourcePath + '/'));
        keysToMove.forEach(oldKey => {
            const suffix = oldKey.substring(sourcePath.length);
            const newKey = newPath + suffix;
            proj.files[newKey] = { ...proj.files[oldKey], path: newKey, name: newKey.split('/').pop() };
            delete proj.files[oldKey];

            const tabIdx = proj.openTabs.indexOf(oldKey);
            if (tabIdx !== -1) proj.openTabs[tabIdx] = newKey;
            if (proj.activeFile === oldKey) proj.activeFile = newKey;
        });
    }

    if (typeof addLogLine === 'function') {
        addLogLine('SYS', `Moved ${sourceName} → ${targetFolderPath || 'root'}`);
    }
    renderFileExplorer();
    renderTabs();
    renderActiveFileContent();
}

/* =================== FILE RENAME & DUPLICATE =================== */
async function promptRenameItem(e, itemPath) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];
    if (!proj) return;
    const item = proj.files[itemPath];
    if (!item) return;

    const oldName = itemPath.split('/').pop();
    const newName = await showCustomPrompt("Rename Item", `Rename "${oldName}" to:`, oldName);
    if (!newName || newName === oldName) return;

    const parentPath = itemPath.includes('/') ? itemPath.substring(0, itemPath.lastIndexOf('/')) : '';
    const newPath = parentPath ? `${parentPath}/${newName}` : newName;

    if (proj.files[newPath]) {
        await showCustomAlert("Rename Error", `"${newName}" already exists in that location.`);
        return;
    }

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (state.activeProject === 'filebox' && window.API?.fileboxMove && token) {
            const res = await window.API.fileboxMove(itemPath, newPath, "Renamed via Web IDE", null, token);
            if (res.error) throw new Error(res.error);
        }

        if (item.type === 'file') {
            proj.files[newPath] = { ...item, path: newPath, name: newName };
            delete proj.files[itemPath];

            const tabIdx = proj.openTabs.indexOf(itemPath);
            if (tabIdx !== -1) proj.openTabs[tabIdx] = newPath;
            if (proj.activeFile === itemPath) proj.activeFile = newPath;
        } else {
            // Rename folder and all children
            const keysToRename = Object.keys(proj.files).filter(k => k === itemPath || k.startsWith(itemPath + '/'));
            keysToRename.forEach(oldKey => {
                const suffix = oldKey.substring(itemPath.length);
                const newKey = newPath + suffix;
                proj.files[newKey] = { ...proj.files[oldKey], path: newKey, name: newKey.split('/').pop() };
                delete proj.files[oldKey];

                const tabIdx = proj.openTabs.indexOf(oldKey);
                if (tabIdx !== -1) proj.openTabs[tabIdx] = newKey;
                if (proj.activeFile === oldKey) proj.activeFile = newKey;
            });
        }

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Renamed ${oldName} → ${newName}`);
        }
        await fetchExplorerFiles();
        renderFileExplorer();
        renderTabs();
        renderActiveFileContent();
    } catch (err) {
        await showCustomAlert("Rename Failed", `Could not rename: ${err.message}`);
    }
}

async function duplicateFile(e, fKey) {
    e.stopPropagation();
    const proj = state.projects[state.activeProject];
    if (!proj) return;
    const original = proj.files[fKey];
    if (!original || original.type !== 'file') return;

    const ext = fKey.includes('.') ? '.' + fKey.split('.').pop() : '';
    const baseName = fKey.includes('.') ? fKey.substring(0, fKey.lastIndexOf('.')) : fKey;
    let copyPath = `${baseName}_copy${ext}`;
    let counter = 1;
    while (proj.files[copyPath]) {
        counter++;
        copyPath = `${baseName}_copy${counter}${ext}`;
    }

    const token = localStorage.getItem('thinkdome_token');

    try {
        if (state.activeProject === 'filebox' && window.API?.fileboxWriteFile && token) {
            const res = await window.API.fileboxWriteFile(copyPath, original.content || '', "Duplicated via Web IDE", null, token);
            if (res.error) throw new Error(res.error);
        }

        proj.files[copyPath] = {
            name: copyPath.split('/').pop(),
            path: copyPath,
            content: original.content,
            type: 'file'
        };

        if (typeof addLogLine === 'function') {
            addLogLine('SYS', `Duplicated ${fKey} → ${copyPath}`);
        }
        await fetchExplorerFiles();
        renderFileExplorer();
        await openFile(copyPath);
    } catch (err) {
        await showCustomAlert("Duplicate Failed", `Could not duplicate file: ${err.message}`);
    }
}

/* =================== BREADCRUMB & MINIMAP =================== */
function updateMinimap() { }
function updateMinimapViewport() { }

function updateBreadcrumb() {
    const proj = state.projects[state.activeProject];
    const container = document.getElementById('ideBreadcrumb');
    if (!container) return;

    if (!proj || !proj.activeFile) {
        container.innerHTML = '<span style="opacity:0.5;">No file open</span>';
        return;
    }

    const projName = proj.name;
    const parts = proj.activeFile.split('/');

    let html = `<span>${projName}</span>`;

    parts.forEach((part, i) => {
        html += `<span class="bc-sep">›</span>`;
        if (i === parts.length - 1) {
            html += `<span class="bc-active">${part}</span>`;
        } else {
            html += `<span>${part}</span>`;
        }
    });

    container.innerHTML = html;
}

/* =================== SEARCH & COLLAPSE =================== */
function filterFiles(query) {
    const container = document.getElementById('fileListContainer');
    if (!container) return;
    const items = container.querySelectorAll('.file-item, .folder-row');
    const lowerQuery = query.toLowerCase();

    if (!query) {
        items.forEach(item => item.style.display = '');
        container.querySelectorAll('.folder-children-container').forEach(c => c.style.display = '');
        return;
    }

    items.forEach(item => {
        const nameEl = item.querySelector('.file-name, .folder-name');
        if (nameEl) {
            const name = nameEl.textContent.toLowerCase();
            item.style.display = name.includes(lowerQuery) ? '' : 'none';
        }
    });
    // Show all folder containers during search
    container.querySelectorAll('.folder-children-container').forEach(c => c.style.display = '');
}

function collapseAllFolders() {
    const proj = state.projects[state.activeProject];
    if (!proj) return;
    Object.keys(proj.files).forEach(key => {
        if (proj.files[key].type === 'folder') {
            proj.files[key].isOpen = false;
        }
    });
    renderFileExplorer();
}

function switchActivityPanel(panel) {
    document.querySelectorAll('.activity-btn').forEach(btn => btn.classList.remove('active'));
    if (event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }
}
