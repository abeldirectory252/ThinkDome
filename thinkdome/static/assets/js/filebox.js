/**
 * filebox.js — ThinkDome AI Agent Filebox Browser & Management Console
 *
 * Independent, card-based Filebox management interface:
 * - Standalone page (#page-filebox) with independent card architecture
 * - Internal menu sidebar with category filters & dynamic file counts
 * - Interactive hierarchical file tree with live query filtering
 * - Code & Markdown editor with line numbers, syntax preview, Ctrl+S save
 * - Multi-user perspective with tenant/user scoping & admin user switching
 * - SQLite FTS5 full-text search with keyword snippets
 * - Audit trail modal and legacy migration wizard
 */

(function () {
    'use strict';

    // State
    const fbState = {
        initialized: false,
        currentUser: null,
        currentOwner: null,
        tenant: 'default',
        isAdmin: false,
        availableUsers: [],
        treeData: null,
        activePath: null,
        activeCategory: 'all',
        fileContent: '',
        originalContent: '',
        isDirty: false,
        activeTab: 'edit', // 'edit' or 'preview'
        searchQuery: '',
        searchResults: [],
        statusInfo: null,
        treeFilterText: '',
    };

    function getToken() {
        return localStorage.getItem('thinkdome_token') || '';
    }

    // ── Entry Point ─────────────────────────────────────────────────────────

    async function init() {
        const page = document.getElementById('page-filebox');
        if (!page) return;
        setupUI();
        await loadUserData();
        await refreshAll();
        fbState.initialized = true;
    }

    async function loadUserData() {
        try {
            const res = await window.API.fileboxGetUsers(getToken());
            if (res.data) {
                fbState.currentUser = res.data.current_user;
                fbState.tenant = res.data.tenant;
                fbState.isAdmin = res.data.is_admin;
                fbState.availableUsers = res.data.users || [];
                if (!fbState.currentOwner) {
                    fbState.currentOwner = fbState.currentUser;
                }
                renderUserSelector();
                updateMetricCards();
            }
        } catch (e) {
            console.error('Failed to load user info for Filebox:', e);
        }
    }

    function renderUserSelector() {
        const selContainer = document.getElementById('fbUserSelectorContainer');
        if (!selContainer) return;

        if (!fbState.isAdmin || fbState.availableUsers.length <= 1) {
            selContainer.innerHTML = `
                <div style="display:inline-flex;align-items:center;gap:6px;padding:5px 10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;">
                    <span style="color:var(--fg-muted);">Agent:</span>
                    <strong style="color:var(--fg);">${escapeHtml(fbState.currentOwner || 'default')}</strong>
                    <span style="color:var(--fg-muted);font-size:11px;">(${escapeHtml(fbState.tenant)})</span>
                </div>
            `;
            return;
        }

        let optionsHtml = fbState.availableUsers.map(u => {
            const selected = u.username === fbState.currentOwner ? 'selected' : '';
            return `<option value="${escapeHtml(u.username)}" ${selected}>${escapeHtml(u.username)} ${u.is_current ? '(Current)' : ''}</option>`;
        }).join('');

        selContainer.innerHTML = `
            <div style="display:inline-flex;align-items:center;gap:6px;font-size:12px;">
                <label for="fbUserSelect" style="color:var(--fg-muted);font-weight:600;">Agent / User:</label>
                <select id="fbUserSelect" class="form-input" style="padding:4px 8px;height:30px;font-size:12px;font-weight:600;min-width:140px;">
                    ${optionsHtml}
                </select>
            </div>
        `;

        const selectEl = document.getElementById('fbUserSelect');
        if (selectEl) {
            selectEl.addEventListener('change', async (e) => {
                fbState.currentOwner = e.target.value;
                fbState.activePath = null;
                fbState.isDirty = false;
                await refreshAll();
            });
        }
    }

    async function refreshAll() {
        showLoading(true);
        try {
            await Promise.all([
                loadTree(),
                loadStatus(),
            ]);
            if (fbState.activePath) {
                await openFile(fbState.activePath);
            } else {
                renderEmptyCard();
            }
        } finally {
            showLoading(false);
        }
    }

    // ── Tree & Navigation ───────────────────────────────────────────────────

    async function loadTree() {
        try {
            const res = await window.API.fileboxGetTree('', 6, fbState.currentOwner, getToken());
            if (res.data) {
                fbState.treeData = res.data;
                updateCategoryCounts();
                renderTree();
            } else if (res.error) {
                renderEmptyTree(res.error);
            }
        } catch (e) {
            renderEmptyTree(e.message);
        }
    }

    async function loadStatus() {
        try {
            const res = await window.API.fileboxGetStatus(fbState.currentOwner, getToken());
            if (res.data) {
                fbState.statusInfo = res.data;
                updateMetricCards();
            }
        } catch (e) {
            console.warn('Could not load status:', e);
        }
    }

    function countFilesInNode(node) {
        if (!node) return 0;
        if (node.type !== 'directory') return 1;
        let count = 0;
        if (node.children) {
            node.children.forEach(c => {
                count += countFilesInNode(c);
            });
        }
        return count;
    }

    function updateCategoryCounts() {
        if (!fbState.treeData || !fbState.treeData.children) return;

        let total = 0;
        const categoryCounts = {};

        fbState.treeData.children.forEach(child => {
            const count = countFilesInNode(child);
            categoryCounts[child.name] = count;
            total += count;
        });

        const badgeAll = document.getElementById('fbNavBadge-all');
        if (badgeAll) badgeAll.textContent = total;

        const categories = ['memory', 'skills', 'knowledge', 'workspace', 'state', 'config', 'logs', 'identity'];
        categories.forEach(cat => {
            const badge = document.getElementById(`fbNavBadge-${cat}`);
            if (badge) {
                badge.textContent = categoryCounts[cat] || 0;
            }
        });
    }

    function updateMetricCards() {
        const totalEl = document.getElementById('fbMetricTotalFiles');
        const sizeEl = document.getElementById('fbMetricStorageSize');
        const quotaEl = document.getElementById('fbMetricStorageQuota');
        const barEl = document.getElementById('fbStorageBar');
        const ownerEl = document.getElementById('fbMetricCurrentOwner');
        const tenantEl = document.getElementById('fbMetricTenantScope');
        const indexEl = document.getElementById('fbMetricIndexStatus');

        if (ownerEl) ownerEl.textContent = fbState.currentOwner || 'agent';
        if (tenantEl) tenantEl.textContent = `Tenant: ${fbState.tenant}`;

        if (!fbState.statusInfo) return;
        const s = fbState.statusInfo;
        const sizeKb = (s.total_size / 1024).toFixed(1);
        const sizeMb = (s.total_size / (1024 * 1024)).toFixed(2);
        const displaySize = s.total_size > 1048576 ? `${sizeMb} MB` : `${sizeKb} KB`;

        if (totalEl) totalEl.textContent = s.total_files;
        if (sizeEl) sizeEl.textContent = displaySize;

        const maxBytes = 1000 * 1024 * 1024; // 1GB quota
        const pct = Math.min(100, Math.max(1, ((s.total_size / maxBytes) * 100))).toFixed(1);
        if (quotaEl) quotaEl.textContent = `${pct}% of 1.0 GB storage`;
        if (barEl) barEl.style.width = `${pct}%`;

        if (indexEl) {
            indexEl.innerHTML = s.valid ? '✓ Verified FTS5' : '⚠ Re-index required';
            indexEl.style.color = s.valid ? 'var(--success)' : 'var(--warn)';
        }
    }

    function renderTree() {
        const treeEl = document.getElementById('fbTreeContent');
        if (!treeEl) return;
        if (!fbState.treeData || !fbState.treeData.children) {
            treeEl.innerHTML = '<div style="padding:16px;color:var(--fg-muted);font-size:12px;text-align:center;">No files found. Click "Initialize" to bootstrap.</div>';
            return;
        }

        let rootChildren = fbState.treeData.children || [];
        if (fbState.activeCategory !== 'all') {
            rootChildren = rootChildren.filter(c => c.name === fbState.activeCategory);
        }

        // Apply filter text if any
        const q = (fbState.treeFilterText || '').trim().toLowerCase();

        let html = '';
        rootChildren.forEach(child => {
            html += renderTreeNode(child, 0, q);
        });

        if (!html.trim()) {
            treeEl.innerHTML = '<div style="padding:16px;color:var(--fg-muted);font-size:12px;text-align:center;">No matching files in this category.</div>';
        } else {
            treeEl.innerHTML = html;
        }

        attachTreeListeners();
    }

    function renderTreeNode(node, level, filterQuery) {
        const isDir = node.type === 'directory';

        // Check if node or children match filterQuery
        if (filterQuery) {
            const matchesSelf = node.name.toLowerCase().includes(filterQuery) || node.path.toLowerCase().includes(filterQuery);
            const matchesChild = isDir && hasMatchingChild(node, filterQuery);
            if (!matchesSelf && !matchesChild) return '';
        }

        const pad = level * 14 + 6;
        const isSelected = fbState.activePath === node.path;
        const selClass = isSelected ? 'active' : '';
        const icon = getFileIcon(node);
        const hasChildren = isDir && node.children && node.children.length > 0;
        const isExpanded = filterQuery || level < 1 || isSelected;

        let html = `
            <div class="fb-tree-node">
                <div class="fb-tree-row ${selClass}" data-path="${escapeHtml(node.path)}" data-type="${node.type}" style="padding-left:${pad}px;">
                    <span class="fb-tree-expander ${hasChildren ? (isExpanded ? 'expanded' : '') : 'empty'}" data-path="${escapeHtml(node.path)}">
                        ▶
                    </span>
                    <span class="fb-tree-icon">${icon}</span>
                    <span class="fb-tree-label" title="${escapeHtml(node.name)}">${escapeHtml(node.name)}</span>
                    ${!isDir && node.size !== undefined ? `<span class="fb-tree-size">${formatBytes(node.size)}</span>` : ''}
                    <div class="fb-tree-actions">
                        ${!isDir ? `
                            <button class="fb-tree-action-btn btn-action-dl" title="Download" data-path="${escapeHtml(node.path)}">⬇</button>
                        ` : `
                            <button class="fb-tree-action-btn btn-action-add" title="New file here" data-path="${escapeHtml(node.path)}">+</button>
                        `}
                        <button class="fb-tree-action-btn btn-action-ren" title="Rename" data-path="${escapeHtml(node.path)}">✏</button>
                        <button class="fb-tree-action-btn btn-action-del" title="Delete" style="color:var(--danger);" data-path="${escapeHtml(node.path)}">🗑</button>
                    </div>
                </div>
        `;

        if (hasChildren) {
            const safeId = node.path.replace(/[^a-zA-Z0-9]/g, '_');
            const displayStyle = isExpanded ? 'block' : 'none';
            html += `<div class="fb-tree-children" id="children-${safeId}" style="display:${displayStyle};">`;
            node.children.forEach(child => {
                html += renderTreeNode(child, level + 1, filterQuery);
            });
            html += `</div>`;
        }

        html += `</div>`;
        return html;
    }

    function hasMatchingChild(node, query) {
        if (!node.children) return false;
        return node.children.some(c => {
            if (c.name.toLowerCase().includes(query) || c.path.toLowerCase().includes(query)) return true;
            if (c.type === 'directory') return hasMatchingChild(c, query);
            return false;
        });
    }

    function attachTreeListeners() {
        const treeEl = document.getElementById('fbTreeContent');
        if (!treeEl) return;

        // Node click
        treeEl.querySelectorAll('.fb-tree-row').forEach(row => {
            row.addEventListener('click', async (e) => {
                // If action button was clicked, don't trigger select
                if (e.target.closest('.fb-tree-actions')) return;

                const path = row.dataset.path;
                const type = row.dataset.type;

                if (type === 'directory') {
                    toggleFolder(path);
                    return;
                }

                // File clicked
                if (fbState.isDirty) {
                    if (!confirm('You have unsaved modifications in the active file. Discard and switch?')) {
                        return;
                    }
                }
                await openFile(path);
            });
        });

        // Expander click
        treeEl.querySelectorAll('.fb-tree-expander').forEach(exp => {
            exp.addEventListener('click', (e) => {
                e.stopPropagation();
                const path = exp.dataset.path;
                toggleFolder(path);
            });
        });

        // Hover action buttons
        treeEl.querySelectorAll('.btn-action-dl').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                downloadFile(btn.dataset.path);
            });
        });

        treeEl.querySelectorAll('.btn-action-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                fbState.activePath = btn.dataset.path;
                openNewFileModal();
            });
        });

        treeEl.querySelectorAll('.btn-action-ren').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openMoveModal(btn.dataset.path);
            });
        });

        treeEl.querySelectorAll('.btn-action-del').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                confirmDeleteFile(btn.dataset.path);
            });
        });
    }

    function toggleFolder(path) {
        const safeId = path.replace(/[^a-zA-Z0-9]/g, '_');
        const childrenEl = document.getElementById(`children-${safeId}`);
        const expander = document.querySelector(`.fb-tree-expander[data-path="${path}"]`);
        if (childrenEl) {
            const isHidden = childrenEl.style.display === 'none';
            childrenEl.style.display = isHidden ? 'block' : 'none';
            if (expander) {
                expander.classList.toggle('expanded', isHidden);
            }
        }
    }

    function renderEmptyTree(msg) {
        const treeEl = document.getElementById('fbTreeContent');
        if (!treeEl) return;
        treeEl.innerHTML = `
            <div style="padding:24px;text-align:center;color:var(--fg-muted);font-size:12.5px;">
                <p style="margin-bottom:12px;">${escapeHtml(msg || 'Filebox filesystem is uninitialized.')}</p>
                <button class="btn btn-primary btn-sm" id="btnFbInitRoot">Initialize Standard Filebox</button>
            </div>
        `;
        const btn = document.getElementById('btnFbInitRoot');
        if (btn) btn.addEventListener('click', initFileboxRoot);
    }

    // ── Open and Edit File ──────────────────────────────────────────────────

    async function openFile(path) {
        fbState.activePath = path;
        updateBreadcrumbs(path);
        highlightActiveTreeNode(path);

        showEditorLoading(true);
        try {
            const res = await window.API.fileboxReadFile(path, fbState.currentOwner, getToken());
            if (res.data) {
                fbState.fileContent = res.data.content !== undefined ? res.data.content : '';
                fbState.originalContent = fbState.fileContent;
                fbState.isDirty = false;
                renderEditor(res.data);
            } else {
                showToast(`Failed to read file: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Error reading file: ${e.message}`, 'error');
        } finally {
            showEditorLoading(false);
        }
    }

    function renderEditor(fileData) {
        const viewerContainer = document.getElementById('fbCardViewer');
        if (!viewerContainer) return;

        const path = fileData.path;
        const isMarkdown = path.endsWith('.md') || path.endsWith('.markdown');
        const isReadOnly = path.startsWith('identity/') || path === 'config/permissions.yaml' || path === 'filebox.yaml';
        const isAppendOnly = path.startsWith('logs/');
        const isBinary = fileData.encoding === 'base64';

        let permBadge = '<span class="fb-viewer-meta-badge" style="color:var(--success);">Read-Write</span>';
        if (isReadOnly) {
            permBadge = '<span class="fb-viewer-meta-badge" style="color:var(--danger);">Read-Only</span>';
        } else if (isAppendOnly) {
            permBadge = '<span class="fb-viewer-meta-badge" style="color:var(--warn);">Append-Only</span>';
        }

        const linesCount = fbState.fileContent.split('\n').length;
        const sizeFormatted = formatBytes(fileData.size || fbState.fileContent.length);

        viewerContainer.innerHTML = `
            <!-- Viewer Head Toolbar -->
            <div class="fb-viewer-head">
                <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;">
                    <div class="fb-viewer-path" id="fbBreadcrumbs">
                        ${renderBreadcrumbsHtml(path)}
                    </div>
                    ${permBadge}
                    <span class="fb-viewer-meta-badge">${sizeFormatted}</span>
                </div>

                <div style="display:flex;align-items:center;gap:10px;">
                    ${isMarkdown ? `
                        <div class="fb-viewer-tabs">
                            <button class="fb-view-tab ${fbState.activeTab === 'edit' ? 'active' : ''}" id="fbBtnTabEdit">
                                📝 Editor
                            </button>
                            <button class="fb-view-tab ${fbState.activeTab === 'preview' ? 'active' : ''}" id="fbBtnTabPreview">
                                👁️ Preview
                            </button>
                        </div>
                    ` : ''}

                    <div class="fb-viewer-actions">
                        <button class="btn btn-ghost btn-sm" id="fbBtnDownload" title="Download file to computer">
                            ⬇ Download
                        </button>
                        <button class="btn btn-ghost btn-sm" id="fbBtnMove" title="Rename or Move">
                            ✏ Rename
                        </button>
                        <button class="btn btn-ghost btn-sm" id="fbBtnDelete" style="color:var(--danger);" title="Delete file">
                            🗑 Delete
                        </button>
                        <button class="btn btn-primary btn-sm" id="fbBtnSave" ${isReadOnly || isBinary ? 'disabled' : ''} title="Save changes (Ctrl+S)">
                            💾 Save File
                        </button>
                    </div>
                </div>
            </div>

            <!-- Viewer Body (Editor or Preview) -->
            ${isBinary ? `
                <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px;color:var(--fg-muted);">
                    <div style="font-size:48px;margin-bottom:12px;">🖼️</div>
                    <h3 style="font-size:16px;color:var(--fg);margin-bottom:6px;">Binary File (${sizeFormatted})</h3>
                    <p style="font-size:13px;max-width:380px;text-align:center;margin-bottom:16px;">
                        This file is encoded as binary data and cannot be displayed in the text editor.
                    </p>
                    <a href="/v1/filebox/browse/raw?path=${encodeURIComponent(path)}${fbState.currentOwner ? '&owner=' + encodeURIComponent(fbState.currentOwner) : ''}" download class="btn btn-primary btn-sm">Download Raw Binary File</a>
                </div>
            ` : `
                <div class="fb-editor-pane" id="fbEditPane" style="display:${fbState.activeTab === 'edit' ? 'flex' : 'none'};">
                    <div class="fb-editor-wrapper">
                        <div class="fb-line-numbers" id="fbLineNumbers"></div>
                        <textarea id="fbCodeTextarea" class="fb-code-editor" spellcheck="false" ${isReadOnly ? 'readonly' : ''}>${escapeHtml(fbState.fileContent)}</textarea>
                    </div>
                    <div class="fb-editor-footer">
                        <div style="display:flex;align-items:center;gap:12px;">
                            <span class="fb-dirty-pill ${fbState.isDirty ? 'dirty' : 'clean'}" id="fbDirtyIndicator">
                                ${fbState.isDirty ? '● Unsaved modifications' : '✓ All changes saved'}
                            </span>
                            <span style="color:var(--border-strong);">|</span>
                            <span id="fbLineColStatus">Ln 1, Col 1</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:12px;">
                            <span id="fbCharCountStatus">${linesCount} lines, ${fbState.fileContent.length} chars</span>
                            <span style="color:var(--border-strong);">|</span>
                            <span>${fileData.encoding || 'UTF-8'}</span>
                        </div>
                    </div>
                </div>

                <div class="fb-preview-pane" id="fbPreviewPane" style="display:${fbState.activeTab === 'preview' ? 'block' : 'none'};">
                    ${renderMarkdown(fbState.fileContent)}
                </div>
            `}
        `;

        updateLineNumbers();
        attachEditorListeners(path);
    }

    function renderEmptyCard() {
        const viewerContainer = document.getElementById('fbCardViewer');
        if (!viewerContainer) return;

        viewerContainer.innerHTML = `
            <div class="fb-zero-card">
                <div class="fb-zero-icon">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>
                        <path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>
                    </svg>
                </div>
                <h3>AI Agent Filebox Workspace</h3>
                <p>
                    Select any file from the explorer on the left to read or edit its contents, or use one of the standard templates below to create new agent artifacts.
                </p>

                <div class="fb-templates-grid">
                    <div class="fb-template-card" id="btnTplMemory">
                        <span style="font-size:20px;">🧠</span>
                        <strong>New Memory Topic</strong>
                        <small>Create semantic topic memory file in memory/</small>
                    </div>
                    <div class="fb-template-card" id="btnTplSkill">
                        <span style="font-size:20px;">⚡</span>
                        <strong>New Agent Skill</strong>
                        <small>Create executable tool instructions SKILL.md in skills/</small>
                    </div>
                    <div class="fb-template-card" id="btnTplProject">
                        <span style="font-size:20px;">💼</span>
                        <strong>Workspace Project</strong>
                        <small>Create project workspace documentation in workspace/</small>
                    </div>
                    <div class="fb-template-card" id="btnTplUpload">
                        <span style="font-size:20px;">📁</span>
                        <strong>Upload Resource</strong>
                        <small>Upload local markdown, code, or binary asset</small>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('btnTplMemory')?.addEventListener('click', () => {
            document.getElementById('fbNewFilePath').value = 'memory/new_topic.md';
            document.getElementById('fbNewFileTemplate').value = 'memory';
            document.getElementById('fbNewFileModal').classList.add('active');
        });

        document.getElementById('btnTplSkill')?.addEventListener('click', () => {
            document.getElementById('fbNewFilePath').value = 'skills/custom_skill/SKILL.md';
            document.getElementById('fbNewFileTemplate').value = 'skill';
            document.getElementById('fbNewFileModal').classList.add('active');
        });

        document.getElementById('btnTplProject')?.addEventListener('click', () => {
            document.getElementById('fbNewFilePath').value = 'workspace/projects/new_project/PROJECT.md';
            document.getElementById('fbNewFileTemplate').value = 'project';
            document.getElementById('fbNewFileModal').classList.add('active');
        });

        document.getElementById('btnTplUpload')?.addEventListener('click', () => {
            document.getElementById('fbUploadInput')?.click();
        });
    }

    function renderBreadcrumbsHtml(path) {
        const parts = path.split('/');
        let cur = '';
        let html = '<span class="fb-viewer-path-segment" style="cursor:pointer;" onclick="window.FileboxUI.refresh()">filebox</span>';
        parts.forEach((p, idx) => {
            cur += (idx === 0 ? '' : '/') + p;
            const isLast = idx === parts.length - 1;
            html += ` <span style="color:var(--fg-subtle);">/</span> `;
            if (isLast) {
                html += `<span class="fb-viewer-path-segment active">${escapeHtml(p)}</span>`;
            } else {
                html += `<span class="fb-viewer-path-segment">${escapeHtml(p)}</span>`;
            }
        });
        return html;
    }

    function updateLineNumbers() {
        const lineNums = document.getElementById('fbLineNumbers');
        const textarea = document.getElementById('fbCodeTextarea');
        if (!lineNums || !textarea) return;
        const lines = textarea.value.split('\n').length;
        let numbers = '';
        for (let i = 1; i <= lines; i++) {
            numbers += i + '\n';
        }
        lineNums.textContent = numbers;
    }

    function attachEditorListeners(path) {
        const textarea = document.getElementById('fbCodeTextarea');
        const lineNums = document.getElementById('fbLineNumbers');
        const dirtyPill = document.getElementById('fbDirtyIndicator');
        const lineColStatus = document.getElementById('fbLineColStatus');
        const charCountStatus = document.getElementById('fbCharCountStatus');

        if (textarea) {
            // Scroll sync
            textarea.addEventListener('scroll', () => {
                if (lineNums) lineNums.scrollTop = textarea.scrollTop;
            });

            // Input tracking
            textarea.addEventListener('input', () => {
                fbState.fileContent = textarea.value;
                fbState.isDirty = fbState.fileContent !== fbState.originalContent;
                if (dirtyPill) {
                    dirtyPill.className = `fb-dirty-pill ${fbState.isDirty ? 'dirty' : 'clean'}`;
                    dirtyPill.textContent = fbState.isDirty ? '● Unsaved modifications' : '✓ All changes saved';
                }
                updateLineNumbers();
                if (charCountStatus) {
                    const lines = textarea.value.split('\n').length;
                    charCountStatus.textContent = `${lines} lines, ${textarea.value.length} chars`;
                }
                const prevPane = document.getElementById('fbPreviewPane');
                if (prevPane && fbState.activeTab === 'preview') {
                    prevPane.innerHTML = renderMarkdown(fbState.fileContent);
                }
            });

            // Tab key indentation
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Tab') {
                    e.preventDefault();
                    const start = textarea.selectionStart;
                    const end = textarea.selectionEnd;
                    textarea.value = textarea.value.substring(0, start) + '    ' + textarea.value.substring(end);
                    textarea.selectionStart = textarea.selectionEnd = start + 4;
                    textarea.dispatchEvent(new Event('input'));
                } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    saveCurrentFile();
                }
            });

            // Cursor position
            const updateCursor = () => {
                const pos = textarea.selectionStart;
                const text = textarea.value.substring(0, pos);
                const lines = text.split('\n');
                const row = lines.length;
                const col = lines[lines.length - 1].length + 1;
                if (lineColStatus) lineColStatus.textContent = `Ln ${row}, Col ${col}`;
            };
            textarea.addEventListener('keyup', updateCursor);
            textarea.addEventListener('click', updateCursor);
        }

        // Save button
        document.getElementById('fbBtnSave')?.addEventListener('click', saveCurrentFile);

        // Tab switcher
        const btnEdit = document.getElementById('fbBtnTabEdit');
        const btnPrev = document.getElementById('fbBtnTabPreview');
        if (btnEdit && btnPrev) {
            btnEdit.addEventListener('click', () => {
                fbState.activeTab = 'edit';
                btnEdit.classList.add('active');
                btnPrev.classList.remove('active');
                document.getElementById('fbEditPane').style.display = 'flex';
                document.getElementById('fbPreviewPane').style.display = 'none';
            });
            btnPrev.addEventListener('click', () => {
                fbState.activeTab = 'preview';
                btnPrev.classList.add('active');
                btnEdit.classList.remove('active');
                document.getElementById('fbEditPane').style.display = 'none';
                const previewPane = document.getElementById('fbPreviewPane');
                previewPane.style.display = 'block';
                previewPane.innerHTML = renderMarkdown(fbState.fileContent);
            });
        }

        // Actions
        document.getElementById('fbBtnDownload')?.addEventListener('click', () => downloadFile(path));
        document.getElementById('fbBtnMove')?.addEventListener('click', () => openMoveModal(path));
        document.getElementById('fbBtnDelete')?.addEventListener('click', () => confirmDeleteFile(path));
    }

    async function saveCurrentFile() {
        if (!fbState.activePath) return;
        const btnSave = document.getElementById('fbBtnSave');
        if (btnSave) btnSave.disabled = true;

        try {
            const res = await window.API.fileboxWriteFile(
                fbState.activePath,
                fbState.fileContent,
                'Web UI edit',
                fbState.currentOwner,
                getToken()
            );
            if (res.data) {
                fbState.originalContent = fbState.fileContent;
                fbState.isDirty = false;
                const dirtyPill = document.getElementById('fbDirtyIndicator');
                if (dirtyPill) {
                    dirtyPill.className = 'fb-dirty-pill clean';
                    dirtyPill.textContent = '✓ All changes saved';
                }
                showToast('File saved successfully!', 'success');
                await loadStatus();
            } else {
                showToast(`Save failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Save error: ${e.message}`, 'error');
        } finally {
            if (btnSave) btnSave.disabled = false;
        }
    }

    function downloadFile(path) {
        if (!path) return;
        const blob = new Blob([fbState.fileContent], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = path.split('/').pop();
        a.click();
        URL.revokeObjectURL(url);
    }

    // ── Modals & Dialogs ────────────────────────────────────────────────────

    function openNewFileModal() {
        const modal = document.getElementById('fbNewFileModal');
        if (!modal) return;
        document.getElementById('fbNewFilePath').value = fbState.activePath ? getParentDir(fbState.activePath) + '/' : 'workspace/projects/';
        document.getElementById('fbNewFileTemplate').value = 'empty';
        modal.classList.add('active');
    }

    function openNewFolderModal() {
        const modal = document.getElementById('fbNewFolderModal');
        if (!modal) return;
        document.getElementById('fbNewFolderPath').value = fbState.activePath ? getParentDir(fbState.activePath) + '/' : 'workspace/projects/';
        modal.classList.add('active');
    }

    function openMoveModal(srcPath) {
        const modal = document.getElementById('fbMoveModal');
        if (!modal) return;
        document.getElementById('fbMoveSrc').value = srcPath;
        document.getElementById('fbMoveDst').value = srcPath;
        modal.classList.add('active');
    }

    function openMigrateModal() {
        const modal = document.getElementById('fbMigrateModal');
        if (!modal) return;
        modal.classList.add('active');
    }

    async function confirmDeleteFile(path) {
        if (!confirm(`Are you sure you want to permanently delete "${path}"?`)) {
            return;
        }
        try {
            const res = await window.API.fileboxDelete(path, 'Web UI delete', fbState.currentOwner, getToken());
            if (res.data) {
                showToast(`Deleted ${path}`, 'success');
                fbState.activePath = null;
                fbState.isDirty = false;
                renderEmptyCard();
                await refreshAll();
            } else {
                showToast(`Delete failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Delete error: ${e.message}`, 'error');
        }
    }

    async function initFileboxRoot() {
        try {
            const res = await window.API.fileboxInit(fbState.currentOwner, getToken());
            if (res.data) {
                showToast('Standard Filebox filesystem initialized successfully!', 'success');
                await refreshAll();
            } else {
                showToast(`Init failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Init error: ${e.message}`, 'error');
        }
    }

    async function triggerIndexRebuild() {
        showToast('Building SQLite FTS5 search index...', 'info');
        try {
            const res = await window.API.fileboxIndex(true, fbState.currentOwner, getToken());
            if (res.data) {
                const r = res.data.result;
                showToast(`Search index updated (${r.indexed} indexed / ${r.total} total files)`, 'success');
                await loadStatus();
            } else {
                showToast(`Indexing failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Index error: ${e.message}`, 'error');
        }
    }

    // ── Fast Search ─────────────────────────────────────────────────────────

    async function executeSearch(query) {
        const panel = document.getElementById('fbSearchPanel');
        if (!panel) return;

        if (!query || !query.trim()) {
            fbState.searchQuery = '';
            fbState.searchResults = [];
            panel.style.display = 'none';
            return;
        }

        fbState.searchQuery = query.trim();
        panel.style.display = 'flex';
        const bodyEl = document.getElementById('fbSearchPanelBody');
        if (bodyEl) bodyEl.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--fg-muted);">Searching FTS5 index &amp; grep...</div>';

        try {
            const res = await window.API.fileboxSearch(fbState.searchQuery, '', 30, fbState.currentOwner, getToken());
            if (res.data && res.data.results) {
                fbState.searchResults = res.data.results;
                renderSearchResults();
            } else {
                if (bodyEl) bodyEl.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--fg-muted);">No matching files found.</div>';
            }
        } catch (e) {
            if (bodyEl) bodyEl.innerHTML = `<div style="padding:14px;font-size:12px;color:var(--danger);">Search error: ${escapeHtml(e.message)}</div>`;
        }
    }

    function renderSearchResults() {
        const bodyEl = document.getElementById('fbSearchPanelBody');
        const countEl = document.getElementById('fbSearchCount');
        if (!bodyEl) return;

        if (countEl) countEl.textContent = fbState.searchResults.length;

        if (!fbState.searchResults.length) {
            bodyEl.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--fg-muted);">No matching files found.</div>';
            return;
        }

        let html = '';
        fbState.searchResults.forEach(r => {
            let snippet = r.snippet || '';
            if (!snippet && r.matches && r.matches.length) {
                snippet = r.matches.map(m => `Line ${m.line}: ${escapeHtml(m.text)}`).join('<br>');
            }
            html += `
                <div class="fb-search-panel-item" data-path="${escapeHtml(r.path)}">
                    <div style="font-weight:600;font-size:12.5px;color:var(--fg);display:flex;align-items:center;gap:6px;">
                        <span style="color:var(--accent);font-size:10px;text-transform:uppercase;background:var(--surface-raised);padding:1px 6px;border-radius:4px;border:1px solid var(--border);">
                            ${escapeHtml(r.category || 'file')}
                        </span>
                        <span>${escapeHtml(r.path)}</span>
                    </div>
                    ${snippet ? `<div class="fb-search-snippet" style="font-size:11.5px;color:var(--fg-muted);margin-top:4px;line-height:1.4;">${snippet}</div>` : ''}
                </div>
            `;
        });

        bodyEl.innerHTML = html;

        bodyEl.querySelectorAll('.fb-search-panel-item').forEach(item => {
            item.addEventListener('click', async () => {
                await openFile(item.dataset.path);
                document.getElementById('fbSearchPanel').style.display = 'none';
            });
        });
    }

    // ── Audit Trail ─────────────────────────────────────────────────────────

    async function openAuditModal() {
        const modal = document.getElementById('fbAuditModal');
        if (!modal) return;
        modal.classList.add('active');
        const listEl = document.getElementById('fbAuditList');
        listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg-muted);">Loading audit stream...</div>';

        try {
            const res = await window.API.fileboxGetAudit(50, fbState.currentOwner, getToken());
            if (res.data && res.data.events) {
                renderAuditEvents(res.data.events);
            }
        } catch (e) {
            listEl.innerHTML = `<div style="padding:20px;color:var(--danger);">Error loading audit: ${escapeHtml(e.message)}</div>`;
        }
    }

    function renderAuditEvents(events) {
        const listEl = document.getElementById('fbAuditList');
        if (!listEl) return;
        if (!events.length) {
            listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg-muted);">No audit events recorded yet.</div>';
            return;
        }

        let html = '<table style="width:100%;font-size:12px;border-collapse:collapse;">';
        html += `
            <thead>
                <tr style="text-align:left;border-bottom:1px solid var(--border);color:var(--fg-muted);background:var(--surface-raised);">
                    <th style="padding:10px 8px;">Time</th>
                    <th style="padding:10px 8px;">Action</th>
                    <th style="padding:10px 8px;">Actor</th>
                    <th style="padding:10px 8px;">Target Path</th>
                    <th style="padding:10px 8px;">Reason / Details</th>
                </tr>
            </thead>
            <tbody>
        `;

        events.forEach(e => {
            const timeStr = new Date(e.timestamp).toLocaleTimeString();
            const actionColor = e.action === 'delete' ? 'var(--danger)' : e.action === 'write' ? 'var(--success)' : 'var(--fg)';
            html += `
                <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:8px;white-space:nowrap;color:var(--fg-muted);">${escapeHtml(timeStr)}</td>
                    <td style="padding:8px;font-weight:700;color:${actionColor};text-transform:uppercase;">${escapeHtml(e.action)}</td>
                    <td style="padding:8px;font-weight:600;">${escapeHtml(e.actor)}</td>
                    <td style="padding:8px;font-family:var(--font-mono);font-size:11.5px;">${escapeHtml(e.path)}</td>
                    <td style="padding:8px;color:var(--fg-muted);">${escapeHtml(e.reason || '—')}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        listEl.innerHTML = html;
    }

    // ── Setup UI Layout ─────────────────────────────────────────────────────

    function setupUI() {
        const page = document.getElementById('page-filebox');
        if (!page || page.dataset.initialized) return;
        page.dataset.initialized = 'true';

        page.innerHTML = `
            <!-- Top Page Header Card -->
            <div class="fb-page-head">
                <div class="fb-page-title-group">
                    <span class="access-eyebrow">AI AGENT PERSISTENT FILESYSTEM</span>
                    <h1>Agent Filebox &amp; Workspace Files</h1>
                    <p>Independent persistent storage for AI agent memory, skills, workspace projects, and session checkpoints.</p>
                </div>
                <div class="fb-page-actions">
                    <div id="fbUserSelectorContainer"></div>
                    <button class="btn btn-primary" id="btnFbNewFile">+ New File</button>
                    <button class="btn btn-ghost" id="btnFbNewFolder">+ New Folder</button>
                    <button class="btn btn-ghost" id="btnFbUpload" title="Upload File">↑ Upload</button>
                    <input type="file" id="fbUploadInput" style="display:none;" />
                    <button class="btn btn-ghost" id="btnFbOpenSearch" title="Search all files">🔍 Search</button>
                    <button class="btn btn-ghost" id="btnFbAudit" title="View Audit Trail">🛡️ Audit</button>
                    <button class="btn btn-ghost" id="btnFbMigrate" title="Migrate Legacy Storage">Migrate</button>
                    <button class="btn btn-ghost" id="btnFbRefresh" title="Refresh files">↺ Refresh</button>
                </div>
            </div>

            <!-- 4 Metrics Summary Cards Strip -->
            <div class="fb-metrics-grid">
                <!-- Card 1: Total Artifacts -->
                <div class="fb-metric-card">
                    <div class="fb-metric-header">
                        <span>Total Artifacts</span>
                        <span>📦</span>
                    </div>
                    <div class="fb-metric-val" id="fbMetricTotalFiles">0</div>
                    <div class="fb-metric-sub">Active files across categories</div>
                </div>

                <!-- Card 2: Storage Utilization -->
                <div class="fb-metric-card">
                    <div class="fb-metric-header">
                        <span>Storage Utilization</span>
                        <span>💾</span>
                    </div>
                    <div class="fb-metric-val" id="fbMetricStorageSize">0 KB</div>
                    <div class="fb-metric-sub" id="fbMetricStorageQuota">0% of 1.0 GB storage</div>
                    <div class="fb-usage-bar-bg">
                        <div class="fb-usage-bar-fill" id="fbStorageBar" style="width:1%;"></div>
                    </div>
                </div>

                <!-- Card 3: Agent / Scope -->
                <div class="fb-metric-card">
                    <div class="fb-metric-header">
                        <span>Agent Context</span>
                        <span>👤</span>
                    </div>
                    <div class="fb-metric-val" id="fbMetricCurrentOwner">agent</div>
                    <div class="fb-metric-sub" id="fbMetricTenantScope">Tenant: default</div>
                </div>

                <!-- Card 4: FTS5 Search Engine -->
                <div class="fb-metric-card">
                    <div class="fb-metric-header">
                        <span>Search Engine</span>
                        <span>⚡</span>
                    </div>
                    <div class="fb-metric-val" id="fbMetricIndexStatus" style="font-size:20px;">FTS5 Active</div>
                    <div class="fb-metric-sub" style="justify-content:space-between;">
                        <span>SQLite Full-Text</span>
                        <button class="btn btn-sm btn-ghost" id="btnFbReindex" style="padding:1px 6px;font-size:11px;">↺ Re-index</button>
                    </div>
                </div>
            </div>

            <!-- Main Filebox Card with Internal Menu Sidebar -->
            <div class="fb-main-card">
                <!-- Left Menu Sidebar -->
                <div class="fb-card-sidebar">
                    <!-- Top Filter Search -->
                    <div class="fb-sidebar-top">
                        <div class="fb-filter-input-wrap">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                            <input type="text" id="fbTreeFilterInput" class="fb-filter-input" placeholder="Filter files in tree..." autocomplete="off" />
                        </div>
                    </div>

                    <!-- Category Menu Navigation -->
                    <div class="fb-sidebar-nav-title">Categories</div>
                    <div class="fb-sidebar-nav-list">
                        <button class="fb-nav-btn active" data-cat="all">
                            <span class="fb-nav-ico">📂</span>
                            <span>All Files</span>
                            <span class="fb-nav-badge" id="fbNavBadge-all">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="memory">
                            <span class="fb-nav-ico">🧠</span>
                            <span>Memory</span>
                            <span class="fb-nav-badge" id="fbNavBadge-memory">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="skills">
                            <span class="fb-nav-ico">⚡</span>
                            <span>Skills</span>
                            <span class="fb-nav-badge" id="fbNavBadge-skills">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="knowledge">
                            <span class="fb-nav-ico">📚</span>
                            <span>Knowledge</span>
                            <span class="fb-nav-badge" id="fbNavBadge-knowledge">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="workspace">
                            <span class="fb-nav-ico">💼</span>
                            <span>Workspace</span>
                            <span class="fb-nav-badge" id="fbNavBadge-workspace">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="state">
                            <span class="fb-nav-ico">⏱️</span>
                            <span>State</span>
                            <span class="fb-nav-badge" id="fbNavBadge-state">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="config">
                            <span class="fb-nav-ico">⚙️</span>
                            <span>Config</span>
                            <span class="fb-nav-badge" id="fbNavBadge-config">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="logs">
                            <span class="fb-nav-ico">📋</span>
                            <span>Logs</span>
                            <span class="fb-nav-badge" id="fbNavBadge-logs">0</span>
                        </button>
                        <button class="fb-nav-btn" data-cat="identity">
                            <span class="fb-nav-ico">🆔</span>
                            <span>Identity</span>
                            <span class="fb-nav-badge" id="fbNavBadge-identity">0</span>
                        </button>
                    </div>

                    <!-- Directory Tree Explorer -->
                    <div class="fb-sidebar-tree-section">
                        <div class="fb-tree-section-header">
                            <span id="fbTreeSectionTitle">File Explorer</span>
                            <div class="fb-tree-actions-mini">
                                <button id="btnMiniNewFile" title="New File in active folder">+ File</button>
                                <button id="btnMiniNewFolder" title="New Folder">+ Dir</button>
                            </div>
                        </div>
                        <div id="fbTreeContent" class="fb-sidebar-tree">
                            <div style="padding:20px;text-align:center;color:var(--fg-muted);font-size:12px;">Loading filesystem tree...</div>
                        </div>
                    </div>
                </div>

                <!-- Right Card: File Viewer & Code Editor -->
                <div class="fb-card-viewer" id="fbCardViewer">
                    <!-- Populated dynamically: either renderEditor or renderEmptyCard -->
                </div>

                <!-- Floating Search Panel -->
                <div id="fbSearchPanel" class="fb-search-panel" style="display:none;">
                    <div class="fb-search-panel-head">
                        <span>SEARCH RESULTS (<span id="fbSearchCount">0</span>)</span>
                        <span style="cursor:pointer;" id="fbCloseSearchPanel">✕ Close</span>
                    </div>
                    <div class="fb-search-panel-body" id="fbSearchPanelBody"></div>
                </div>
            </div>

            <!-- MODALS -->
            ${renderModalsHtml()}
        `;

        attachGeneralListeners();
    }

    function renderModalsHtml() {
        return `
            <!-- New File Modal -->
            <div id="fbNewFileModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
                <div class="modal-card" style="max-width:480px;">
                    <div class="modal-header">
                        <h3>Create New File</h3>
                        <button class="close-modal-btn" onclick="document.getElementById('fbNewFileModal').classList.remove('active')">&times;</button>
                    </div>
                    <form id="fbNewFileForm">
                        <div class="modal-body" style="display:flex;flex-direction:column;gap:14px;">
                            <div class="field">
                                <label style="font-size:12px;font-weight:600;color:var(--fg-muted);">File Path *</label>
                                <input type="text" id="fbNewFilePath" class="form-input" required placeholder="e.g. workspace/projects/app.py" />
                            </div>
                            <div class="field">
                                <label style="font-size:12px;font-weight:600;color:var(--fg-muted);">Initial Template</label>
                                <select id="fbNewFileTemplate" class="form-input">
                                    <option value="empty">Empty File</option>
                                    <option value="memory">Semantic Memory Topic</option>
                                    <option value="skill">Agent Skill (SKILL.md)</option>
                                    <option value="project">Workspace Project (PROJECT.md)</option>
                                    <option value="note">Knowledge Note</option>
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-ghost" onclick="document.getElementById('fbNewFileModal').classList.remove('active')">Cancel</button>
                            <button type="submit" class="btn btn-primary">Create File</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- New Folder Modal -->
            <div id="fbNewFolderModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
                <div class="modal-card" style="max-width:440px;">
                    <div class="modal-header">
                        <h3>Create Directory</h3>
                        <button class="close-modal-btn" onclick="document.getElementById('fbNewFolderModal').classList.remove('active')">&times;</button>
                    </div>
                    <form id="fbNewFolderForm">
                        <div class="modal-body">
                            <div class="field">
                                <label style="font-size:12px;font-weight:600;color:var(--fg-muted);">Directory Path *</label>
                                <input type="text" id="fbNewFolderPath" class="form-input" required placeholder="e.g. workspace/projects/my-project" />
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-ghost" onclick="document.getElementById('fbNewFolderModal').classList.remove('active')">Cancel</button>
                            <button type="submit" class="btn btn-primary">Create</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- Move / Rename Modal -->
            <div id="fbMoveModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
                <div class="modal-card" style="max-width:480px;">
                    <div class="modal-header">
                        <h3>Rename or Move</h3>
                        <button class="close-modal-btn" onclick="document.getElementById('fbMoveModal').classList.remove('active')">&times;</button>
                    </div>
                    <form id="fbMoveForm">
                        <div class="modal-body" style="display:flex;flex-direction:column;gap:14px;">
                            <input type="hidden" id="fbMoveSrc" />
                            <div class="field">
                                <label style="font-size:12px;font-weight:600;color:var(--fg-muted);">New Destination Path *</label>
                                <input type="text" id="fbMoveDst" class="form-input" required />
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-ghost" onclick="document.getElementById('fbMoveModal').classList.remove('active')">Cancel</button>
                            <button type="submit" class="btn btn-primary">Save Destination</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- Migrate Modal -->
            <div id="fbMigrateModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
                <div class="modal-card" style="max-width:540px;">
                    <div class="modal-header">
                        <h3>Migrate Old Filebox Files</h3>
                        <button class="close-modal-btn" onclick="document.getElementById('fbMigrateModal').classList.remove('active')">&times;</button>
                    </div>
                    <form id="fbMigrateForm">
                        <div class="modal-body" style="display:flex;flex-direction:column;gap:14px;">
                            <p style="font-size:12.5px;color:var(--fg-muted);line-height:1.4;margin:0;">
                                Migrate legacy sandbox structures (flat memory.md, unindexed skills) or encrypted platform volumes (.box) into the standardized Filebox layout.
                            </p>
                            <div class="field">
                                <label style="font-size:12px;font-weight:600;color:var(--fg-muted);">Source Directory (Optional)</label>
                                <input type="text" id="fbMigrateSource" class="form-input" placeholder="e.g. /sandbox or leave empty for platform storage" />
                            </div>
                            <div style="display:flex;flex-direction:column;gap:8px;">
                                <label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;">
                                    <input type="checkbox" id="fbMigrateLegacyStorage" checked />
                                    Migrate legacy storage volume (.box containers)
                                </label>
                                <label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;">
                                    <input type="checkbox" id="fbMigrateDryRun" />
                                    Dry Run (Preview migration without modifying disk)
                                </label>
                            </div>
                            <div id="fbMigrateResult" style="display:none;padding:12px;background:var(--surface-raised);border-radius:var(--radius-sm);font-size:12px;max-height:200px;overflow-y:auto;"></div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-ghost" onclick="document.getElementById('fbMigrateModal').classList.remove('active')">Close</button>
                            <button type="submit" class="btn btn-primary" id="fbBtnDoMigrate">Execute Migration</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- Audit Modal -->
            <div id="fbAuditModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
                <div class="modal-card" style="max-width:760px;width:95%;">
                    <div class="modal-header">
                        <h3>Filebox Security &amp; Access Audit Trail</h3>
                        <button class="close-modal-btn" onclick="document.getElementById('fbAuditModal').classList.remove('active')">&times;</button>
                    </div>
                    <div class="modal-body" style="max-height:65vh;overflow-y:auto;padding:16px;">
                        <div id="fbAuditList"></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-ghost" onclick="document.getElementById('fbAuditModal').classList.remove('active')">Close</button>
                    </div>
                </div>
            </div>
        `;
    }

    function attachGeneralListeners() {
        // Category menu navigation in internal sidebar
        document.querySelectorAll('.fb-nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.fb-nav-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                fbState.activeCategory = btn.dataset.cat;
                const titleEl = document.getElementById('fbTreeSectionTitle');
                if (titleEl) {
                    titleEl.textContent = btn.dataset.cat === 'all' ? 'File Explorer' : `${btn.dataset.cat.toUpperCase()} Explorer`;
                }
                renderTree();
            });
        });

        // Tree filter input
        const filterInput = document.getElementById('fbTreeFilterInput');
        if (filterInput) {
            let filterDebounce = null;
            filterInput.addEventListener('input', (e) => {
                clearTimeout(filterDebounce);
                filterDebounce = setTimeout(() => {
                    fbState.treeFilterText = e.target.value;
                    renderTree();
                }, 150);
            });
        }

        // Top actions
        document.getElementById('btnFbRefresh')?.addEventListener('click', refreshAll);
        document.getElementById('btnFbReindex')?.addEventListener('click', triggerIndexRebuild);
        document.getElementById('btnFbAudit')?.addEventListener('click', openAuditModal);
        document.getElementById('btnFbMigrate')?.addEventListener('click', openMigrateModal);

        // Search trigger
        document.getElementById('btnFbOpenSearch')?.addEventListener('click', () => {
            const query = prompt('Enter text to search across all Filebox files (FTS5 & Grep):');
            if (query !== null) {
                executeSearch(query);
            }
        });
        document.getElementById('fbCloseSearchPanel')?.addEventListener('click', () => {
            document.getElementById('fbSearchPanel').style.display = 'none';
        });

        // New File & Folder buttons
        document.getElementById('btnFbNewFile')?.addEventListener('click', openNewFileModal);
        document.getElementById('btnFbNewFolder')?.addEventListener('click', openNewFolderModal);
        document.getElementById('btnMiniNewFile')?.addEventListener('click', openNewFileModal);
        document.getElementById('btnMiniNewFolder')?.addEventListener('click', openNewFolderModal);

        // Upload
        const uploadBtn = document.getElementById('btnFbUpload');
        const uploadInput = document.getElementById('fbUploadInput');
        if (uploadBtn && uploadInput) {
            uploadBtn.addEventListener('click', () => uploadInput.click());
            uploadInput.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                const parent = fbState.activePath ? getParentDir(fbState.activePath) : 'workspace/drafts';
                const destPath = `${parent}/${file.name}`.replace(/\/+/g, '/');

                const reader = new FileReader();
                reader.onload = async () => {
                    const base64 = reader.result.split(',')[1];
                    try {
                        const res = await window.API.fileboxWriteBinary(destPath, base64, 'Web upload', fbState.currentOwner, getToken());
                        if (res.data) {
                            showToast(`Uploaded ${file.name}`, 'success');
                            await refreshAll();
                            await openFile(destPath);
                        } else {
                            showToast(`Upload failed: ${res.error}`, 'error');
                        }
                    } catch (err) {
                        showToast(`Upload error: ${err.message}`, 'error');
                    }
                };
                reader.readAsDataURL(file);
                uploadInput.value = '';
            });
        }

        // New File Form
        document.getElementById('fbNewFileForm')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const path = document.getElementById('fbNewFilePath').value.trim();
            const tpl = document.getElementById('fbNewFileTemplate').value;
            let initialContent = '';

            if (tpl === 'memory') {
                initialContent = `# Memory: ${path.split('/').pop().replace('.md', '')}\n\n## [${new Date().toISOString().split('T')[0]}] Initial Memory\n<!-- id: mem-${Date.now().toString(36)} | importance: medium -->\n\nRecord key agent facts, context, or user preferences here.\n`;
            } else if (tpl === 'skill') {
                initialContent = `---\nname: ${path.split('/')[1] || 'new-skill'}\nversion: "1.0"\ndescription: Skill description\nenabled: true\ntags: [tool]\ntriggers: [action]\n---\n\n# Skill Title\n\n## Workflow\n1. Step 1\n`;
            } else if (tpl === 'project') {
                initialContent = `---\nname: ${path.split('/')[2] || 'new-project'}\ndescription: Project description\nstatus: active\n---\n\n# Project Title\n\n## Goal\nDescribe goal here.\n`;
            } else if (tpl === 'note') {
                initialContent = `# Note: ${path.split('/').pop().replace('.md', '')}\n\nDate: ${new Date().toLocaleDateString()}\n\n`;
            }

            try {
                const res = await window.API.fileboxWriteFile(path, initialContent, 'Web UI create file', fbState.currentOwner, getToken());
                if (res.data) {
                    document.getElementById('fbNewFileModal').classList.remove('active');
                    showToast(`Created ${path}`, 'success');
                    await refreshAll();
                    await openFile(path);
                } else {
                    showToast(`Creation failed: ${res.error}`, 'error');
                }
            } catch (err) {
                showToast(`Error: ${err.message}`, 'error');
            }
        });

        // New Folder Form
        document.getElementById('fbNewFolderForm')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const path = document.getElementById('fbNewFolderPath').value.trim();
            try {
                const res = await window.API.fileboxMkdir(path, fbState.currentOwner, getToken());
                if (res.data) {
                    document.getElementById('fbNewFolderModal').classList.remove('active');
                    showToast(`Created directory ${path}`, 'success');
                    await refreshAll();
                } else {
                    showToast(`Directory creation failed: ${res.error}`, 'error');
                }
            } catch (err) {
                showToast(`Error: ${err.message}`, 'error');
            }
        });

        // Move Form
        document.getElementById('fbMoveForm')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const src = document.getElementById('fbMoveSrc').value.trim();
            const dst = document.getElementById('fbMoveDst').value.trim();
            try {
                const res = await window.API.fileboxMove(src, dst, 'Web UI move', fbState.currentOwner, getToken());
                if (res.data) {
                    document.getElementById('fbMoveModal').classList.remove('active');
                    showToast(`Moved to ${dst}`, 'success');
                    fbState.activePath = dst;
                    await refreshAll();
                    await openFile(dst);
                } else {
                    showToast(`Move failed: ${res.error}`, 'error');
                }
            } catch (err) {
                showToast(`Error: ${err.message}`, 'error');
            }
        });

        // Migrate Form
        document.getElementById('fbMigrateForm')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const srcDir = document.getElementById('fbMigrateSource').value.trim();
            const legacyStorage = document.getElementById('fbMigrateLegacyStorage').checked;
            const dryRun = document.getElementById('fbMigrateDryRun').checked;
            const resDiv = document.getElementById('fbMigrateResult');
            const submitBtn = document.getElementById('fbBtnDoMigrate');

            submitBtn.disabled = true;
            resDiv.style.display = 'block';
            resDiv.innerHTML = '<span style="color:var(--fg-muted);">Running migration...</span>';

            try {
                const res = await window.API.fileboxMigrate({
                    source_dir: srcDir || null,
                    migrate_legacy_storage: legacyStorage,
                    dry_run: dryRun,
                    target_owner: fbState.currentOwner
                }, getToken());

                if (res.data) {
                    let summaryHtml = `<strong>Migration Completed (${dryRun ? 'DRY RUN' : 'APPLIED'})</strong><br>`;
                    (res.data.reports || []).forEach(rep => {
                        summaryHtml += `<div style="margin-top:6px;padding:6px;border-left:2px solid var(--accent);">`;
                        summaryHtml += `Status: <strong>${rep.status.toUpperCase()}</strong> | Copied: ${rep.total_copied} | Transformed: ${rep.total_transformed}<br>`;
                        if (rep.warnings && rep.warnings.length) {
                            summaryHtml += `<span style="color:var(--warn);">Warnings: ${rep.warnings.join(', ')}</span><br>`;
                        }
                        if (rep.errors && rep.errors.length) {
                            summaryHtml += `<span style="color:var(--danger);">Errors: ${rep.errors.join(', ')}</span><br>`;
                        }
                        summaryHtml += `</div>`;
                    });
                    resDiv.innerHTML = summaryHtml;
                    if (!dryRun) {
                        await refreshAll();
                    }
                } else {
                    resDiv.innerHTML = `<span style="color:var(--danger);">Migration failed: ${escapeHtml(res.error)}</span>`;
                }
            } catch (err) {
                resDiv.innerHTML = `<span style="color:var(--danger);">Migration error: ${escapeHtml(err.message)}</span>`;
            } finally {
                submitBtn.disabled = false;
            }
        });
    }

    // ── Utility Helpers ─────────────────────────────────────────────────────

    function updateBreadcrumbs(path) {
        const bc = document.getElementById('fbBreadcrumbs');
        if (bc) {
            bc.innerHTML = renderBreadcrumbsHtml(path);
        }
    }

    function highlightActiveTreeNode(path) {
        document.querySelectorAll('.fb-tree-row').forEach(row => {
            row.classList.toggle('active', row.dataset.path === path);
        });
    }

    function getParentDir(path) {
        const parts = path.split('/');
        parts.pop();
        return parts.join('/') || 'workspace';
    }

    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function getFileIcon(node) {
        if (node.type === 'directory') {
            return '📁';
        }
        const ext = node.name.split('.').pop().toLowerCase();
        switch (ext) {
            case 'md':
            case 'markdown':
                return '📝';
            case 'yaml':
            case 'yml':
                return '⚙️';
            case 'json':
                return '📋';
            case 'py':
            case 'sh':
            case 'js':
                return '⚡';
            case 'jsonl':
            case 'log':
                return '📜';
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'svg':
                return '🖼️';
            default:
                return '📄';
        }
    }

    function showLoading(show) {
        const tree = document.getElementById('fbTreeContent');
        if (tree && show && !fbState.treeData) {
            tree.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg-muted);font-size:12px;">Loading...</div>';
        }
    }

    function showEditorLoading(show) {
        const view = document.getElementById('fbCardViewer');
        if (view && show) {
            view.style.opacity = '0.6';
        } else if (view) {
            view.style.opacity = '1';
        }
    }

    function showToast(msg, type = 'info') {
        let toast = document.getElementById('fbToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'fbToast';
            toast.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:12px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:99999;box-shadow:var(--shadow-lg);transition:opacity 0.3s;pointer-events:none;';
            document.body.appendChild(toast);
        }
        toast.style.background = type === 'error' ? 'var(--danger)' : type === 'success' ? 'var(--success)' : 'var(--surface-raised)';
        toast.style.color = type === 'error' || type === 'success' ? '#ffffff' : 'var(--fg)';
        toast.style.border = type === 'info' ? '1px solid var(--border)' : 'none';
        toast.textContent = msg;
        toast.style.opacity = '1';
        setTimeout(() => { toast.style.opacity = '0'; }, 3200);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Clean Markdown renderer
    function renderMarkdown(md) {
        if (!md) return '<p style="color:var(--fg-muted);">Empty file</p>';
        let html = escapeHtml(md);

        // Code blocks
        html = html.replace(/```([a-zA-Z0-9_]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre class="fb-code-block"><code class="lang-${lang}">${code}</code></pre>`;
        });

        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code class="fb-inline-code">$1</code>');

        // Headers
        html = html.replace(/^### (.*$)/gim, '<h3 class="fb-h3">$1</h3>');
        html = html.replace(/^## (.*$)/gim, '<h2 class="fb-h2">$1</h2>');
        html = html.replace(/^# (.*$)/gim, '<h1 class="fb-h1">$1</h1>');

        // Bold & Italics
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Horizontal rules
        html = html.replace(/^---$/gim, '<hr class="fb-hr" />');

        // Bullet lists
        html = html.replace(/^\- (.*$)/gim, '<li class="fb-li">$1</li>');

        // Line breaks
        html = html.replace(/\n\n/g, '<br><br>');

        return `<div class="fb-rendered-prose">${html}</div>`;
    }

    // Expose Global Object
    window.FileboxUI = {
        init,
        refresh: refreshAll,
        openFile,
    };

    // Auto-init if page is active on boot
    document.addEventListener('DOMContentLoaded', () => {
        const fileboxPage = document.getElementById('page-filebox');
        if (fileboxPage && !fileboxPage.classList.contains('hidden')) {
            init();
        }
    });

})();
