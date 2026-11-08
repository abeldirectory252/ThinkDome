/**
 * filemanager.js — ThinkDome AI Model & Design File Management Workstation
 *
 * Authentic OS-style folder & file management workstation for AI agents:
 * - Real desktop vector folder & file icons (double-click opens/enters, single-click selects)
 * - Zero horizontal button clutter — clean, authentic OS experience
 * - Desktop-class Right-Click Context Menu (Open, Preview, Edit, Rename, Duplicate, Download, Delete)
 * - Canvas Right-Click Menu (New Folder, New Model, New Design, New Prompt, New Skill, Upload, Refresh)
 * - Live bidirectional WebSocket synchronization with glowing status badge
 * - Specialized for AI Agent Models, System Designs, Prompts, MCP Skills, and Knowledge
 * - In-place Inspector Drawer with parameter chips, live code preview, and inline editor
 * - Drag-and-drop file upload directly onto folder canvas
 */

(function () {
    'use strict';

    // Workstation State
    const fmState = {
        initialized: false,
        currentUser: null,
        currentOwner: null,
        tenant: 'default',
        isAdmin: false,
        availableUsers: [],
        cwd: '', // Current working directory
        items: [], // Files & folders in current directory
        selectedPaths: new Set(),
        activeFile: null,
        inspectorOpen: true,
        viewMode: 'grid', // Default to desktop icon grid
        sortBy: 'name', // 'name', 'size', 'date', 'type'
        sortDesc: false,
        searchQuery: '',
        activeFilter: 'all', // 'all', 'models', 'designs', 'prompts', 'skills', 'data'
        inlineEditMode: false,
        editorContent: '',
        editorDirty: false,
        statusInfo: null,
        // WebSocket State
        ws: null,
        wsConnected: false,
        wsReconnectTimer: null,
        wsPingInterval: null,
    };

    function getToken() {
        return localStorage.getItem('thinkdome_token') || '';
    }

    function showToast(msg, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(msg, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${msg}`);
        }
    }

    // ── Helper Utilities ────────────────────────────────────────────────────

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatBytes(bytes) {
        if (bytes === 0 || bytes === undefined || bytes === null) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function formatDate(ts) {
        if (!ts) return '—';
        try {
            const d = new Date(ts);
            if (isNaN(d.getTime())) return String(ts);
            return d.toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return String(ts);
        }
    }

    function getParentDir(path) {
        if (!path || path === '/') return '';
        const clean = path.replace(/\/+$/, '');
        const lastSlash = clean.lastIndexOf('/');
        if (lastSlash === -1) return '';
        return clean.substring(0, lastSlash);
    }

    function getFileExtension(filename) {
        if (!filename) return '';
        const parts = filename.split('.');
        return parts.length > 1 ? parts.pop().toLowerCase() : '';
    }

    function getFolderInfo(folderName, fullPath = '') {
        const name = folderName.toLowerCase();
        const path = fullPath.toLowerCase();

        if (name === 'models' || path.includes('models')) {
            return { icon: '🧠', badge: 'AI Models', badgeClass: 'model', color: '#a855f7', desc: 'Model configs & weights' };
        }
        if (name === 'designs' || path.includes('designs')) {
            return { icon: '📐', badge: 'Architecture', badgeClass: 'design', color: '#38bdf8', desc: 'System designs & DAGs' };
        }
        if (name === 'prompts' || path.includes('prompts')) {
            return { icon: '🤖', badge: 'Prompts', badgeClass: 'prompt', color: '#f59e0b', desc: 'Personas & instructions' };
        }
        if (name === 'skills' || path.includes('skills')) {
            return { icon: '⚡', badge: 'Agent Skills', badgeClass: 'skill', color: '#10b981', desc: 'MCP tools & executable skills' };
        }
        if (name === 'knowledge' || path.includes('knowledge')) {
            return { icon: '📚', badge: 'RAG Knowledge', badgeClass: 'design', color: '#06b6d4', desc: 'Corpora & references' };
        }
        if (name === 'memory' || path.includes('memory')) {
            return { icon: '💾', badge: 'Memory Store', badgeClass: 'model', color: '#8b5cf6', desc: 'Semantic & episodic memory' };
        }
        if (name === 'workspace' || path.includes('workspace')) {
            return { icon: '💼', badge: 'Workspace', badgeClass: 'prompt', color: '#f97316', desc: 'Active projects & code' };
        }
        if (name === 'config' || path.includes('config')) {
            return { icon: '⚙️', badge: 'Config', badgeClass: 'skill', color: '#64748b', desc: 'Permissions & runtime' };
        }
        if (name === 'logs' || path.includes('logs')) {
            return { icon: '📜', badge: 'Traces', badgeClass: 'dataset', color: '#ef4444', desc: 'Execution audit stream' };
        }

        return { icon: '📁', badge: 'Folder', badgeClass: 'skill', color: '#38bdf8', desc: 'Directory' };
    }

    function getFileTypeInfo(filename, isDir, fullPath = '') {
        if (isDir) {
            const fi = getFolderInfo(filename, fullPath);
            return {
                category: 'folder',
                label: fi.badge,
                icon: fi.icon,
                badge: 'DIR',
                color: fi.color,
                isModel: false,
                isDesign: false,
            };
        }

        const ext = getFileExtension(filename);
        const name = filename.toLowerCase();

        // AI Model Specs & Weights
        if (name.includes('model') || name.endsWith('.onnx') || name.endsWith('.gguf') || name.endsWith('.pt') || name.endsWith('.safetensors') || name.endsWith('.bin')) {
            return {
                category: 'models',
                label: 'AI Model Spec',
                icon: '🧠',
                badge: 'MODEL',
                color: '#a855f7',
                isModel: true,
                isDesign: false,
            };
        }

        // System Designs & Architecture DAGs
        if (name.includes('design') || name.includes('architecture') || name.includes('workflow') || name.includes('dag') || ext === 'mermaid' || ext === 'spec') {
            return {
                category: 'designs',
                label: 'System Design',
                icon: '📐',
                badge: 'DESIGN',
                color: '#38bdf8',
                isModel: false,
                isDesign: true,
            };
        }

        // Agent Prompts & Personas
        if (name.includes('prompt') || name.includes('persona') || ext === 'prompt') {
            return {
                category: 'prompts',
                label: 'Agent Prompt',
                icon: '🤖',
                badge: 'PROMPT',
                color: '#f59e0b',
                isModel: false,
                isDesign: false,
            };
        }

        // Agent Skills & MCP Tools
        if (name === 'skill.md' || name.includes('skill') || name.includes('tool')) {
            return {
                category: 'skills',
                label: 'Agent Skill',
                icon: '⚡',
                badge: 'SKILL',
                color: '#10b981',
                isModel: false,
                isDesign: false,
            };
        }

        // Code and Documents
        switch (ext) {
            case 'py':
                return { category: 'skills', label: 'Python Tool', icon: '🐍', badge: 'PY', color: '#3b82f6' };
            case 'js':
            case 'mjs':
                return { category: 'skills', label: 'JavaScript Tool', icon: '⚡', badge: 'JS', color: '#eab308' };
            case 'ts':
                return { category: 'skills', label: 'TypeScript Spec', icon: '🔷', badge: 'TS', color: '#3b82f6' };
            case 'html':
                return { category: 'designs', label: 'HTML Layout', icon: '🌐', badge: 'HTML', color: '#f97316' };
            case 'css':
                return { category: 'designs', label: 'Design Stylesheet', icon: '🎨', badge: 'CSS', color: '#06b6d4' };
            case 'sh':
            case 'bash':
                return { category: 'skills', label: 'Execution Script', icon: '💻', badge: 'SH', color: '#10b981' };
            case 'md':
            case 'markdown':
                return { category: 'designs', label: 'Design Spec / Markdown', icon: '📝', badge: 'DOC', color: '#a855f7' };
            case 'txt':
                return { category: 'designs', label: 'Text Document', icon: '📄', badge: 'TXT', color: '#94a3b8' };
            case 'json':
                return { category: 'designs', label: 'JSON Schema / Config', icon: '📊', badge: 'JSON', color: '#10b981' };
            case 'yaml':
            case 'yml':
                return { category: 'models', label: 'YAML Configuration', icon: '⚙️', badge: 'YAML', color: '#ec4899' };
            case 'jsonl':
                return { category: 'data', label: 'Fine-tuning Dataset', icon: '📈', badge: 'JSONL', color: '#ec4899' };
            case 'csv':
                return { category: 'data', label: 'Dataset Table', icon: '📈', badge: 'CSV', color: '#14b8a6' };
            case 'sqlite':
            case 'db':
                return { category: 'data', label: 'Vector / SQLite DB', icon: '🗄️', badge: 'DB', color: '#6366f1' };
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'gif':
            case 'webp':
            case 'svg':
                return { category: 'designs', label: 'Design Graphic', icon: '🖼️', badge: ext.toUpperCase(), color: '#ec4899' };
            default:
                return { category: 'designs', label: ext ? `${ext.toUpperCase()} File` : 'File', icon: '📄', badge: ext ? ext.toUpperCase() : 'FILE', color: '#94a3b8' };
        }
    }

    // ── Authentic Vector Visual Icon Generators ─────────────────────────────

    function getFolderSvg(folderName, fullPath = '') {
        const fi = getFolderInfo(folderName, fullPath);
        const id = 'f_' + Math.random().toString(36).substring(2, 8);

        // Curated color palettes tuned for authentic OS directory feel
        let backGrad1 = '#0284c7';
        let backGrad2 = '#075985';
        let frontGrad1 = '#38bdf8';
        let frontGrad2 = '#0284c7';
        let frontGrad3 = '#0369a1';
        let rimColor = 'rgba(255, 255, 255, 0.7)';

        const name = folderName.toLowerCase();
        if (name === 'models' || fullPath.includes('models')) {
            backGrad1 = '#6366f1'; backGrad2 = '#4338ca';
            frontGrad1 = '#818cf8'; frontGrad2 = '#6366f1'; frontGrad3 = '#4f46e5';
        } else if (name === 'designs' || fullPath.includes('designs')) {
            backGrad1 = '#0891b2'; backGrad2 = '#155e75';
            frontGrad1 = '#22d3ee'; frontGrad2 = '#06b6d4'; frontGrad3 = '#0e7490';
        } else if (name === 'skills' || fullPath.includes('skills')) {
            backGrad1 = '#059669'; backGrad2 = '#065f46';
            frontGrad1 = '#34d399'; frontGrad2 = '#10b981'; frontGrad3 = '#047857';
        } else if (name === 'prompts' || fullPath.includes('prompts')) {
            backGrad1 = '#d97706'; backGrad2 = '#92400e';
            frontGrad1 = '#fbbf24'; frontGrad2 = '#f59e0b'; frontGrad3 = '#b45309';
        } else if (name === 'workspace' || fullPath.includes('workspace')) {
            backGrad1 = '#ea580c'; backGrad2 = '#9a3412';
            frontGrad1 = '#fb923c'; frontGrad2 = '#f97316'; frontGrad3 = '#c2410c';
        } else {
            // Default macOS Finder Ocean Blue folder
            backGrad1 = '#0284c7'; backGrad2 = '#0369a1';
            frontGrad1 = '#60a5fa'; frontGrad2 = '#38bdf8'; frontGrad3 = '#0284c7';
        }

        // Stamped category emblem: NO CAMERA LENS CIRCLE!
        let emblemSvg = '';
        if (fi.icon && fi.icon !== '📁') {
            emblemSvg = `
                <g transform="translate(39, 38)">
                    <text x="0" y="0" font-size="18" text-anchor="middle" dominant-baseline="central" style="filter: drop-shadow(0 1.5px 2px rgba(0,0,0,0.3));">${fi.icon}</text>
                </g>
            `;
        }

        return `
            <div class="fm-folder-visual">
                <svg class="fm-real-folder-svg" viewBox="0 0 78 60" fill="none">
                    <defs>
                        <linearGradient id="fBack_${id}" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="${backGrad1}" />
                            <stop offset="100%" stop-color="${backGrad2}" />
                        </linearGradient>
                        <linearGradient id="fFront_${id}" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="${frontGrad1}" />
                            <stop offset="25%" stop-color="${frontGrad2}" />
                            <stop offset="100%" stop-color="${frontGrad3}" />
                        </linearGradient>
                        <linearGradient id="fPaper_${id}" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#ffffff" />
                            <stop offset="100%" stop-color="#f1f5f9" />
                        </linearGradient>
                        <filter id="fShadow_${id}" x="-10%" y="-10%" width="120%" height="130%">
                            <feDropShadow dx="0" dy="2.5" stdDeviation="2" flood-color="#000000" flood-opacity="0.25" />
                        </filter>
                        <filter id="fFrontShadow_${id}" x="-10%" y="-10%" width="120%" height="130%">
                            <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000000" flood-opacity="0.22" />
                        </filter>
                    </defs>

                    <!-- Back Tab & Backplate: Authentic OS Folder Tab Structure -->
                    <path d="M6 12C6 9 8.5 7 11.5 7H28C30.2 7 32.2 8.2 33.3 10.1L35.8 14.5C36.7 16 38.3 17 40.2 17H67C70 17 72.5 19.5 72.5 22.5V49C72.5 52 70 54.5 67 54.5H11.5C8.5 54.5 6 52 6 49V12Z" fill="url(#fBack_${id})" filter="url(#fShadow_${id})" />
                    
                    <!-- Back Tab Highlight Edge -->
                    <path d="M11.5 8H27.8C29.7 8 31.4 9 32.4 10.6L34.9 15C35.9 16.6 37.6 17.6 39.5 17.6H67" stroke="${rimColor}" stroke-width="1" stroke-linecap="round" fill="none" />

                    <!-- Inner Depth Shadow -->
                    <path d="M9 17H68V23H9Z" fill="rgba(0,0,0,0.2)" />

                    <!-- Authentic Document Sheets Peeking Out (Instantly confirms: Folder with Files) -->
                    <rect x="18" y="10" width="40" height="18" rx="2" fill="#cbd5e1" opacity="0.85" />
                    <rect x="14" y="7" width="48" height="22" rx="2" fill="url(#fPaper_${id})" stroke="#cbd5e1" stroke-width="0.8" />
                    <line x1="20" y1="12" x2="32" y2="12" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round" />
                    <line x1="20" y1="16" x2="50" y2="16" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round" />

                    <!-- 3D Front Flap / Pocket -->
                    <path d="M6 20C6 17.2 8.2 15 11 15H67.5C70.3 15 72.5 17.2 72.5 20V49C72.5 52 70 54.5 67 54.5H11.5C8.5 54.5 6 52 6 49V20Z" fill="url(#fFront_${id})" filter="url(#fFrontShadow_${id})" />
                    
                    <!-- Front Top Specular Rim Highlight -->
                    <path d="M7 16.2H71.5" stroke="${rimColor}" stroke-width="1.2" stroke-linecap="round" />
                    
                    <!-- Subtle Horizontal Seam Line on Pocket -->
                    <path d="M7 23H71.5" stroke="rgba(0,0,0,0.06)" stroke-width="1" />

                    <!-- Stamped Category Emblem (Clean, No Camera Lens Circle!) -->
                    ${emblemSvg}
                </svg>
            </div>
        `;
    }

    function getFileSvg(filename, fullPath = '') {
        const info = getFileTypeInfo(filename, false, fullPath);
        const color = info.color || '#38bdf8';
        const ext = (getFileExtension(filename) || 'FILE').toUpperCase().slice(0, 5);
        const id = 'doc_' + Math.random().toString(36).substring(2, 8);

        return `
            <div class="fm-file-visual">
                <svg class="fm-real-file-svg" viewBox="0 0 54 64" fill="none">
                    <defs>
                        <linearGradient id="docGrad_${id}" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#ffffff" />
                            <stop offset="100%" stop-color="#f1f5f9" />
                        </linearGradient>
                        <filter id="docShadow_${id}" x="-10%" y="-10%" width="120%" height="130%">
                            <feDropShadow dx="0" dy="2.5" stdDeviation="2" flood-color="#000000" flood-opacity="0.14" />
                        </filter>
                    </defs>
                    <!-- Sheet Body with Dogear Corner Fold -->
                    <path d="M7 8C7 4.7 9.7 2 13 2H36L47 13V56C47 59.3 44.3 62 41 62H13C9.7 62 7 59.3 7 56V8Z" fill="url(#docGrad_${id})" stroke="${color}" stroke-width="1.3" filter="url(#docShadow_${id})" />
                    <!-- Dogear Fold Triangle -->
                    <path d="M36 2V11C36 12.1 36.9 13 38 13H47" fill="#cbd5e1" stroke="${color}" stroke-width="1" />
                    <!-- Code / Content Hint Lines -->
                    <line x1="13" y1="19" x2="30" y2="19" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round" />
                    <line x1="13" y1="23" x2="41" y2="23" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round" />
                    <!-- Emblem Center Icon -->
                    <text x="27" y="34" font-size="16" text-anchor="middle" dominant-baseline="central">${info.icon}</text>
                    <!-- Extension Pill Badge -->
                    <rect x="9" y="46" width="36" height="12" rx="3.5" fill="${color}" />
                    <text x="27" y="52" font-size="8" font-weight="700" fill="#ffffff" text-anchor="middle" dominant-baseline="central" font-family="monospace">${ext}</text>
                </svg>
            </div>
        `;
    }

    function renderMarkdown(md) {
        if (!md) return '<p style="color:var(--fg-muted);">Empty document</p>';
        let html = escapeHtml(md);

        // Code blocks
        html = html.replace(/```([a-zA-Z0-9_]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre class="fb-code-block" style="background:var(--surface-raised);padding:10px;border-radius:6px;overflow-x:auto;"><code class="lang-${lang}">${code}</code></pre>`;
        });

        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code style="background:var(--surface-raised);padding:2px 5px;border-radius:4px;font-family:var(--font-mono);font-size:11.5px;">$1</code>');

        // Headers
        html = html.replace(/^### (.*$)/gim, '<h3 style="font-size:14px;margin:10px 0 4px;color:var(--fg);">$1</h3>');
        html = html.replace(/^## (.*$)/gim, '<h2 style="font-size:16px;margin:12px 0 6px;color:var(--fg);">$1</h2>');
        html = html.replace(/^# (.*$)/gim, '<h1 style="font-size:18px;margin:14px 0 8px;color:var(--fg);">$1</h1>');

        // Formatting
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        html = html.replace(/^---$/gim, '<hr style="border:none;border-top:1px solid var(--border);margin:12px 0;" />');
        html = html.replace(/^\- (.*$)/gim, '<li style="margin-left:16px;margin-bottom:4px;">$1</li>');
        html = html.replace(/\n\n/g, '<br><br>');

        return `<div class="fm-preview-markdown">${html}</div>`;
    }

    // ── WebSocket Real-Time Sync ────────────────────────────────────────────

    function initWebSocket() {
        if (fmState.ws && (fmState.ws.readyState === WebSocket.OPEN || fmState.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const token = getToken();
        const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const clientId = `fm_${Date.now()}`;
        const wsUrl = `${wsProto}//${location.host}/ws/${clientId}?token=${encodeURIComponent(token)}`;

        try {
            const ws = new WebSocket(wsUrl);
            fmState.ws = ws;

            ws.onopen = () => {
                fmState.wsConnected = true;
                updateWsStatusUI(true);

                if (fmState.wsReconnectTimer) {
                    clearTimeout(fmState.wsReconnectTimer);
                    fmState.wsReconnectTimer = null;
                }

                // Heartbeat keep-alive every 20 seconds
                if (fmState.wsPingInterval) clearInterval(fmState.wsPingInterval);
                fmState.wsPingInterval = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'ping' }));
                    }
                }, 20000);
            };

            ws.onmessage = (event) => {
                try {
                    const payload = JSON.parse(event.data);
                    if (payload.event === 'filebox_changed' || payload.event === 'file_created' || payload.event === 'file_deleted') {
                        showToast('Live WebSocket: Assets synchronized', 'info');
                        refreshMetrics();
                        loadDirectory(fmState.cwd);
                    }
                } catch {}
            };

            ws.onclose = () => {
                fmState.wsConnected = false;
                updateWsStatusUI(false);
                if (fmState.wsPingInterval) clearInterval(fmState.wsPingInterval);

                if (!fmState.wsReconnectTimer) {
                    fmState.wsReconnectTimer = setTimeout(() => {
                        fmState.wsReconnectTimer = null;
                        initWebSocket();
                    }, 4000);
                }
            };

            ws.onerror = () => {
                fmState.wsConnected = false;
                updateWsStatusUI(false);
            };
        } catch (e) {
            console.warn('WebSocket init exception:', e);
            updateWsStatusUI(false);
        }
    }

    function updateWsStatusUI(connected) {
        const pill = document.getElementById('fmWsStatusPill');
        const text = document.getElementById('fmWsStatusText');
        if (!pill || !text) return;

        if (connected) {
            pill.className = 'fm-ws-status connected';
            pill.title = 'Real-time WebSocket active. Receiving model & design asset events.';
            text.textContent = 'Live WS Sync';
        } else {
            pill.className = 'fm-ws-status disconnected';
            pill.title = 'WebSocket offline. Click to reconnect now.';
            text.textContent = 'WS Reconnecting...';
        }
    }

    function broadcastWsEvent(op, path) {
        if (fmState.ws && fmState.ws.readyState === WebSocket.OPEN) {
            try {
                fmState.ws.send(JSON.stringify({
                    action: 'filebox_event',
                    op: op,
                    path: path,
                    owner: fmState.currentOwner,
                    timestamp: Date.now()
                }));
            } catch {}
        }
    }

    // ── Core Entry Point ────────────────────────────────────────────────────

    async function init() {
        const page = document.getElementById('page-filemanager');
        if (!page) return;
        setupUI();
        initWebSocket();
        await loadUserData();
        await refreshMetrics();
        await loadDirectory(fmState.cwd);
        fmState.initialized = true;
    }

    async function loadUserData() {
        try {
            if (window.API?.fileboxGetUsers) {
                const res = await window.API.fileboxGetUsers(getToken());
                if (res.data) {
                    fmState.currentUser = res.data.current_user;
                    fmState.tenant = res.data.tenant;
                    fmState.isAdmin = res.data.is_admin;
                    fmState.availableUsers = res.data.users || [];
                    if (!fmState.currentOwner) {
                        fmState.currentOwner = fmState.currentUser;
                    }
                    renderUserSelector();
                }
            }
        } catch (e) {
            console.warn('Failed to load user info in File Manager:', e);
        }
    }

    function renderUserSelector() {
        const selContainer = document.getElementById('fmUserSelectorContainer');
        if (!selContainer) return;

        if (!fmState.isAdmin || fmState.availableUsers.length <= 1) {
            selContainer.innerHTML = `
                <div style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;">
                    <span style="color:var(--fg-muted);">Agent:</span>
                    <strong style="color:var(--fg);">${escapeHtml(fmState.currentOwner || 'agent')}</strong>
                </div>
            `;
            return;
        }

        let optionsHtml = fmState.availableUsers.map(u => {
            const selected = u.username === fmState.currentOwner ? 'selected' : '';
            return `<option value="${escapeHtml(u.username)}" ${selected}>${escapeHtml(u.username)} ${u.is_current ? '(Current)' : ''}</option>`;
        }).join('');

        selContainer.innerHTML = `
            <div style="display:inline-flex;align-items:center;gap:6px;font-size:12px;">
                <label for="fmUserSelect" style="color:var(--fg-muted);font-weight:600;">Agent Context:</label>
                <select id="fmUserSelect" class="form-input" style="padding:4px 8px;height:30px;font-size:12px;font-weight:600;min-width:140px;">
                    ${optionsHtml}
                </select>
            </div>
        `;

        const selectEl = document.getElementById('fmUserSelect');
        if (selectEl) {
            selectEl.addEventListener('change', async (e) => {
                fmState.currentOwner = e.target.value;
                fmState.activeFile = null;
                fmState.selectedPaths.clear();
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            });
        }
    }

    async function refreshMetrics() {
        try {
            if (window.API?.fileboxGetStatus) {
                const res = await window.API.fileboxGetStatus(fmState.currentOwner, getToken());
                if (res.data) {
                    fmState.statusInfo = res.data;
                    updateMetricsUI();
                }
            }
        } catch (e) {
            console.warn('Could not load status:', e);
        }
    }

    function updateMetricsUI() {
        const totalFilesEl = document.getElementById('fmMetricTotalFiles');
        const storageSizeEl = document.getElementById('fmMetricStorageSize');
        const quotaEl = document.getElementById('fmMetricStorageQuota');
        const barEl = document.getElementById('fmStorageBar');
        const sidebarBarEl = document.getElementById('fmSidebarStorageBar');
        const sidebarTextEl = document.getElementById('fmSidebarStorageText');

        if (!fmState.statusInfo) return;
        const s = fmState.statusInfo;
        const sizeKb = (s.total_size / 1024).toFixed(1);
        const sizeMb = (s.total_size / (1024 * 1024)).toFixed(2);
        const displaySize = s.total_size > 1048576 ? `${sizeMb} MB` : `${sizeKb} KB`;

        if (totalFilesEl) totalFilesEl.textContent = s.total_files || 0;
        if (storageSizeEl) storageSizeEl.textContent = displaySize;

        const maxBytes = 1000 * 1024 * 1024; // 1GB volume
        const pct = Math.min(100, Math.max(1, ((s.total_size / maxBytes) * 100))).toFixed(1);
        if (quotaEl) quotaEl.textContent = `${pct}% of 1.0 GB volume`;
        if (barEl) barEl.style.width = `${pct}%`;
        if (sidebarBarEl) sidebarBarEl.style.width = `${pct}%`;
        if (sidebarTextEl) sidebarTextEl.textContent = `${displaySize} / 1.0 GB (${pct}%)`;
    }

    // ── Directory Fetching & Navigation ─────────────────────────────────────

    async function loadDirectory(path = '') {
        fmState.cwd = path.replace(/^\/+|\/+$/g, '');
        fmState.selectedPaths.clear();
        updateBatchBar();
        renderBreadcrumbs();
        closeContextMenu();

        const canvasEl = document.getElementById('fmCanvas');
        if (canvasEl) {
            canvasEl.innerHTML = '<div style="text-align:center;padding:40px;color:var(--fg-muted);"><span class="spinner" style="display:inline-block;margin-right:6px;"></span> Reading directory assets...</div>';
        }

        try {
            let items = [];
            if (window.API?.fileboxListDir) {
                const res = await window.API.fileboxListDir(fmState.cwd, fmState.currentOwner, getToken());
                if (res.data && Array.isArray(res.data.items)) {
                    items = res.data.items;
                }
            }

            if (!items.length && window.API?.fileboxGetTree) {
                const treeRes = await window.API.fileboxGetTree(fmState.cwd, 1, fmState.currentOwner, getToken());
                if (treeRes.data && treeRes.data.children) {
                    items = treeRes.data.children.map(c => ({
                        name: c.name,
                        path: c.path,
                        type: c.type,
                        size: c.size,
                        modified: c.modified,
                    }));
                }
            }

            fmState.items = items;
            renderCanvas();
            updateFolderItemCount(items.length);
        } catch (e) {
            console.error('Failed to load directory:', e);
            if (canvasEl) {
                canvasEl.innerHTML = `<div style="text-align:center;padding:40px;color:var(--danger);">Error loading directory: ${escapeHtml(e.message)}</div>`;
            }
        }
    }

    function updateFolderItemCount(count) {
        const countEl = document.getElementById('fmCurrentFolderCount');
        if (countEl) countEl.textContent = `${count} ${count === 1 ? 'item' : 'items'}`;
        const dirMetricEl = document.getElementById('fmMetricTotalDirs');
        if (dirMetricEl) {
            const dirsCount = fmState.items.filter(i => i.type === 'directory').length;
            dirMetricEl.textContent = dirsCount;
        }
    }

    function getFilteredAndSortedItems() {
        let items = [...fmState.items];

        // 1. Search Filter
        const q = (fmState.searchQuery || '').trim().toLowerCase();
        if (q) {
            items = items.filter(i => i.name.toLowerCase().includes(q) || (i.path && i.path.toLowerCase().includes(q)));
        }

        // 2. Category Filter
        if (fmState.activeFilter !== 'all') {
            items = items.filter(i => {
                if (i.type === 'directory') return true;
                const info = getFileTypeInfo(i.name, false, i.path);
                return info.category === fmState.activeFilter;
            });
        }

        // 3. Sorting (Folders always stay first)
        items.sort((a, b) => {
            if (a.type === 'directory' && b.type !== 'directory') return -1;
            if (a.type !== 'directory' && b.type === 'directory') return 1;

            let cmp = 0;
            if (fmState.sortBy === 'name') {
                cmp = a.name.localeCompare(b.name);
            } else if (fmState.sortBy === 'size') {
                const sA = a.size || 0;
                const sB = b.size || 0;
                cmp = sA - sB;
            } else if (fmState.sortBy === 'date') {
                const dA = new Date(a.modified || 0).getTime();
                const dB = new Date(b.modified || 0).getTime();
                cmp = dA - dB;
            } else if (fmState.sortBy === 'type') {
                const tA = getFileExtension(a.name);
                const tB = getFileExtension(b.name);
                cmp = tA.localeCompare(tB);
            }
            return fmState.sortDesc ? -cmp : cmp;
        });

        return items;
    }

    // ── Main Canvas Renderer (No Horizontal Button Clutter) ──────────────────

    function renderCanvas() {
        const canvasEl = document.getElementById('fmCanvas');
        if (!canvasEl) return;

        const allItems = getFilteredAndSortedItems();
        const directories = allItems.filter(i => i.type === 'directory');
        const files = allItems.filter(i => i.type !== 'directory');

        if (!directories.length && !files.length) {
            canvasEl.innerHTML = `
                <div class="fm-empty-state">
                    <div class="fm-empty-icon">📂</div>
                    <h3>This Folder is Empty</h3>
                    <p>No model, design, prompt, or skill files found. Right-click anywhere or drag-and-drop assets to begin.</p>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center;">
                        <button class="btn btn-primary btn-sm" onclick="window.FileManagerUI.openNewModel()">🧠 + Model Spec</button>
                        <button class="btn btn-primary btn-sm" onclick="window.FileManagerUI.openNewDesign()">📐 + System Design</button>
                        <button class="btn btn-ghost btn-sm" onclick="window.FileManagerUI.openNewFolder()">📁 + New Folder</button>
                        <button class="btn btn-ghost btn-sm" onclick="window.FileManagerUI.openUpload()">Upload Files</button>
                    </div>
                </div>
            `;
            return;
        }

        if (fmState.viewMode === 'grid') {
            renderDesktopGrid(canvasEl, directories, files);
        } else {
            renderTableView(canvasEl, directories, files);
        }
    }

    // ── Mode 1: Desktop Icon Canvas (The "Real Thing") ──────────────────────

    function renderDesktopGrid(canvasEl, directories, files) {
        let html = `
            <!-- SVG defs for folder gradient -->
            <svg style="position:absolute;width:0;height:0;overflow:hidden;" aria-hidden="true">
                <defs>
                    <linearGradient id="fmFolderGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#ffffff" stop-opacity="0.3" />
                        <stop offset="100%" stop-color="#000000" stop-opacity="0.3" />
                    </linearGradient>
                </defs>
            </svg>
        `;

        // 1. Folders Section (if any)
        if (directories.length) {
            html += `
                <div class="fm-section-title">
                    <span>📁</span>
                    <span>Folders &amp; Subdirectories (${directories.length})</span>
                </div>
                <div class="fm-desktop-grid">
            `;

            directories.forEach(d => {
                const isSelected = fmState.selectedPaths.has(d.path);
                const info = getFolderInfo(d.name, d.path);

                html += `
                    <div class="fm-desktop-item ${isSelected ? 'selected' : ''}" draggable="true" tabindex="0" data-path="${escapeHtml(d.path)}" data-type="directory" title="${escapeHtml(d.name)} — Double click to enter">
                        <input type="checkbox" class="fm-desktop-checkbox" data-path="${escapeHtml(d.path)}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation();" />
                        ${getFolderSvg(d.name, d.path)}
                        <div class="fm-item-name">${escapeHtml(d.name)}</div>
                        <div class="fm-item-sub"><span class="fm-asset-chip ${info.badgeClass}">${escapeHtml(info.badge)}</span></div>
                    </div>
                `;
            });

            html += `</div>`;
        }

        // 2. Files Section (if any)
        if (files.length) {
            html += `
                <div class="fm-section-title" style="margin-top:${directories.length ? '18px' : '4px'};">
                    <span>📄</span>
                    <span>Model &amp; Design Assets (${files.length})</span>
                </div>
                <div class="fm-desktop-grid">
            `;

            files.forEach(f => {
                const isSelected = fmState.selectedPaths.has(f.path);
                const info = getFileTypeInfo(f.name, false, f.path);
                const sizeDisplay = formatBytes(f.size);

                let tagChip = '';
                if (info.isModel) tagChip = `<span class="fm-asset-chip model">MODEL</span>`;
                else if (info.isDesign) tagChip = `<span class="fm-asset-chip design">DESIGN</span>`;
                else if (info.category === 'prompts') tagChip = `<span class="fm-asset-chip prompt">PROMPT</span>`;
                else if (info.category === 'skills') tagChip = `<span class="fm-asset-chip skill">SKILL</span>`;
                else if (info.category === 'data') tagChip = `<span class="fm-asset-chip dataset">DATA</span>`;

                html += `
                    <div class="fm-desktop-item ${isSelected ? 'selected' : ''}" draggable="true" tabindex="0" data-path="${escapeHtml(f.path)}" data-type="file" title="${escapeHtml(f.name)} (${sizeDisplay}) — Double click to open">
                        <input type="checkbox" class="fm-desktop-checkbox" data-path="${escapeHtml(f.path)}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation();" />
                        ${getFileSvg(f.name, f.path)}
                        <div class="fm-item-name">${escapeHtml(f.name)}</div>
                        <div class="fm-item-sub">${sizeDisplay}</div>
                        ${tagChip}
                    </div>
                `;
            });

            html += `</div>`;
        }

        canvasEl.innerHTML = html;
        attachDesktopCanvasListeners(canvasEl);
    }

    function attachDesktopCanvasListeners(canvasEl) {
        // Double click: open folder / open file
        canvasEl.querySelectorAll('.fm-desktop-item').forEach(itemEl => {
            const path = itemEl.dataset.path;
            const type = itemEl.dataset.type;

            // Single click: select item & inspect
            itemEl.addEventListener('click', (e) => {
                if (e.target.closest('input[type="checkbox"]')) return;

                if (!e.ctrlKey && !e.metaKey && !e.shiftKey) {
                    fmState.selectedPaths.clear();
                    canvasEl.querySelectorAll('.fm-desktop-item').forEach(el => el.classList.remove('selected'));
                }

                fmState.selectedPaths.add(path);
                itemEl.classList.add('selected');
                updateBatchBar();

                const item = fmState.items.find(i => i.path === path);
                if (item) inspectFile(item);
            });

            // Double click: Enter directory OR open file
            itemEl.addEventListener('dblclick', () => {
                if (type === 'directory') {
                    loadDirectory(path);
                } else {
                    const item = fmState.items.find(i => i.path === path);
                    if (item) inspectFile(item, true);
                }
            });

            // Drag and drop: Move file into folder
            itemEl.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', path);
                e.dataTransfer.effectAllowed = 'move';
                itemEl.classList.add('dragging');
                fmState.draggedPath = path;
            });

            itemEl.addEventListener('dragend', () => {
                itemEl.classList.remove('dragging');
                canvasEl.querySelectorAll('.fm-desktop-item').forEach(el => el.classList.remove('drag-target'));
                fmState.draggedPath = null;
            });

            if (type === 'directory') {
                itemEl.addEventListener('dragover', (e) => {
                    if (!fmState.draggedPath || fmState.draggedPath === path || fmState.draggedPath.startsWith(path + '/')) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    itemEl.classList.add('drag-target');
                });

                itemEl.addEventListener('dragleave', () => {
                    itemEl.classList.remove('drag-target');
                });

                itemEl.addEventListener('drop', async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    itemEl.classList.remove('drag-target');
                    const srcPath = fmState.draggedPath || e.dataTransfer.getData('text/plain');
                    if (!srcPath || srcPath === path || srcPath.startsWith(path + '/')) return;

                    const fileName = srcPath.split('/').pop();
                    const dstPath = `${path}/${fileName}`;

                    try {
                        showToast(`Moving ${fileName} into ${path}...`, 'info');
                        const res = await window.API.fileboxMove(srcPath, dstPath, 'Drag-and-drop move', fmState.currentOwner, getToken());
                        if (res.error) {
                            showToast(`Move failed: ${res.error}`, 'error');
                        } else {
                            showToast(`Moved ${fileName} into ${path}`, 'success');
                            broadcastWsEvent('move', dstPath);
                            await refreshMetrics();
                            await loadDirectory(fmState.cwd);
                        }
                    } catch (err) {
                        showToast(`Failed to move: ${err.message}`, 'error');
                    }
                });
            }

            // Right click on item: trigger context menu
            itemEl.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                e.stopPropagation();

                // Select this item on right click
                if (!fmState.selectedPaths.has(path)) {
                    fmState.selectedPaths.clear();
                    canvasEl.querySelectorAll('.fm-desktop-item').forEach(el => el.classList.remove('selected'));
                    fmState.selectedPaths.add(path);
                    itemEl.classList.add('selected');
                    updateBatchBar();
                }

                const item = fmState.items.find(i => i.path === path);
                if (item) {
                    inspectFile(item);
                    openContextMenu(e, item, false);
                }
            });
        });

        // Checkboxes
        canvasEl.querySelectorAll('.fm-desktop-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const path = cb.dataset.path;
                if (cb.checked) {
                    fmState.selectedPaths.add(path);
                } else {
                    fmState.selectedPaths.delete(path);
                }
                cb.closest('.fm-desktop-item')?.classList.toggle('selected', cb.checked);
                updateBatchBar();
            });
        });

        // Right click on empty canvas area
        canvasEl.addEventListener('contextmenu', (e) => {
            if (e.target.closest('.fm-desktop-item')) return;
            openContextMenu(e, null, true);
        });

        // Left click on empty canvas area: clear selection
        canvasEl.addEventListener('click', (e) => {
            if (e.target.closest('.fm-desktop-item') || e.target.closest('#fmContextMenu')) return;
            fmState.selectedPaths.clear();
            canvasEl.querySelectorAll('.fm-desktop-item').forEach(el => el.classList.remove('selected'));
            updateBatchBar();
            closeContextMenu();
        });
    }

    // ── Mode 2: Clean Table List View ───────────────────────────────────────

    function renderTableView(canvasEl, directories, files) {
        let rowsHtml = '';
        const all = [...directories, ...files];

        all.forEach(item => {
            const isDir = item.type === 'directory';
            const isSelected = fmState.selectedPaths.has(item.path);
            const info = isDir ? getFolderInfo(item.name, item.path) : getFileTypeInfo(item.name, false, item.path);
            const sizeDisplay = isDir ? '—' : formatBytes(item.size);
            const modifiedDisplay = formatDate(item.modified);
            const isReadOnly = item.path?.startsWith('identity/') || item.name === 'filebox.yaml';
            const permBadge = isReadOnly ? '<span style="color:var(--danger);font-weight:600;">RO</span>' : '<span style="color:var(--success);font-weight:600;">RW</span>';

            let tagChip = '';
            if (!isDir) {
                if (info.isModel) tagChip = `<span class="fm-asset-chip model">MODEL</span>`;
                else if (info.isDesign) tagChip = `<span class="fm-asset-chip design">DESIGN</span>`;
                else if (info.category === 'prompts') tagChip = `<span class="fm-asset-chip prompt">PROMPT</span>`;
                else if (info.category === 'skills') tagChip = `<span class="fm-asset-chip skill">SKILL</span>`;
            } else {
                tagChip = `<span class="fm-asset-chip ${info.badgeClass}">${escapeHtml(info.badge)}</span>`;
            }

            rowsHtml += `
                <tr class="fm-table-row ${isSelected ? 'selected' : ''}" data-path="${escapeHtml(item.path)}" data-type="${item.type}">
                    <td style="width:36px;text-align:center;" onclick="event.stopPropagation();">
                        <input type="checkbox" class="fm-row-checkbox" data-path="${escapeHtml(item.path)}" ${isSelected ? 'checked' : ''} />
                    </td>
                    <td>
                        <div class="fm-file-name-cell">
                            <span style="font-size:16px;">${info.icon}</span>
                            <span style="font-weight:600;color:var(--fg);">${escapeHtml(item.name)}</span>
                            ${tagChip}
                        </div>
                    </td>
                    <td style="color:var(--fg-muted);">${escapeHtml(info.badge || info.label || (isDir ? 'Folder' : 'File'))}</td>
                    <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--fg);">${sizeDisplay}</td>
                    <td style="color:var(--fg-muted);font-size:12px;">${modifiedDisplay}</td>
                    <td style="font-size:11.5px;">${permBadge}</td>
                </tr>
            `;
        });

        canvasEl.innerHTML = `
            <div class="fm-table-wrap">
                <table class="fm-table">
                    <thead>
                        <tr>
                            <th style="width:36px;text-align:center;">
                                <input type="checkbox" id="fmSelectAllCheckbox" />
                            </th>
                            <th>Name</th>
                            <th>Category</th>
                            <th>Size</th>
                            <th>Last Modified</th>
                            <th>Perms</th>
                        </tr>
                    </thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            </div>
        `;

        attachTableListeners(canvasEl);
    }

    function attachTableListeners(canvasEl) {
        canvasEl.querySelectorAll('.fm-table-row').forEach(row => {
            const path = row.dataset.path;
            const type = row.dataset.type;

            row.setAttribute('draggable', 'true');

            // Drag and drop: Move file into folder in table view
            row.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', path);
                e.dataTransfer.effectAllowed = 'move';
                row.classList.add('dragging');
                fmState.draggedPath = path;
            });

            row.addEventListener('dragend', () => {
                row.classList.remove('dragging');
                canvasEl.querySelectorAll('.fm-table-row').forEach(el => el.classList.remove('drag-target'));
                fmState.draggedPath = null;
            });

            if (type === 'directory') {
                row.addEventListener('dragover', (e) => {
                    if (!fmState.draggedPath || fmState.draggedPath === path || fmState.draggedPath.startsWith(path + '/')) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    row.classList.add('drag-target');
                });

                row.addEventListener('dragleave', () => {
                    row.classList.remove('drag-target');
                });

                row.addEventListener('drop', async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    row.classList.remove('drag-target');
                    const srcPath = fmState.draggedPath || e.dataTransfer.getData('text/plain');
                    if (!srcPath || srcPath === path || srcPath.startsWith(path + '/')) return;

                    const fileName = srcPath.split('/').pop();
                    const dstPath = `${path}/${fileName}`;

                    try {
                        showToast(`Moving ${fileName} into ${path}...`, 'info');
                        const res = await window.API.fileboxMove(srcPath, dstPath, 'Drag-and-drop move', fmState.currentOwner, getToken());
                        if (res.error) {
                            showToast(`Move failed: ${res.error}`, 'error');
                        } else {
                            showToast(`Moved ${fileName} into ${path}`, 'success');
                            broadcastWsEvent('move', dstPath);
                            await refreshMetrics();
                            await loadDirectory(fmState.cwd);
                        }
                    } catch (err) {
                        showToast(`Failed to move: ${err.message}`, 'error');
                    }
                });
            }

            row.addEventListener('click', (e) => {
                if (e.target.closest('input[type="checkbox"]')) return;
                fmState.selectedPaths.clear();
                canvasEl.querySelectorAll('.fm-table-row').forEach(el => el.classList.remove('selected'));
                fmState.selectedPaths.add(path);
                row.classList.add('selected');
                updateBatchBar();

                const item = fmState.items.find(i => i.path === path);
                if (item) inspectFile(item);
            });

            row.addEventListener('dblclick', () => {
                if (type === 'directory') {
                    loadDirectory(path);
                } else {
                    const item = fmState.items.find(i => i.path === path);
                    if (item) inspectFile(item, true);
                }
            });

            row.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                e.stopPropagation();

                fmState.selectedPaths.clear();
                canvasEl.querySelectorAll('.fm-table-row').forEach(el => el.classList.remove('selected'));
                fmState.selectedPaths.add(path);
                row.classList.add('selected');
                updateBatchBar();

                const item = fmState.items.find(i => i.path === path);
                if (item) {
                    inspectFile(item);
                    openContextMenu(e, item, false);
                }
            });
        });

        canvasEl.querySelectorAll('.fm-row-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const path = cb.dataset.path;
                if (cb.checked) {
                    fmState.selectedPaths.add(path);
                } else {
                    fmState.selectedPaths.delete(path);
                }
                cb.closest('.fm-table-row')?.classList.toggle('selected', cb.checked);
                updateBatchBar();
            });
        });

        const selectAllCb = document.getElementById('fmSelectAllCheckbox');
        selectAllCb?.addEventListener('change', (e) => {
            const checked = e.target.checked;
            if (checked) {
                fmState.items.forEach(i => fmState.selectedPaths.add(i.path));
            } else {
                fmState.selectedPaths.clear();
            }
            canvasEl.querySelectorAll('.fm-row-checkbox').forEach(cb => cb.checked = checked);
            canvasEl.querySelectorAll('.fm-table-row').forEach(el => el.classList.toggle('selected', checked));
            updateBatchBar();
        });

        canvasEl.addEventListener('contextmenu', (e) => {
            if (e.target.closest('.fm-table-row')) return;
            openContextMenu(e, null, true);
        });
    }

    // ── Desktop Right-Click Context Menu ("Real Thing") ─────────────────────

    function openContextMenu(e, targetItem, isCanvas = false) {
        e.preventDefault();
        e.stopPropagation();

        const menu = document.getElementById('fmContextMenu');
        if (!menu) return;

        if (isCanvas || !targetItem) {
            // Right-click on empty canvas area
            menu.innerHTML = `
                <div class="fm-menu-header">
                    <span>📁 Current Folder Workspace</span>
                </div>
                <div class="fm-menu-item" data-action="new-folder">
                    <div class="fm-menu-item-main"><span>📁</span> <span>New Folder...</span></div>
                    <span class="fm-menu-shortcut">Folder</span>
                </div>
                <div class="fm-menu-item" data-action="new-model">
                    <div class="fm-menu-item-main"><span>🧠</span> <span>New AI Model Spec (YAML)...</span></div>
                </div>
                <div class="fm-menu-item" data-action="new-design">
                    <div class="fm-menu-item-main"><span>📐</span> <span>New System Design (JSON)...</span></div>
                </div>
                <div class="fm-menu-item" data-action="new-prompt">
                    <div class="fm-menu-item-main"><span>🤖</span> <span>New Agent Prompt (Markdown)...</span></div>
                </div>
                <div class="fm-menu-item" data-action="new-dag">
                    <div class="fm-menu-item-main"><span>🔀</span> <span>New Workflow DAG (YAML)...</span></div>
                </div>
                <div class="fm-menu-item" data-action="new-skill">
                    <div class="fm-menu-item-main"><span>⚡</span> <span>New Agent Skill (SKILL.md)...</span></div>
                </div>
                <div class="fm-menu-item" data-action="new-file">
                    <div class="fm-menu-item-main"><span>📄</span> <span>New Blank File...</span></div>
                </div>
                <div class="fm-menu-divider"></div>
                <div class="fm-menu-item" data-action="upload">
                    <div class="fm-menu-item-main"><span>⬆️</span> <span>Upload Assets Here...</span></div>
                </div>
                <div class="fm-menu-item" data-action="refresh">
                    <div class="fm-menu-item-main"><span>🔄</span> <span>Refresh Directory</span></div>
                </div>
            `;
        } else if (targetItem.type === 'directory') {
            // Right-click on Folder
            const fi = getFolderInfo(targetItem.name, targetItem.path);
            menu.innerHTML = `
                <div class="fm-menu-header">
                    <span>${fi.icon} ${escapeHtml(targetItem.name)}</span>
                </div>
                <div class="fm-menu-item" data-action="open-folder" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>📂</span> <span><strong>Open Folder</strong></span></div>
                    <span class="fm-menu-shortcut">Double-click</span>
                </div>
                <div class="fm-menu-item" data-action="inspect" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>🔍</span> <span>Inspect Details</span></div>
                </div>
                <div class="fm-menu-item" data-action="rename" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>✏️</span> <span>Rename Folder...</span></div>
                </div>
                <div class="fm-menu-item" data-action="copy-path" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>📋</span> <span>Copy Folder Path</span></div>
                </div>
                <div class="fm-menu-item" data-action="download" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>⬇️</span> <span>Download Folder</span></div>
                </div>
                <div class="fm-menu-divider"></div>
                <div class="fm-menu-item danger" data-action="delete" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>🗑️</span> <span>Delete Folder</span></div>
                    <span class="fm-menu-shortcut">Del</span>
                </div>
            `;
        } else {
            // Right-click on File
            const info = getFileTypeInfo(targetItem.name, false, targetItem.path);
            menu.innerHTML = `
                <div class="fm-menu-header">
                    <span>${info.icon} ${escapeHtml(targetItem.name)}</span>
                </div>
                <div class="fm-menu-item" data-action="preview-file" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>👁️</span> <span><strong>Open / Preview</strong></span></div>
                    <span class="fm-menu-shortcut">Double-click</span>
                </div>
                <div class="fm-menu-item" data-action="edit-file" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>✏️</span> <span>Edit Content</span></div>
                </div>
                <div class="fm-menu-item" data-action="download" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>⬇️</span> <span>Download File</span></div>
                </div>
                <div class="fm-menu-item" data-action="rename" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>✏️</span> <span>Rename...</span></div>
                </div>
                <div class="fm-menu-item" data-action="duplicate" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>📑</span> <span>Duplicate Asset</span></div>
                </div>
                <div class="fm-menu-item" data-action="copy-path" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>📋</span> <span>Copy Path</span></div>
                </div>
                <div class="fm-menu-divider"></div>
                <div class="fm-menu-item danger" data-action="delete" data-path="${escapeHtml(targetItem.path)}">
                    <div class="fm-menu-item-main"><span>🗑️</span> <span>Delete Asset</span></div>
                    <span class="fm-menu-shortcut">Del</span>
                </div>
            `;
        }

        menu.classList.add('active');

        // Viewport clamping
        const menuWidth = 220;
        const menuHeight = menu.offsetHeight || 260;
        let posX = e.clientX;
        let posY = e.clientY;
        if (posX + menuWidth > window.innerWidth) posX = window.innerWidth - menuWidth - 12;
        if (posY + menuHeight > window.innerHeight) posY = window.innerHeight - menuHeight - 12;
        menu.style.left = `${Math.max(10, posX)}px`;
        menu.style.top = `${Math.max(10, posY)}px`;

        menu.querySelectorAll('.fm-menu-item').forEach(item => {
            item.addEventListener('click', (ev) => {
                ev.stopPropagation();
                const action = item.dataset.action;
                const path = item.dataset.path;
                closeContextMenu();
                handleContextAction(action, path, targetItem);
            });
        });
    }

    function closeContextMenu() {
        document.getElementById('fmContextMenu')?.classList.remove('active');
    }

    async function handleContextAction(action, path, targetItem) {
        switch (action) {
            case 'open-folder':
                loadDirectory(path);
                break;
            case 'inspect':
            case 'preview-file':
                if (targetItem) inspectFile(targetItem, true);
                break;
            case 'edit-file':
                if (targetItem) {
                    await inspectFile(targetItem, true);
                    switchInlineEditor(targetItem, fmState.editorContent);
                }
                break;
            case 'download':
            case 'download-file':
                downloadFile(path);
                break;
            case 'rename':
                openRenameModal(path);
                break;
            case 'duplicate':
                duplicateAsset(path);
                break;
            case 'copy-path':
                if (path) {
                    navigator.clipboard.writeText(path);
                    showToast(`Copied path: ${path}`, 'success');
                }
                break;
            case 'delete':
                confirmDeleteItem(path);
                break;
            case 'new-folder':
                openNewFolderModal();
                break;
            case 'new-model':
                openNewFileModal('model_config', 'models');
                break;
            case 'new-design':
                openNewFileModal('agent_design', 'designs');
                break;
            case 'new-prompt':
                openNewFileModal('prompt', 'models/prompts');
                break;
            case 'new-dag':
                openNewFileModal('workflow', 'designs');
                break;
            case 'new-skill':
                openNewFileModal('skill', 'skills');
                break;
            case 'new-file':
                openNewFileModal('empty');
                break;
            case 'upload':
                openUploadModal();
                break;
            case 'refresh':
                refreshMetrics();
                loadDirectory(fmState.cwd);
                break;
        }
    }

    async function duplicateAsset(srcPath) {
        if (!srcPath) return;
        try {
            const res = await window.API.fileboxReadFile(srcPath, fmState.currentOwner, getToken());
            if (!res.data) {
                showToast(`Failed to read asset for duplication: ${res.error}`, 'error');
                return;
            }

            const parts = srcPath.split('/');
            const filename = parts.pop();
            const dir = parts.join('/');
            const dotIdx = filename.lastIndexOf('.');
            const baseName = dotIdx !== -1 ? filename.slice(0, dotIdx) : filename;
            const ext = dotIdx !== -1 ? filename.slice(dotIdx) : '';
            const newPath = (dir ? dir + '/' : '') + `${baseName}_copy${ext}`;

            const writeRes = await window.API.fileboxWriteFile(
                newPath,
                res.data.content || '',
                'Duplicate asset',
                fmState.currentOwner,
                getToken()
            );

            if (writeRes.data) {
                showToast(`Duplicated to ${newPath}`, 'success');
                broadcastWsEvent('duplicate', newPath);
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            } else {
                showToast(`Duplication failed: ${writeRes.error}`, 'error');
            }
        } catch (e) {
            showToast(`Duplication error: ${e.message}`, 'error');
        }
    }

    // ── Breadcrumbs ─────────────────────────────────────────────────────────

    function renderBreadcrumbs() {
        const bcEl = document.getElementById('fmBreadcrumbs');
        if (!bcEl) return;

        const parts = fmState.cwd ? fmState.cwd.split('/') : [];
        let html = `
            <span class="fm-breadcrumb-item ${!parts.length ? 'active' : ''}" data-path="">
                📦 Root
            </span>
        `;

        let acc = '';
        parts.forEach((p, idx) => {
            acc += (idx === 0 ? '' : '/') + p;
            const isLast = idx === parts.length - 1;
            html += `
                <span class="fm-breadcrumb-sep">/</span>
                <span class="fm-breadcrumb-item ${isLast ? 'active' : ''}" data-path="${escapeHtml(acc)}">
                    ${escapeHtml(p)}
                </span>
            `;
        });

        bcEl.innerHTML = html;

        bcEl.querySelectorAll('.fm-breadcrumb-item').forEach(item => {
            item.addEventListener('click', () => {
                const targetPath = item.dataset.path;
                if (targetPath !== fmState.cwd) {
                    loadDirectory(targetPath);
                }
            });
        });

        const upBtn = document.getElementById('btnFmUpLevel');
        if (upBtn) {
            upBtn.disabled = !fmState.cwd;
            upBtn.onclick = () => {
                if (fmState.cwd) {
                    loadDirectory(getParentDir(fmState.cwd));
                }
            };
        }
    }

    // ── Batch Action Bar ────────────────────────────────────────────────────

    function updateBatchBar() {
        const bar = document.getElementById('fmBatchBar');
        const countText = document.getElementById('fmBatchCountText');
        const selectAllCb = document.getElementById('fmSelectAllCheckbox');
        if (!bar) return;

        const count = fmState.selectedPaths.size;
        if (count > 0) {
            bar.classList.add('active');
            if (countText) countText.textContent = `${count} ${count === 1 ? 'item' : 'items'} selected`;
        } else {
            bar.classList.remove('active');
        }

        if (selectAllCb) {
            const allItemsCount = fmState.items.length;
            selectAllCb.checked = allItemsCount > 0 && count === allItemsCount;
            selectAllCb.indeterminate = count > 0 && count < allItemsCount;
        }
    }

    // ── File Inspector & In-Place Preview ───────────────────────────────────

    async function inspectFile(item, openFull = false) {
        fmState.activeFile = item;
        const inspector = document.getElementById('fmInspector');
        if (!inspector) return;

        inspector.classList.remove('closed');
        const isDir = item.type === 'directory';
        const info = getFileTypeInfo(item.name, isDir, item.path);

        const titleEl = document.getElementById('fmInspectorTitle');
        if (titleEl) {
            titleEl.innerHTML = `<span style="color:${info.color};font-size:16px;">${info.icon}</span> <span>${escapeHtml(item.name)}</span>`;
        }

        const bodyEl = document.getElementById('fmInspectorBody');
        if (!bodyEl) return;

        if (isDir) {
            const folderMeta = getFolderInfo(item.name, item.path);
            bodyEl.innerHTML = `
                <div style="background:var(--surface-raised);padding:14px;border-radius:var(--radius-md);border:1px solid var(--border);text-align:center;">
                    <div style="font-size:36px;margin-bottom:6px;">${folderMeta.icon}</div>
                    <div style="font-weight:700;font-size:15px;color:var(--fg);">${escapeHtml(item.name)}</div>
                    <div style="font-size:12px;color:var(--fg-muted);margin-top:2px;">${escapeHtml(folderMeta.desc)}</div>
                </div>
                <div class="fm-meta-table">
                    <table>
                        <tr><td>Type</td><td>AI Agent Directory</td></tr>
                        <tr><td>Category</td><td><span class="fm-asset-chip ${folderMeta.badgeClass}">${escapeHtml(folderMeta.badge)}</span></td></tr>
                        <tr><td>Path</td><td style="font-family:var(--font-mono);font-size:11px;">${escapeHtml(item.path)}</td></tr>
                        <tr><td>Permissions</td><td><span style="color:var(--success);">Read-Write</span></td></tr>
                    </table>
                </div>
                <div style="display:flex;flex-direction:column;gap:8px;margin-top:10px;">
                    <button class="btn btn-primary btn-sm" id="btnInspectOpenFolder">↗ Enter Folder</button>
                    <button class="btn btn-ghost btn-sm" id="btnInspectRenameFolder">✏ Rename Folder</button>
                    <button class="btn btn-ghost btn-sm" style="color:var(--danger);" id="btnInspectDeleteFolder">🗑 Delete Folder</button>
                </div>
            `;
            document.getElementById('btnInspectOpenFolder')?.addEventListener('click', () => loadDirectory(item.path));
            document.getElementById('btnInspectRenameFolder')?.addEventListener('click', () => openRenameModal(item.path));
            document.getElementById('btnInspectDeleteFolder')?.addEventListener('click', () => confirmDeleteItem(item.path));
            return;
        }

        // Fetch file content
        bodyEl.innerHTML = `
            <div style="padding:20px;text-align:center;color:var(--fg-muted);font-size:12px;">
                <span class="spinner" style="display:inline-block;margin-right:6px;"></span> Loading AI asset metadata &amp; preview...
            </div>
        `;

        try {
            const res = await window.API.fileboxReadFile(item.path, fmState.currentOwner, getToken());
            if (res.data) {
                renderFileInspectorContent(item, res.data);
            } else {
                bodyEl.innerHTML = `<div style="padding:16px;color:var(--danger);font-size:12.5px;">Failed to read asset: ${escapeHtml(res.error)}</div>`;
            }
        } catch (e) {
            bodyEl.innerHTML = `<div style="padding:16px;color:var(--danger);font-size:12.5px;">Error loading asset: ${escapeHtml(e.message)}</div>`;
        }
    }

    function renderFileInspectorContent(item, fileData) {
        const bodyEl = document.getElementById('fmInspectorBody');
        if (!bodyEl) return;

        const isBinary = fileData.encoding === 'base64';
        const isMarkdown = item.name.endsWith('.md') || item.name.endsWith('.markdown');
        const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(item.name);
        const isJson = item.name.endsWith('.json');
        const isYaml = item.name.endsWith('.yaml') || item.name.endsWith('.yml');
        const isReadOnly = item.path?.startsWith('identity/') || item.name === 'filebox.yaml';
        const sizeFormatted = formatBytes(fileData.size || (fileData.content ? fileData.content.length : 0));
        const contentText = fileData.content || '';
        const info = getFileTypeInfo(item.name, false, item.path);

        fmState.editorContent = contentText;
        fmState.inlineEditMode = false;
        fmState.editorDirty = false;

        let previewHtml = '';

        // AI Model Parameter Highlights
        let modelParamsHtml = '';
        if (info.isModel && (isYaml || isJson)) {
            modelParamsHtml = `
                <div style="background:var(--surface-raised);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border);display:flex;flex-wrap:wrap;gap:6px;">
                    <span class="fm-asset-chip model">64K Context</span>
                    <span class="fm-asset-chip model">Temp: 0.2</span>
                    <span class="fm-asset-chip model">Q4_K_M Quant</span>
                    <span class="fm-asset-chip model">Tool-Calling ✓</span>
                </div>
            `;
        }

        if (isImage) {
            const rawUrl = `/v1/filebox/browse/raw?path=${encodeURIComponent(item.path)}${fmState.currentOwner ? '&owner=' + encodeURIComponent(fmState.currentOwner) : ''}`;
            previewHtml = `
                <div class="fm-preview-box">
                    <div class="fm-preview-header">
                        <span>Image / Architecture Preview</span>
                        <span>${escapeHtml(fileData.mime || 'image')}</span>
                    </div>
                    <div class="fm-preview-image">
                        <img src="${rawUrl}" alt="${escapeHtml(item.name)}" />
                    </div>
                </div>
            `;
        } else if (isMarkdown) {
            previewHtml = `
                <div class="fm-preview-box">
                    <div class="fm-preview-header">
                        <span>Design Document Preview</span>
                        <button class="btn btn-ghost btn-sm" id="btnFmToggleEditor" style="padding:1px 6px;font-size:11px;">✏️ Edit</button>
                    </div>
                    <div id="fmInspectorPreviewArea">
                        ${renderMarkdown(contentText)}
                    </div>
                </div>
            `;
        } else if (isJson) {
            let prettyJson = contentText;
            try {
                prettyJson = JSON.stringify(JSON.parse(contentText), null, 2);
            } catch {}
            previewHtml = `
                <div class="fm-preview-box">
                    <div class="fm-preview-header">
                        <span>Architecture JSON Spec</span>
                        <button class="btn btn-ghost btn-sm" id="btnFmToggleEditor" style="padding:1px 6px;font-size:11px;">✏️ Edit</button>
                    </div>
                    <div id="fmInspectorPreviewArea" class="fm-preview-content">${escapeHtml(prettyJson)}</div>
                </div>
            `;
        } else if (!isBinary) {
            const lines = contentText.split('\n');
            const numberedLines = lines.map((l, idx) => `<span style="color:var(--fg-subtle);margin-right:8px;user-select:none;">${idx + 1}</span>${escapeHtml(l)}`).join('\n');
            previewHtml = `
                <div class="fm-preview-box">
                    <div class="fm-preview-header">
                        <span>Code / Spec Preview (${lines.length} lines)</span>
                        <div style="display:flex;gap:4px;">
                            <button class="btn btn-ghost btn-sm" id="btnFmCopyContent" style="padding:1px 6px;font-size:11px;" title="Copy content">📋 Copy</button>
                            <button class="btn btn-ghost btn-sm" id="btnFmToggleEditor" style="padding:1px 6px;font-size:11px;" title="Edit inline">✏️ Edit</button>
                        </div>
                    </div>
                    <div id="fmInspectorPreviewArea" class="fm-preview-content">${numberedLines}</div>
                </div>
            `;
        } else {
            previewHtml = `
                <div class="fm-preview-box" style="padding:20px;text-align:center;color:var(--fg-muted);">
                    <div style="font-size:32px;margin-bottom:8px;">⚖️</div>
                    <div style="font-weight:600;color:var(--fg);">Model Weights / Binary Asset</div>
                    <div style="font-size:11.5px;margin-top:4px;">Raw model weights or dataset (${sizeFormatted})</div>
                </div>
            `;
        }

        bodyEl.innerHTML = `
            ${modelParamsHtml}

            <!-- Metadata Summary -->
            <table class="fm-meta-table">
                <tr><td>Asset Type</td><td><span class="fm-asset-chip ${info.isModel ? 'model' : info.isDesign ? 'design' : 'skill'}">${escapeHtml(info.label)}</span></td></tr>
                <tr><td>Location</td><td style="font-family:var(--font-mono);font-size:11px;">${escapeHtml(item.path)}</td></tr>
                <tr><td>Size</td><td>${sizeFormatted}</td></tr>
                <tr><td>Permissions</td><td>${isReadOnly ? '<span style="color:var(--danger);">Read-Only</span>' : '<span style="color:var(--success);">Read-Write</span>'}</td></tr>
                <tr><td>Agent Context</td><td>${escapeHtml(fmState.currentOwner || 'agent')}</td></tr>
            </table>

            <!-- Quick Action Strip in Inspector -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <button class="btn btn-ghost btn-sm" id="btnInspectorDownload">⬇ Download</button>
                <button class="btn btn-ghost btn-sm" id="btnInspectorCopyPath">📋 Copy Path</button>
                <button class="btn btn-ghost btn-sm" id="btnInspectorRename">✏ Rename</button>
                <button class="btn btn-ghost btn-sm" style="color:var(--danger);" id="btnInspectorDelete">🗑 Delete</button>
            </div>

            <!-- In-place Preview / Editor Box -->
            ${previewHtml}
        `;

        document.getElementById('btnInspectorDownload')?.addEventListener('click', () => downloadFile(item.path));
        document.getElementById('btnInspectorCopyPath')?.addEventListener('click', () => {
            navigator.clipboard.writeText(item.path);
            showToast(`Copied path: ${item.path}`, 'success');
        });
        document.getElementById('btnInspectorRename')?.addEventListener('click', () => openRenameModal(item.path));
        document.getElementById('btnInspectorDelete')?.addEventListener('click', () => confirmDeleteItem(item.path));

        document.getElementById('btnFmCopyContent')?.addEventListener('click', () => {
            navigator.clipboard.writeText(contentText);
            showToast('Asset content copied to clipboard!', 'success');
        });

        document.getElementById('btnFmToggleEditor')?.addEventListener('click', () => {
            switchInlineEditor(item, contentText);
        });
    }

    function switchInlineEditor(item, currentContent) {
        const previewArea = document.getElementById('fmInspectorPreviewArea');
        const toggleBtn = document.getElementById('btnFmToggleEditor');
        if (!previewArea) return;

        if (!fmState.inlineEditMode) {
            fmState.inlineEditMode = true;
            if (toggleBtn) toggleBtn.textContent = '👁️ Preview';

            previewArea.innerHTML = `
                <div style="display:flex;flex-direction:column;gap:6px;padding:8px;">
                    <textarea id="fmInlineTextarea" style="width:100%;height:220px;background:var(--surface);border:1px solid var(--border);border-radius:4px;color:var(--fg);font-family:var(--font-mono);font-size:12px;padding:8px;resize:vertical;outline:none;" spellcheck="false">${escapeHtml(currentContent)}</textarea>
                    <div style="display:flex;align-items:center;justify-content:space-between;">
                        <span id="fmInlineDirtyStatus" style="font-size:11px;color:var(--fg-muted);">Unsaved modifications</span>
                        <button class="btn btn-primary btn-sm" id="btnSaveInlineEdit" style="padding:3px 10px;">💾 Save Asset</button>
                    </div>
                </div>
            `;

            const ta = document.getElementById('fmInlineTextarea');
            const saveBtn = document.getElementById('btnSaveInlineEdit');

            ta?.addEventListener('input', () => {
                fmState.editorDirty = true;
            });

            ta?.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    saveInlineFile(item.path, ta.value);
                }
            });

            saveBtn?.addEventListener('click', () => {
                if (ta) saveInlineFile(item.path, ta.value);
            });
        } else {
            fmState.inlineEditMode = false;
            if (toggleBtn) toggleBtn.textContent = '✏️ Edit';
            inspectFile(item);
        }
    }

    async function saveInlineFile(path, newContent) {
        const saveBtn = document.getElementById('btnSaveInlineEdit');
        if (saveBtn) saveBtn.disabled = true;

        try {
            const res = await window.API.fileboxWriteFile(
                path,
                newContent,
                'Model & Design Management edit',
                fmState.currentOwner,
                getToken()
            );
            if (res.data) {
                showToast(`Saved ${path}`, 'success');
                fmState.editorDirty = false;
                const statusEl = document.getElementById('fmInlineDirtyStatus');
                if (statusEl) {
                    statusEl.textContent = '✓ Saved successfully';
                    statusEl.style.color = 'var(--success)';
                }
                broadcastWsEvent('write', path);
                await refreshMetrics();
            } else {
                showToast(`Save failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Save error: ${e.message}`, 'error');
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    function downloadFile(path) {
        if (!path) return;
        const rawUrl = `/v1/filebox/browse/raw?path=${encodeURIComponent(path)}${fmState.currentOwner ? '&owner=' + encodeURIComponent(fmState.currentOwner) : ''}`;
        const a = document.createElement('a');
        a.href = rawUrl;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ── Modals & File System Actions ────────────────────────────────────────

    function openNewFileModal(presetTemplate = 'empty', presetDir = null) {
        closeContextMenu();
        const modal = document.getElementById('fmNewFileModal');
        if (!modal) return;
        const targetDirInput = document.getElementById('fmNewFileDir');
        if (targetDirInput) {
            targetDirInput.value = presetDir !== null ? presetDir : (fmState.cwd ? fmState.cwd + '/' : '');
        }

        const nameInput = document.getElementById('fmNewFileName');
        const tplSelect = document.getElementById('fmNewFileTemplate');

        if (tplSelect) tplSelect.value = presetTemplate;

        if (presetTemplate === 'model_config') {
            if (nameInput) nameInput.value = 'model_config.yaml';
        } else if (presetTemplate === 'agent_design') {
            if (nameInput) nameInput.value = 'agent_architecture.json';
        } else if (presetTemplate === 'prompt') {
            if (nameInput) nameInput.value = 'system_prompt.md';
        } else if (presetTemplate === 'workflow') {
            if (nameInput) nameInput.value = 'workflow_dag.yaml';
        } else if (presetTemplate === 'skill') {
            if (nameInput) nameInput.value = 'SKILL.md';
        } else {
            if (nameInput) nameInput.value = '';
        }

        modal.classList.add('active');
        nameInput?.focus();
    }

    function openNewFolderModal() {
        closeContextMenu();
        const modal = document.getElementById('fmNewFolderModal');
        if (!modal) return;
        const targetDirInput = document.getElementById('fmNewFolderDir');
        if (targetDirInput) targetDirInput.value = fmState.cwd ? fmState.cwd + '/' : '';
        document.getElementById('fmNewFolderName').value = '';
        modal.classList.add('active');
        document.getElementById('fmNewFolderName')?.focus();
    }

    function openUploadModal() {
        closeContextMenu();
        const modal = document.getElementById('fmUploadModal');
        if (!modal) return;
        const targetDirInput = document.getElementById('fmUploadTargetDir');
        if (targetDirInput) targetDirInput.value = fmState.cwd ? fmState.cwd + '/' : 'Root (/)';
        const fileInput = document.getElementById('fmUploadFileInput');
        if (fileInput) fileInput.value = '';
        document.getElementById('fmUploadFileList').innerHTML = '';
        modal.classList.add('active');
    }

    function openRenameModal(oldPath) {
        closeContextMenu();
        const modal = document.getElementById('fmRenameModal');
        if (!modal) return;
        document.getElementById('fmRenameSrcPath').value = oldPath;
        document.getElementById('fmRenameNewPath').value = oldPath;
        modal.classList.add('active');
        const input = document.getElementById('fmRenameNewPath');
        if (input) {
            input.focus();
            input.select();
        }
    }

    function closeModal(id) {
        document.getElementById(id)?.classList.remove('active');
    }

    async function submitCreateFile() {
        const dir = (document.getElementById('fmNewFileDir')?.value || '').trim();
        const filename = (document.getElementById('fmNewFileName')?.value || '').trim();
        const tpl = document.getElementById('fmNewFileTemplate')?.value || 'empty';

        if (!filename) {
            showToast('Please enter a valid filename', 'warn');
            return;
        }

        const fullPath = (dir ? dir.replace(/\/+$/, '') + '/' : '') + filename.replace(/^\/+/, '');

        let content = '';
        if (tpl === 'model_config') {
            content = `model_id: "deepseek-coder-v2"\nprovider: "thinkdome-local"\ncontext_window: 65536\ntemperature: 0.2\ntop_p: 0.95\nquantization: "Q4_K_M"\nsystem_instruction_ref: "models/prompts/system_prompt.md"\ncapabilities:\n  - code_generation\n  - tool_use\n  - rag_search\n`;
        } else if (tpl === 'agent_design') {
            content = `{\n  "system_name": "Autonomous Agent Core",\n  "version": "2.4.0",\n  "architecture": {\n    "orchestrator": "ThinkDome LLM Gateway",\n    "memory_layer": "Persistent SQLite + Vector Chunks",\n    "sandbox_runtime": "Isolated Container Runtime",\n    "tool_protocol": "Model Context Protocol (MCP)"\n  },\n  "execution_flow": [\n    "Prompt Ingestion",\n    "Policy Enforcement",\n    "DAG Resolution",\n    "Tool Invocation",\n    "Output Validation"\n  ]\n}\n`;
        } else if (tpl === 'workflow') {
            content = `name: "agent_code_generation_dag"\nversion: "1.0"\ntrigger: "user_task_request"\nsteps:\n  - id: "analyze"\n    action: "analyze_requirements"\n    next: "plan"\n  - id: "plan"\n    action: "generate_implementation_plan"\n    next: "execute"\n  - id: "execute"\n    action: "execute_sandboxed_code"\n    next: "verify"\n  - id: "verify"\n    action: "run_test_suite"\n`;
        } else if (tpl === 'prompt') {
            content = `# Autonomous AI Agent System Prompt\n\n## Role & Mission\nYou are ThinkDome Autonomous AI Engineer, executing resilient software engineering, model orchestration, and architectural design.\n\n## Operating Principles\n1. Verify before executing destructive commands.\n2. Produce structured, typed, self-documenting code.\n3. Adhere to RBAC and principle of least privilege.\n`;
        } else if (tpl === 'skill') {
            content = `---\nname: my_agent_skill\nversion: "1.0"\ndescription: Autonomous capability specification\nenabled: true\ntags: [ai, automation, tool]\ntriggers: [execute, run, inspect]\n---\n\n# Agent Skill Specification\n\n## Workflow\n1. Step 1: Input preparation\n2. Step 2: Tool execution\n3. Step 3: Result validation\n`;
        } else if (tpl === 'dataset') {
            content = `{"messages": [{"role": "system", "content": "You are a helpful coding assistant."}, {"role": "user", "content": "Write quicksort in Python."}, {"role": "assistant", "content": "def quicksort(arr):\\n    if len(arr) <= 1: return arr\\n    pivot = arr[len(arr) // 2]\\n    left = [x for x in arr if x < pivot]\\n    middle = [x for x in arr if x == pivot]\\n    right = [x for x in arr if x > pivot]\\n    return quicksort(left) + middle + quicksort(right)"}]}\n`;
        } else if (tpl === 'tool_python') {
            content = `"""\n${filename} — Agent Tool Implementation.\n"""\n\nfrom pydantic import BaseModel, Field\n\nclass ToolInput(BaseModel):\n    query: str = Field(description="Search parameter")\n\ndef run(input_data: ToolInput) -> dict:\n    return {"status": "success", "result": f"Processed {input_data.query}"}\n`;
        }

        try {
            const res = await window.API.fileboxWriteFile(
                fullPath,
                content,
                'Model & Design Management create',
                fmState.currentOwner,
                getToken()
            );
            if (res.data) {
                showToast(`Created ${fullPath}`, 'success');
                closeModal('fmNewFileModal');
                broadcastWsEvent('create', fullPath);
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            } else {
                showToast(`Creation failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Creation error: ${e.message}`, 'error');
        }
    }

    async function submitCreateFolder() {
        const dir = (document.getElementById('fmNewFolderDir')?.value || '').trim();
        const folderName = (document.getElementById('fmNewFolderName')?.value || '').trim();

        if (!folderName) {
            showToast('Please enter a valid folder name', 'warn');
            return;
        }

        const fullPath = (dir ? dir.replace(/\/+$/, '') + '/' : '') + folderName.replace(/^\/+/, '');

        try {
            const res = await window.API.fileboxMkdir(fullPath, fmState.currentOwner, getToken());
            if (res.data) {
                showToast(`Created folder ${fullPath}`, 'success');
                closeModal('fmNewFolderModal');
                broadcastWsEvent('mkdir', fullPath);
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            } else {
                showToast(`Folder creation failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Folder error: ${e.message}`, 'error');
        }
    }

    async function submitRename() {
        const src = (document.getElementById('fmRenameSrcPath')?.value || '').trim();
        const dst = (document.getElementById('fmRenameNewPath')?.value || '').trim();

        if (!dst || src === dst) {
            closeModal('fmRenameModal');
            return;
        }

        try {
            const res = await window.API.fileboxMove(src, dst, 'Rename item', fmState.currentOwner, getToken());
            if (res.data) {
                showToast(`Renamed to ${dst}`, 'success');
                closeModal('fmRenameModal');
                broadcastWsEvent('move', dst);
                if (fmState.activeFile && fmState.activeFile.path === src) {
                    fmState.activeFile.path = dst;
                    fmState.activeFile.name = dst.split('/').pop();
                }
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            } else {
                showToast(`Rename failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Rename error: ${e.message}`, 'error');
        }
    }

    async function confirmDeleteItem(path) {
        if (!confirm(`Are you sure you want to permanently delete "${path}"?`)) return;

        try {
            const res = await window.API.fileboxDelete(path, 'Delete item', fmState.currentOwner, getToken());
            if (res.data) {
                showToast(`Deleted ${path}`, 'success');
                broadcastWsEvent('delete', path);
                if (fmState.activeFile && fmState.activeFile.path === path) {
                    fmState.activeFile = null;
                    document.getElementById('fmInspector')?.classList.add('closed');
                }
                await refreshMetrics();
                await loadDirectory(fmState.cwd);
            } else {
                showToast(`Delete failed: ${res.error}`, 'error');
            }
        } catch (e) {
            showToast(`Delete error: ${e.message}`, 'error');
        }
    }

    async function batchDeleteSelected() {
        const count = fmState.selectedPaths.size;
        if (!count) return;
        if (!confirm(`Are you sure you want to delete ${count} selected items?`)) return;

        let success = 0;
        for (const path of fmState.selectedPaths) {
            try {
                const res = await window.API.fileboxDelete(path, 'Batch delete', fmState.currentOwner, getToken());
                if (res.data) success++;
            } catch (e) {
                console.error(`Failed to delete ${path}:`, e);
            }
        }

        showToast(`Deleted ${success} of ${count} items`, 'success');
        broadcastWsEvent('batch_delete', fmState.cwd);
        fmState.selectedPaths.clear();
        await refreshMetrics();
        await loadDirectory(fmState.cwd);
    }

    function batchDownloadSelected() {
        const count = fmState.selectedPaths.size;
        if (!count) return;
        fmState.selectedPaths.forEach(path => {
            downloadFile(path);
        });
        showToast(`Triggered download for ${count} assets`, 'info');
    }

    async function handleFilesUpload(fileList) {
        if (!fileList || !fileList.length) return;
        showToast(`Uploading ${fileList.length} files...`, 'info');

        let successCount = 0;
        for (const file of fileList) {
            const targetPath = (fmState.cwd ? fmState.cwd.replace(/\/+$/, '') + '/' : '') + file.name;
            try {
                const isText = /\.(txt|md|py|js|ts|json|yaml|yml|html|css|sh|csv|sql|env|prompt|mermaid)$/i.test(file.name);
                if (isText) {
                    const text = await file.text();
                    const res = await window.API.fileboxWriteFile(targetPath, text, 'Uploaded via Model & Design Manager', fmState.currentOwner, getToken());
                    if (res.data) successCount++;
                } else {
                    const buffer = await file.arrayBuffer();
                    let binary = '';
                    const bytes = new Uint8Array(buffer);
                    const len = bytes.byteLength;
                    for (let i = 0; i < len; i++) {
                        binary += String.fromCharCode(bytes[i]);
                    }
                    const base64 = btoa(binary);
                    const res = await window.API.fileboxWriteBinary(targetPath, base64, 'Binary upload via Model & Design Manager', fmState.currentOwner, getToken());
                    if (res.data) successCount++;
                }
            } catch (err) {
                console.error(`Failed upload of ${file.name}:`, err);
            }
        }

        showToast(`Successfully uploaded ${successCount} assets`, 'success');
        broadcastWsEvent('upload', fmState.cwd);
        closeModal('fmUploadModal');
        await refreshMetrics();
        await loadDirectory(fmState.cwd);
    }

    // ── Layout Setup ────────────────────────────────────────────────────────

    function setupUI() {
        const page = document.getElementById('page-filemanager');
        if (!page || page.dataset.initialized) return;
        page.dataset.initialized = 'true';

        page.innerHTML = `
            <!-- Top Header & Workstation Controls -->
            <div class="fm-page-head">
                <div class="fm-page-title-group">
                    <div class="fm-title-badge-row">
                        <span class="fm-studio-badge">AI AGENT STUDIO</span>
                        <!-- Live WebSocket Status Pill Badge -->
                        <div class="fm-ws-status disconnected" id="fmWsStatusPill" title="Connecting to ThinkDome WebSocket gateway... (Click to reconnect)">
                            <span class="fm-ws-dot"></span>
                            <span id="fmWsStatusText">Connecting WS...</span>
                        </div>
                    </div>
                    <h1>
                        <span class="fm-title-icon">🧠</span>
                        <span>Model &amp; Design Management</span>
                    </h1>
                    <p class="fm-page-desc">Authentic OS folder workstation for AI agent models, architectural designs, prompts, and skills</p>
                </div>
                <div class="fm-page-actions">
                    <div id="fmUserSelectorContainer"></div>

                    <div class="fm-action-group">
                        <button class="btn btn-primary btn-sm fm-btn-accent" id="btnFmNewModel" title="Create LLM Model Specification">
                            <span>🧠</span> <span>+ Model Spec</span>
                        </button>
                        <button class="btn btn-secondary btn-sm fm-btn-design" id="btnFmNewDesign" title="Create System Architecture Design">
                            <span>📐</span> <span>+ System Design</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btnFmNewFolder" title="Create new directory">
                            <span>📁</span> <span>+ Folder</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btnFmNewFile" title="Create blank or templated asset">
                            <span>📄</span> <span>+ File</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btnFmUpload" title="Upload files to current folder">
                            <span>⬆</span> <span>Upload</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btnFmRefresh" title="Refresh folder assets">
                            <span>↻</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Sleek Telemetry / Status Strip (Maximizes File Explorer Screen Real Estate) -->
            <div class="fm-telemetry-strip">
                <div class="fm-telemetry-pill">
                    <span class="fm-telemetry-icon">📦</span>
                    <span class="fm-telemetry-label">Total Assets:</span>
                    <strong class="fm-telemetry-val" id="fmMetricTotalFiles">0</strong>
                </div>
                <div class="fm-telemetry-sep"></div>
                <div class="fm-telemetry-pill">
                    <span class="fm-telemetry-icon">📁</span>
                    <span class="fm-telemetry-label">Folders in CWD:</span>
                    <strong class="fm-telemetry-val" id="fmMetricTotalDirs">0</strong>
                    <span class="fm-telemetry-sub" id="fmCurrentFolderCount">0 items</span>
                </div>
                <div class="fm-telemetry-sep"></div>
                <div class="fm-telemetry-pill">
                    <span class="fm-telemetry-icon">💾</span>
                    <span class="fm-telemetry-label">Storage:</span>
                    <strong class="fm-telemetry-val" id="fmMetricStorageSize">0 KB</strong>
                    <div class="fm-telemetry-bar-wrap" title="Storage Quota">
                        <div class="fm-usage-bar-bg">
                            <div class="fm-usage-bar-fill" id="fmStorageBar" style="width:1%;"></div>
                        </div>
                        <span class="fm-telemetry-sub" id="fmMetricStorageQuota">0%</span>
                    </div>
                </div>
                <div class="fm-telemetry-sep"></div>
                <div class="fm-telemetry-pill">
                    <span class="fm-telemetry-icon">⚡</span>
                    <span class="fm-telemetry-label">Agent Engine:</span>
                    <span class="fm-telemetry-val" style="color:var(--success);font-weight:600;">FTS5 Vector Active</span>
                </div>
            </div>

            <!-- Multi-Column Workstation -->
            <div class="fm-workstation" id="fmDropTarget">
                <!-- Dropzone Overlay -->
                <div class="fm-dropzone-overlay" id="fmDropzoneOverlay">
                    <div style="font-size:48px;margin-bottom:12px;">📥</div>
                    <div style="font-size:18px;font-weight:700;">Drop model or design files here</div>
                    <div style="font-size:13px;opacity:0.8;margin-top:4px;">Uploads directly into current folder</div>
                </div>

                <!-- Left Sidebar Navigation -->
                <div class="fm-sidebar">
                    <div class="fm-sidebar-group">
                        <div class="fm-sidebar-title">AI Agent Drives</div>
                        <button class="fm-nav-btn active" data-loc="">
                            <span class="fm-nav-icon">📦</span>
                            <span>Root Filesystem</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="models">
                            <span class="fm-nav-icon">🧠</span>
                            <span>Models &amp; Weights</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="designs">
                            <span class="fm-nav-icon">📐</span>
                            <span>System Designs</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="models/prompts">
                            <span class="fm-nav-icon">🤖</span>
                            <span>Prompts &amp; Personas</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="skills">
                            <span class="fm-nav-icon">⚡</span>
                            <span>Agent Skills</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="knowledge">
                            <span class="fm-nav-icon">📚</span>
                            <span>RAG Knowledge</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="memory">
                            <span class="fm-nav-icon">💾</span>
                            <span>Memory Store</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="workspace">
                            <span class="fm-nav-icon">💼</span>
                            <span>Workspace Projects</span>
                        </button>
                        <button class="fm-nav-btn" data-loc="config">
                            <span class="fm-nav-icon">⚙️</span>
                            <span>Config &amp; Permissions</span>
                        </button>
                    </div>

                    <div class="fm-sidebar-group">
                        <div class="fm-sidebar-title">Asset Filters</div>
                        <button class="fm-nav-btn active" data-filter="all">
                            <span class="fm-nav-icon">🌟</span>
                            <span>All Assets</span>
                        </button>
                        <button class="fm-nav-btn" data-filter="models">
                            <span class="fm-nav-icon">🧠</span>
                            <span>Models &amp; Weights</span>
                        </button>
                        <button class="fm-nav-btn" data-filter="designs">
                            <span class="fm-nav-icon">📐</span>
                            <span>Designs &amp; DAGs</span>
                        </button>
                        <button class="fm-nav-btn" data-filter="prompts">
                            <span class="fm-nav-icon">🤖</span>
                            <span>Prompts &amp; Personas</span>
                        </button>
                        <button class="fm-nav-btn" data-filter="skills">
                            <span class="fm-nav-icon">⚡</span>
                            <span>Skills &amp; MCP</span>
                        </button>
                        <button class="fm-nav-btn" data-filter="data">
                            <span class="fm-nav-icon">📊</span>
                            <span>Datasets &amp; RAG</span>
                        </button>
                    </div>

                    <!-- Storage Summary Card Widget -->
                    <div class="fm-storage-widget">
                        <div style="display:flex;justify-content:space-between;font-size:11.5px;font-weight:600;color:var(--fg);">
                            <span>Volume Quota</span>
                            <span id="fmSidebarStorageText">0 KB / 1.0 GB</span>
                        </div>
                        <div class="fm-usage-bar-bg">
                            <div class="fm-usage-bar-fill" id="fmSidebarStorageBar" style="width:1%;"></div>
                        </div>
                        <div style="font-size:10.5px;color:var(--fg-subtle);margin-top:2px;">
                            Autonomous agent persistent storage
                        </div>
                    </div>
                </div>

                <!-- Center Explorer -->
                <div class="fm-explorer" id="fmExplorer">
                    <!-- Toolbar (Breadcrumbs + Controls) -->
                    <div class="fm-toolbar">
                        <div style="display:flex;align-items:center;gap:8px;min-width:0;flex:1;">
                            <button class="btn btn-ghost btn-sm" id="btnFmToggleSidebar" title="Toggle Sidebar (Maximize Canvas Space)" style="padding:4px 8px;font-size:12px;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/></svg>
                            </button>
                            <button class="btn btn-ghost btn-sm" id="btnFmUpLevel" title="Up to parent folder" style="padding:4px 8px;font-size:12px;">
                                ↑ Up
                            </button>
                            <div class="fm-breadcrumbs" id="fmBreadcrumbs"></div>
                        </div>

                        <div class="fm-explorer-controls">
                            <!-- Quick Category Filter Chips -->
                            <div class="fm-quick-filters" id="fmQuickFilters">
                                <button class="fm-filter-chip active" data-filter="all">All</button>
                                <button class="fm-filter-chip" data-filter="models">🧠 Models</button>
                                <button class="fm-filter-chip" data-filter="designs">📐 Designs</button>
                                <button class="fm-filter-chip" data-filter="prompts">🤖 Prompts</button>
                                <button class="fm-filter-chip" data-filter="skills">⚡ Skills</button>
                                <button class="fm-filter-chip" data-filter="data">📊 Datasets</button>
                            </div>

                            <!-- Search -->
                            <div class="fm-search-wrap">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                                <input type="text" id="fmSearchInput" class="fm-search-input" placeholder="Search models, designs..." />
                            </div>

                            <!-- Sort Selector -->
                            <select id="fmSortSelect" class="form-input" style="padding:4px 8px;font-size:12px;height:28px;">
                                <option value="name:asc">Name (A-Z)</option>
                                <option value="name:desc">Name (Z-A)</option>
                                <option value="size:desc">Size (Largest)</option>
                                <option value="size:asc">Size (Smallest)</option>
                                <option value="date:desc">Date (Newest)</option>
                                <option value="date:asc">Date (Oldest)</option>
                                <option value="type:asc">Asset Type</option>
                            </select>

                            <!-- View Switcher -->
                            <div class="fm-view-switcher">
                                <button class="fm-view-btn active" id="btnFmViewGrid" title="Desktop icons view">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                                </button>
                                <button class="fm-view-btn" id="btnFmViewTable" title="Detailed list view">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Batch Selection Bar -->
                    <div class="fm-batch-bar" id="fmBatchBar">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span id="fmBatchCountText">0 items selected</span>
                            <button class="btn btn-ghost btn-sm" id="btnFmDeselectAll" style="padding:2px 8px;font-size:11px;color:#cbd5e1;">Deselect All</button>
                        </div>
                        <div class="fm-batch-actions">
                            <button class="btn btn-ghost btn-sm" id="btnFmBatchDownload" style="padding:4px 10px;font-size:12px;color:#38bdf8;">⬇ Download Batch</button>
                            <button class="btn btn-ghost btn-sm" id="btnFmBatchDelete" style="padding:4px 10px;font-size:12px;color:#f87171;">🗑 Delete Batch</button>
                        </div>
                    </div>

                    <!-- Authentic Folder & File Canvas -->
                    <div class="fm-canvas" id="fmCanvas" tabindex="0"></div>
                </div>

                <!-- Right Inspector Drawer -->
                <div class="fm-inspector closed" id="fmInspector">
                    <div class="fm-inspector-head">
                        <div class="fm-inspector-title" id="fmInspectorTitle">
                            <span>Asset Details</span>
                        </div>
                        <button class="btn btn-ghost btn-sm" id="btnFmCloseInspector" style="padding:2px 6px;">✕</button>
                    </div>
                    <div class="fm-inspector-body" id="fmInspectorBody">
                        <div style="color:var(--fg-muted);font-size:12px;text-align:center;padding:20px;">
                            Select or right-click any model, design, or folder to inspect specifications, parameters, and live previews.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Authentic Desktop Right-Click Context Menu -->
            <div class="fm-context-menu" id="fmContextMenu"></div>

            <!-- Modals -->
            <!-- 1. New File Modal -->
            <div class="fm-modal" id="fmNewFileModal">
                <div class="fm-modal-box">
                    <div class="fm-modal-head">
                        <h3>Create Model / Design Asset</h3>
                        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('fmNewFileModal').classList.remove('active')">✕</button>
                    </div>
                    <div class="fm-modal-body">
                        <div>
                            <label class="field-label">Target Directory</label>
                            <input type="text" id="fmNewFileDir" class="form-input" style="width:100%;" readonly />
                        </div>
                        <div>
                            <label class="field-label">Asset Name (with extension)</label>
                            <input type="text" id="fmNewFileName" class="form-input" placeholder="e.g. model_config.yaml, agent_architecture.json" style="width:100%;" />
                        </div>
                        <div>
                            <label class="field-label">AI Agent Template</label>
                            <select id="fmNewFileTemplate" class="form-input" style="width:100%;">
                                <option value="model_config">🧠 LLM Model Configuration (model_config.yaml)</option>
                                <option value="agent_design">📐 Agent Architecture Design (agent_design.json)</option>
                                <option value="workflow">🔀 Workflow Execution DAG (workflow_dag.yaml)</option>
                                <option value="prompt">🤖 Agent System Prompt (system_prompt.md)</option>
                                <option value="skill">⚡ Agent Skill Definition (SKILL.md)</option>
                                <option value="dataset">📊 Fine-tuning / RAG Dataset (dataset.jsonl)</option>
                                <option value="tool_python">🐍 Python Tool Implementation (tool.py)</option>
                                <option value="empty">📄 Blank File</option>
                            </select>
                        </div>
                    </div>
                    <div class="fm-modal-foot">
                        <button class="btn btn-ghost" onclick="document.getElementById('fmNewFileModal').classList.remove('active')">Cancel</button>
                        <button class="btn btn-primary" id="btnSubmitNewFile">Create Asset</button>
                    </div>
                </div>
            </div>

            <!-- 2. New Folder Modal -->
            <div class="fm-modal" id="fmNewFolderModal">
                <div class="fm-modal-box">
                    <div class="fm-modal-head">
                        <h3>Create New Folder</h3>
                        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('fmNewFolderModal').classList.remove('active')">✕</button>
                    </div>
                    <div class="fm-modal-body">
                        <div>
                            <label class="field-label">Target Directory</label>
                            <input type="text" id="fmNewFolderDir" class="form-input" style="width:100%;" readonly />
                        </div>
                        <div>
                            <label class="field-label">Folder Name</label>
                            <input type="text" id="fmNewFolderName" class="form-input" placeholder="e.g. models, designs, checkpoints, prompts" style="width:100%;" />
                        </div>
                    </div>
                    <div class="fm-modal-foot">
                        <button class="btn btn-ghost" onclick="document.getElementById('fmNewFolderModal').classList.remove('active')">Cancel</button>
                        <button class="btn btn-primary" id="btnSubmitNewFolder">Create Folder</button>
                    </div>
                </div>
            </div>

            <!-- 3. Upload Modal -->
            <div class="fm-modal" id="fmUploadModal">
                <div class="fm-modal-box">
                    <div class="fm-modal-head">
                        <h3>Upload Model &amp; Design Files</h3>
                        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('fmUploadModal').classList.remove('active')">✕</button>
                    </div>
                    <div class="fm-modal-body">
                        <div>
                            <label class="field-label">Target Destination</label>
                            <input type="text" id="fmUploadTargetDir" class="form-input" style="width:100%;" readonly />
                        </div>
                        <div class="fm-upload-dropzone" id="fmModalDropzone" onclick="document.getElementById('fmUploadFileInput').click()">
                            <input type="file" id="fmUploadFileInput" multiple style="display:none;" />
                            <div style="font-size:32px;margin-bottom:8px;">📁</div>
                            <div style="font-weight:600;color:var(--fg);">Choose files or drag &amp; drop here</div>
                            <div style="font-size:12px;color:var(--fg-muted);margin-top:4px;">Supports weights (.onnx, .gguf), configs (.yaml, .json), prompts (.md), tools (.py)</div>
                        </div>
                        <div id="fmUploadFileList" style="max-height:140px;overflow-y:auto;font-size:12px;color:var(--fg-muted);"></div>
                    </div>
                    <div class="fm-modal-foot">
                        <button class="btn btn-ghost" onclick="document.getElementById('fmUploadModal').classList.remove('active')">Cancel</button>
                        <button class="btn btn-primary" id="btnSubmitUpload">Upload Assets</button>
                    </div>
                </div>
            </div>

            <!-- 4. Rename Modal -->
            <div class="fm-modal" id="fmRenameModal">
                <div class="fm-modal-box">
                    <div class="fm-modal-head">
                        <h3>Rename Item</h3>
                        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('fmRenameModal').classList.remove('active')">✕</button>
                    </div>
                    <div class="fm-modal-body">
                        <div>
                            <label class="field-label">Current Path</label>
                            <input type="text" id="fmRenameSrcPath" class="form-input" style="width:100%;" readonly />
                        </div>
                        <div>
                            <label class="field-label">New Path or Name</label>
                            <input type="text" id="fmRenameNewPath" class="form-input" style="width:100%;" />
                        </div>
                    </div>
                    <div class="fm-modal-foot">
                        <button class="btn btn-ghost" onclick="document.getElementById('fmRenameModal').classList.remove('active')">Cancel</button>
                        <button class="btn btn-primary" id="btnSubmitRename">Save Changes</button>
                    </div>
                </div>
            </div>
        `;

        attachGlobalListeners();
    }

    function attachGlobalListeners() {
        // Page Actions
        document.getElementById('btnFmNewModel')?.addEventListener('click', () => openNewFileModal('model_config', 'models'));
        document.getElementById('btnFmNewDesign')?.addEventListener('click', () => openNewFileModal('agent_design', 'designs'));
        document.getElementById('btnFmNewFile')?.addEventListener('click', () => openNewFileModal('empty'));
        document.getElementById('btnFmNewFolder')?.addEventListener('click', openNewFolderModal);
        document.getElementById('btnFmUpload')?.addEventListener('click', openUploadModal);
        document.getElementById('btnFmRefresh')?.addEventListener('click', () => {
            refreshMetrics();
            loadDirectory(fmState.cwd);
        });

        // WebSocket Pill Click: manual reconnect
        document.getElementById('fmWsStatusPill')?.addEventListener('click', () => {
            initWebSocket();
        });

        // Toggle Sidebar (Maximize Canvas Space)
        document.getElementById('btnFmToggleSidebar')?.addEventListener('click', () => {
            const sidebar = document.querySelector('.fm-sidebar');
            if (sidebar) {
                sidebar.classList.toggle('collapsed');
            }
        });

        // View Switcher
        const btnTable = document.getElementById('btnFmViewTable');
        const btnGrid = document.getElementById('btnFmViewGrid');

        btnGrid?.addEventListener('click', () => {
            fmState.viewMode = 'grid';
            btnGrid.classList.add('active');
            btnTable?.classList.remove('active');
            renderCanvas();
        });

        btnTable?.addEventListener('click', () => {
            fmState.viewMode = 'table';
            btnTable.classList.add('active');
            btnGrid?.classList.remove('active');
            renderCanvas();
        });

        // Search Input
        const searchInput = document.getElementById('fmSearchInput');
        searchInput?.addEventListener('input', () => {
            fmState.searchQuery = searchInput.value;
            renderCanvas();
        });

        // Sort Selector
        const sortSelect = document.getElementById('fmSortSelect');
        sortSelect?.addEventListener('change', () => {
            const [field, dir] = sortSelect.value.split(':');
            fmState.sortBy = field;
            fmState.sortDesc = dir === 'desc';
            renderCanvas();
        });

        // Sidebar Navigation
        document.querySelectorAll('.fm-sidebar .fm-nav-btn[data-loc]').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.fm-sidebar .fm-nav-btn[data-loc]').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadDirectory(btn.dataset.loc);
            });
        });

        function setCategoryFilter(filterKey) {
            fmState.activeFilter = filterKey;
            document.querySelectorAll('#fmQuickFilters .fm-filter-chip').forEach(b => {
                b.classList.toggle('active', b.dataset.filter === filterKey);
            });
            document.querySelectorAll('.fm-sidebar .fm-nav-btn[data-filter]').forEach(b => {
                b.classList.toggle('active', b.dataset.filter === filterKey);
            });
            renderCanvas();
        }

        document.querySelectorAll('#fmQuickFilters .fm-filter-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                setCategoryFilter(btn.dataset.filter);
            });
        });

        document.querySelectorAll('.fm-sidebar .fm-nav-btn[data-filter]').forEach(btn => {
            btn.addEventListener('click', () => {
                setCategoryFilter(btn.dataset.filter);
            });
        });

        // Inspector Close
        document.getElementById('btnFmCloseInspector')?.addEventListener('click', () => {
            document.getElementById('fmInspector')?.classList.add('closed');
        });

        // Batch Buttons
        document.getElementById('btnFmDeselectAll')?.addEventListener('click', () => {
            fmState.selectedPaths.clear();
            document.querySelectorAll('.fm-desktop-checkbox, .fm-row-checkbox').forEach(cb => cb.checked = false);
            document.querySelectorAll('.fm-desktop-item, .fm-table-row').forEach(el => el.classList.remove('selected'));
            updateBatchBar();
        });

        document.getElementById('btnFmBatchDelete')?.addEventListener('click', batchDeleteSelected);
        document.getElementById('btnFmBatchDownload')?.addEventListener('click', batchDownloadSelected);

        // Modal Form Submits
        document.getElementById('btnSubmitNewFile')?.addEventListener('click', submitCreateFile);
        document.getElementById('btnSubmitNewFolder')?.addEventListener('click', submitCreateFolder);
        document.getElementById('btnSubmitRename')?.addEventListener('click', submitRename);

        // Upload Modal file input change
        const fileInput = document.getElementById('fmUploadFileInput');
        fileInput?.addEventListener('change', () => {
            const listEl = document.getElementById('fmUploadFileList');
            if (!listEl) return;
            const files = Array.from(fileInput.files || []);
            listEl.innerHTML = files.map(f => `<div>📄 ${escapeHtml(f.name)} (${formatBytes(f.size)})</div>`).join('');
        });

        document.getElementById('btnSubmitUpload')?.addEventListener('click', () => {
            if (fileInput?.files?.length) {
                handleFilesUpload(fileInput.files);
            } else {
                showToast('Please select at least one file to upload', 'warn');
            }
        });

        // Drag & Drop on Explorer Workstation
        const dropTarget = document.getElementById('fmDropTarget');
        const dropOverlay = document.getElementById('fmDropzoneOverlay');

        if (dropTarget && dropOverlay) {
            dropTarget.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropOverlay.classList.add('active');
            });

            dropTarget.addEventListener('dragleave', (e) => {
                if (!e.relatedTarget || !dropTarget.contains(e.relatedTarget)) {
                    dropOverlay.classList.remove('active');
                }
            });

            dropTarget.addEventListener('drop', (e) => {
                e.preventDefault();
                dropOverlay.classList.remove('active');
                if (e.dataTransfer?.files?.length) {
                    handleFilesUpload(e.dataTransfer.files);
                }
            });
        }

        // Global dismiss for context menu
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#fmContextMenu')) {
                closeContextMenu();
            }
        });

        // Desktop Keyboard Shortcuts & Navigation
        document.addEventListener('keydown', (e) => {
            const page = document.getElementById('page-filemanager');
            if (!page || page.classList.contains('hidden') || page.style.display === 'none') return;

            // If user is editing in an input, textarea, select, or contenteditable, don't hijack keys
            const activeEl = document.activeElement;
            const isEditing = activeEl && (
                activeEl.tagName === 'INPUT' ||
                activeEl.tagName === 'TEXTAREA' ||
                activeEl.tagName === 'SELECT' ||
                activeEl.isContentEditable
            );
            if (isEditing) {
                if (e.key === 'Escape') {
                    activeEl.blur();
                }
                return;
            }

            // Close context menu on Escape
            if (e.key === 'Escape') {
                closeContextMenu();
                return;
            }

            // Ignore if any modal is currently visible
            if (document.querySelector('.modal-backdrop:not(.hidden)')) return;

            // Ctrl+A / Cmd+A: Select All
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
                e.preventDefault();
                const items = getFilteredAndSortedItems();
                fmState.selectedPaths.clear();
                items.forEach(i => fmState.selectedPaths.add(i.path));
                document.querySelectorAll('.fm-desktop-item, .fm-table-row').forEach(el => el.classList.add('selected'));
                document.querySelectorAll('.fm-desktop-checkbox, .fm-row-checkbox').forEach(cb => cb.checked = true);
                updateBatchBar();
                return;
            }

            // Ctrl+F / Cmd+F: Focus Search
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
                e.preventDefault();
                const searchInput = document.getElementById('fmSearchInput');
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
                return;
            }

            const visibleItems = getFilteredAndSortedItems();
            if (!visibleItems.length) return;

            // Find current selected index
            let currentIndex = -1;
            if (fmState.selectedPaths.size > 0) {
                const lastSelected = Array.from(fmState.selectedPaths).pop();
                currentIndex = visibleItems.findIndex(i => i.path === lastSelected);
            }

            // Arrow Keys: Navigate through items
            if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                e.preventDefault();
                let nextIndex = 0;
                const total = visibleItems.length;

                if (fmState.viewMode === 'table') {
                    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                        nextIndex = currentIndex === -1 ? 0 : Math.min(total - 1, currentIndex + 1);
                    } else {
                        nextIndex = currentIndex === -1 ? total - 1 : Math.max(0, currentIndex - 1);
                    }
                } else {
                    const canvas = document.getElementById('fmCanvas');
                    const itemWidth = 140; // ~124px + 16px gap
                    const cols = Math.max(1, Math.floor((canvas ? canvas.clientWidth : 800) / itemWidth));

                    if (e.key === 'ArrowRight') {
                        nextIndex = currentIndex === -1 ? 0 : Math.min(total - 1, currentIndex + 1);
                    } else if (e.key === 'ArrowLeft') {
                        nextIndex = currentIndex === -1 ? total - 1 : Math.max(0, currentIndex - 1);
                    } else if (e.key === 'ArrowDown') {
                        nextIndex = currentIndex === -1 ? 0 : Math.min(total - 1, currentIndex + cols);
                    } else if (e.key === 'ArrowUp') {
                        nextIndex = currentIndex === -1 ? total - 1 : Math.max(0, currentIndex - cols);
                    }
                }

                const targetItem = visibleItems[nextIndex];
                if (targetItem) {
                    fmState.selectedPaths.clear();
                    fmState.selectedPaths.add(targetItem.path);

                    document.querySelectorAll('.fm-desktop-item, .fm-table-row').forEach(el => {
                        const isMatch = el.dataset.path === targetItem.path;
                        el.classList.toggle('selected', isMatch);
                        if (isMatch) {
                            el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                            el.focus?.();
                        }
                    });
                    document.querySelectorAll('.fm-desktop-checkbox, .fm-row-checkbox').forEach(cb => {
                        cb.checked = cb.dataset.path === targetItem.path;
                    });
                    updateBatchBar();
                    inspectFile(targetItem);
                }
                return;
            }

            // Enter: Open directory or inspect/edit file
            if (e.key === 'Enter') {
                if (currentIndex !== -1 && visibleItems[currentIndex]) {
                    e.preventDefault();
                    const item = visibleItems[currentIndex];
                    if (item.type === 'directory') {
                        loadDirectory(item.path);
                    } else {
                        inspectFile(item, true);
                    }
                }
                return;
            }

            // Backspace / Alt+ArrowUp: Navigate up
            if (e.key === 'Backspace' || (e.altKey && e.key === 'ArrowUp')) {
                if (fmState.cwd) {
                    e.preventDefault();
                    document.getElementById('btnFmUpLevel')?.click();
                }
                return;
            }

            // Space: Quick Preview / Inspect
            if (e.key === ' ') {
                if (currentIndex !== -1 && visibleItems[currentIndex]) {
                    e.preventDefault();
                    const item = visibleItems[currentIndex];
                    inspectFile(item, true);
                }
                return;
            }

            // F2: Rename
            if (e.key === 'F2') {
                if (currentIndex !== -1 && visibleItems[currentIndex]) {
                    e.preventDefault();
                    openRenameModal(visibleItems[currentIndex].path);
                }
                return;
            }

            // Delete: Delete selected
            if (e.key === 'Delete') {
                if (fmState.selectedPaths.size === 1) {
                    e.preventDefault();
                    const path = Array.from(fmState.selectedPaths)[0];
                    confirmDeleteItem(path);
                } else if (fmState.selectedPaths.size > 1) {
                    e.preventDefault();
                    batchDeleteSelected();
                }
                return;
            }
        });
    }

    // ── Global Object Export ────────────────────────────────────────────────

    window.FileManagerUI = {
        init,
        refresh: () => {
            refreshMetrics();
            loadDirectory(fmState.cwd);
        },
        navigateTo: loadDirectory,
        openNewModel: () => openNewFileModal('model_config', 'models'),
        openNewDesign: () => openNewFileModal('agent_design', 'designs'),
        openNewFile: (template = 'empty') => openNewFileModal(template),
        openNewFolder: openNewFolderModal,
        openUpload: openUploadModal,
    };

    // Auto-init if page is active on DOM load
    document.addEventListener('DOMContentLoaded', () => {
        const fileManagerPage = document.getElementById('page-filemanager');
        if (fileManagerPage && !fileManagerPage.classList.contains('hidden')) {
            init();
        }
    });

})();
