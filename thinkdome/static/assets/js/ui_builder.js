/**
 * ui_builder.js — ThinkDome Dynamic UI Platform Studio Engine (Frappe-style)
 * Powers Visual Studio Mode, live item editing, transactional drafts, preview, and versioning.
 */

(function (global) {
  'use strict';

  let activeStudioWorkspace = null;
  let activeDraftId = null;
  let isStudioActive = false;

  global.toggleWorkspaceStudioMode = function (enable = true) {
    isStudioActive = enable;
    const studioBar = document.getElementById('deskStudioBar');
    if (studioBar) {
      studioBar.hidden = !enable;
    }

    if (enable) {
      if (!activeStudioWorkspace) {
        // Initialize working copy from current effective workspace
        activeStudioWorkspace = JSON.parse(JSON.stringify(global.currentWorkspaceData || {
          name: "build",
          label: "Build Workspace",
          version: "1.0",
          icon: "▦",
          description: "Role-aware development & operations studio.",
          shortcuts: [
            { name: "create_sandbox", label: "Create Sandbox", route: "sandboxes", count: "3" },
            { name: "terminal", label: "Open Terminal", route: "console" },
            { name: "api_keys", label: "Manage API Keys", route: "apikeys" }
          ],
          number_cards: [
            { label: "Active Sandboxes", value: "4", trend: "+2 active" },
            { label: "Compute Usage", value: "18.4 hrs", trend: "+12.4%" },
            { label: "Security Score", value: "98/100", trend: "Passing" }
          ],
          card_groups: [
            {
              name: "Operations & Compute",
              title: "Operations & Compute",
              items: [
                { name: "sandboxes", label: "Sandboxes Studio", description: "Manage sandbox containers & microVMs", route: "sandboxes", badge: "Live" },
                { name: "console", label: "Console & Terminal", description: "Interactive command environment", route: "console" }
              ]
            },
            {
              name: "Security & Access",
              title: "Security & Access Control",
              items: [
                { name: "apikeys", label: "API Keys", description: "Manage authentication tokens", route: "apikeys" },
                { name: "audit", label: "Audit Center", description: "Security audit trail", route: "audit" }
              ]
            }
          ]
        }));
      }
      renderStudioDesk();
    } else {
      // Re-render in view mode
      if (typeof global.loadDynamicWorkspace === 'function') {
        global.loadDynamicWorkspace();
      }
    }
  };

  function renderStudioDesk() {
    const container = document.getElementById('deskDeskContainer') || document.getElementById('workspaceDeskContainer');
    if (!container || !activeStudioWorkspace) return;

    if (global.thinkdome && global.thinkdome.ui && typeof global.thinkdome.ui.renderWorkspaceDesk === 'function') {
      global.thinkdome.ui.renderWorkspaceDesk(container, activeStudioWorkspace, true);
    }
  }

  // ── Shortcut Items ─────────────────────────────────────────────────────────

  global.openAddShortcutModal = function () {
    const label = prompt("Enter Shortcut Label:");
    if (!label) return;
    const route = prompt("Enter Target Route (e.g., sandboxes, console, billing):", "sandboxes");
    if (!route) return;

    if (!activeStudioWorkspace.shortcuts) activeStudioWorkspace.shortcuts = [];
    activeStudioWorkspace.shortcuts.push({
      name: label.toLowerCase().replace(/\s+/g, '_'),
      label: label,
      route: route,
      count: "New"
    });
    renderStudioDesk();
  };

  global.removeWorkspaceShortcut = function (idx) {
    if (!activeStudioWorkspace || !activeStudioWorkspace.shortcuts) return;
    activeStudioWorkspace.shortcuts.splice(idx, 1);
    renderStudioDesk();
  };

  // ── Number Cards (Metrics) ──────────────────────────────────────────────────

  global.openAddNumberCardModal = function () {
    const label = prompt("Enter Metric Label:");
    if (!label) return;
    const value = prompt("Enter Metric Display Value:", "100");
    if (!value) return;

    if (!activeStudioWorkspace.number_cards) activeStudioWorkspace.number_cards = [];
    activeStudioWorkspace.number_cards.push({
      label: label,
      value: value,
      trend: "New"
    });
    renderStudioDesk();
  };

  global.removeWorkspaceNumberCard = function (idx) {
    if (!activeStudioWorkspace || !activeStudioWorkspace.number_cards) return;
    activeStudioWorkspace.number_cards.splice(idx, 1);
    renderStudioDesk();
  };

  // ── Card Groups & Links ────────────────────────────────────────────────────

  global.openAddCardGroupModal = function () {
    const title = prompt("Enter Group Title:");
    if (!title) return;

    if (!activeStudioWorkspace.card_groups) activeStudioWorkspace.card_groups = [];
    activeStudioWorkspace.card_groups.push({
      name: title.toLowerCase().replace(/\s+/g, '_'),
      title: title,
      items: []
    });
    renderStudioDesk();
  };

  global.addCardGroupItem = function (gIdx) {
    if (!activeStudioWorkspace || !activeStudioWorkspace.card_groups) return;
    const group = activeStudioWorkspace.card_groups[gIdx];
    if (!group) return;

    const label = prompt("Enter Link Label:");
    if (!label) return;
    const route = prompt("Enter Target Route:", "sandboxes");
    if (!route) return;
    const desc = prompt("Enter Subtitle / Description:", "Manage resources");

    if (!group.items) group.items = [];
    group.items.push({
      name: label.toLowerCase().replace(/\s+/g, '_'),
      label: label,
      route: route,
      description: desc || ""
    });
    renderStudioDesk();
  };

  global.removeCardGroupItem = function (gIdx, iIdx) {
    if (!activeStudioWorkspace || !activeStudioWorkspace.card_groups) return;
    const group = activeStudioWorkspace.card_groups[gIdx];
    if (group && group.items) {
      group.items.splice(iIdx, 1);
      renderStudioDesk();
    }
  };

  // ── Transactional Draft, Preview, Publish, Versioning ───────────────────────

  global.saveStudioDraft = async function () {
    if (!activeStudioWorkspace) return;
    try {
      const draftResult = await global.thinkdome.call("thinkdome.core.ui.api.save_ui_draft", {
        data: activeStudioWorkspace
      });
      activeDraftId = draftResult.draft_id;
      if (typeof global.showToast === 'function') {
        global.showToast(`Draft saved successfully (ID: ${activeDraftId})`, 'success');
      }
      return activeDraftId;
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Failed to save draft: ${err.message}`, 'error');
      }
    }
  };

  global.previewStudioDraft = async function () {
    let draftId = activeDraftId;
    if (!draftId) {
      draftId = await global.saveStudioDraft();
    }
    if (!draftId) return;

    try {
      const previewData = await global.thinkdome.call("thinkdome.core.ui.api.preview_ui", {
        draft_id: draftId
      });
      if (typeof global.showToast === 'function') {
        global.showToast('Preview calculated non-mutating Effective UI successfully.', 'info');
      }
      console.log("[Dynamic UI Platform Preview Impact]", previewData);
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Preview failed: ${err.message}`, 'error');
      }
    }
  };

  global.publishStudioDraft = async function () {
    let draftId = activeDraftId;
    if (!draftId) {
      draftId = await global.saveStudioDraft();
    }
    if (!draftId) return;

    try {
      const publishResult = await global.thinkdome.call("thinkdome.core.ui.api.publish_ui", {
        draft_id: draftId
      });
      if (typeof global.showToast === 'function') {
        global.showToast(`Version ${publishResult.version_id} published live!`, 'success');
      }
      global.toggleWorkspaceStudioMode(false);
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Publish failed: ${err.message}`, 'error');
      }
    }
  };

  global.loadVersionHistory = async function () {
    try {
      const versions = await global.thinkdome.call("thinkdome.core.ui.api.list_versions");
      const select = document.getElementById('deskVersionSelect');
      if (!select) return;
      select.replaceChildren();

      if (!versions || versions.length === 0) {
        select.appendChild(new Option("v1.0 (Live)", "v1.0"));
        return;
      }

      versions.forEach(v => {
        const opt = new Option(`v${v.version_num} (${v.published_by}) - ${new Date(v.created_at * 1000).toLocaleTimeString()}`, v.version_id);
        select.appendChild(opt);
      });
    } catch (err) {
      console.warn("Failed to load versions:", err);
    }
  };

  global.restoreSelectedVersion = async function () {
    const select = document.getElementById('deskVersionSelect');
    if (!select || !select.value) return;
    const versionId = select.value;

    if (!confirm(`Restore Workspace Version ${versionId}?`)) return;

    try {
      await global.thinkdome.call("thinkdome.core.ui.api.restore_version", {
        version_id: versionId
      });
      if (typeof global.showToast === 'function') {
        global.showToast(`Restored version ${versionId}`, 'success');
      }
      global.toggleWorkspaceStudioMode(false);
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Restore failed: ${err.message}`, 'error');
      }
    }
  };

  // ── Dynamic UI Platform Creator Controller Functions ──────────────────────

  global.switchPlatformWorkspaceTab = function (tab) {
    const deskTab = document.getElementById('platformDeskTab');
    const studioTab = document.getElementById('platformStudioTab');
    const btnDesk = document.getElementById('tabBtnDesk');
    const btnStudio = document.getElementById('tabBtnStudio');

    if (!deskTab || !studioTab) return;

    if (tab === 'studio') {
      deskTab.hidden = true;
      studioTab.hidden = false;
      btnDesk?.classList.remove('active');
      btnStudio?.classList.add('active');
      global.loadDynamicPlatformRegistryTable();
    } else {
      deskTab.hidden = false;
      studioTab.hidden = true;
      btnDesk?.classList.add('active');
      btnStudio?.classList.remove('active');
    }
  };

  global.addCreatorPageBlock = function () {
    const list = document.getElementById('creatorPageBlocksList');
    if (!list) return;

    const row = document.createElement('div');
    row.className = 'creator-block-row';
    row.innerHTML = `
      <select class="form-select block-type" style="width:110px;">
        <option value="heading">Heading</option>
        <option value="card">Card</option>
        <option value="stat">Stat Metric</option>
        <option value="text">Text</option>
      </select>
      <input type="text" class="form-input block-title" placeholder="Block Title / Text" value=""/>
      <input type="text" class="form-input block-val" placeholder="Value / Body" value=""/>
      <button type="button" class="btn btn-ghost btn-xs" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
  };

  global.addCreatorMenuItem = function () {
    const list = document.getElementById('creatorMenuItemsList');
    if (!list) return;

    const row = document.createElement('div');
    row.className = 'creator-block-row';
    row.innerHTML = `
      <input type="text" class="form-input item-label" placeholder="Item Label" value=""/>
      <input type="text" class="form-input item-route" placeholder="Target Page ID" value=""/>
      <select class="form-select item-icon" style="width:90px;">
        <option value="grid">Grid</option>
        <option value="terminal">Terminal</option>
        <option value="box">Box</option>
        <option value="settings">Settings</option>
      </select>
      <button type="button" class="btn btn-ghost btn-xs" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
  };

  global.submitCreatorCreatePage = async function () {
    const pageId = (document.getElementById('creatorPageId')?.value || '').trim().toLowerCase();
    const title = (document.getElementById('creatorPageTitle')?.value || '').trim();

    if (!pageId || !title) {
      if (typeof global.showToast === 'function') global.showToast('Page Route ID and Title are required.', 'error');
      return;
    }

    const allowedRoles = [...document.querySelectorAll('#platformStudioTab .role-checkbox-label input:checked')].map(c => c.value);

    const layout = [...document.querySelectorAll('#creatorPageBlocksList .creator-block-row')].map(row => {
      const type = row.querySelector('.block-type')?.value || 'text';
      const text = row.querySelector('.block-title')?.value || '';
      const val = row.querySelector('.block-val')?.value || '';
      return { type, text, title: text, value: val, body: val };
    });

    try {
      const pageConfig = {
        name: pageId,
        route: pageId,
        title: title,
        allowed_roles: allowedRoles,
        layout: layout
      };

      await global.thinkdome.call("thinkdome.core.ui.api.create_page", { config: pageConfig });

      if (typeof global.showToast === 'function') {
        global.showToast(`Dynamic Page '${title}' created successfully via RPC!`, 'success');
      }

      // Refresh navigation and registry table
      if (typeof global.refreshWorkspaceMenu === 'function') await global.refreshWorkspaceMenu();
      await global.loadDynamicPlatformRegistryTable();

      document.getElementById('creatorPageId').value = '';
      document.getElementById('creatorPageTitle').value = '';
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Failed to create page: ${err.message}`, 'error');
      }
    }
  };

  global.submitCreatorCreateWorkspace = async function () {
    const wsName = (document.getElementById('creatorWsName')?.value || '').trim().toLowerCase();
    const wsLabel = (document.getElementById('creatorWsLabel')?.value || '').trim();

    if (!wsName || !wsLabel) {
      if (typeof global.showToast === 'function') global.showToast('Workspace Identifier and Label are required.', 'error');
      return;
    }

    const items = [...document.querySelectorAll('#creatorMenuItemsList .creator-block-row')].map(row => {
      const label = row.querySelector('.item-label')?.value || 'Item';
      const route = row.querySelector('.item-route')?.value || 'dashboard';
      const icon = row.querySelector('.item-icon')?.value || 'grid';
      return { name: route, label: label, route: route, icon: icon, type: 'page' };
    });

    try {
      const wsConfig = {
        name: wsName,
        label: wsLabel,
        sequence: 10,
        items: items
      };

      await global.thinkdome.call("thinkdome.core.ui.api.create_workspace", { config: wsConfig });

      if (typeof global.showToast === 'function') {
        global.showToast(`Sidebar Navigation '${wsLabel}' published via RPC!`, 'success');
      }

      if (typeof global.refreshWorkspaceMenu === 'function') await global.refreshWorkspaceMenu();
      if (typeof global.loadDynamicWorkspace === 'function') await global.loadDynamicWorkspace();

      document.getElementById('creatorWsName').value = '';
      document.getElementById('creatorWsLabel').value = '';
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Failed to publish navigation: ${err.message}`, 'error');
      }
    }
  };

  global.loadDynamicPlatformRegistryTable = async function () {
    const tbody = document.getElementById('creatorRegistryTableBody');
    if (!tbody) return;

    try {
      const builderState = await global.thinkdome.call("thinkdome.core.ui.api.get_ui_builder");
      const effective = builderState.effective || {};
      const pages = effective.pages || [];

      tbody.replaceChildren();

      if (pages.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--fg-muted);padding:18px;">No dynamic pages registered yet. Use the creator above!</td></tr>';
        return;
      }

      pages.forEach(p => {
        const tr = document.createElement('tr');
        const roles = (p.allowed_roles || []).map(r => `<span class="desk-version-tag">${r}</span>`).join(' ');
        const blocksCount = (p.layout || []).length;

        tr.innerHTML = `
          <td><strong style="font-family:var(--font-mono);font-size:12.5px;">/${p.name || p.page_id}</strong></td>
          <td><strong>${p.title}</strong></td>
          <td>${roles || '<span class="desk-version-tag">Everyone</span>'}</td>
          <td>${blocksCount} block(s)</td>
          <td>
            <button class="btn btn-ghost btn-xs" onclick="openDynamicPageRuntime('${p.name}')">View Page ↗</button>
            <button class="btn btn-danger btn-xs" onclick="deleteDynamicPageRPC('${p.name}')">Delete</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn("Failed to load registry table:", err);
    }
  };

  global.openDynamicPageRuntime = async function (pageId) {
    try {
      const pageConfig = await global.thinkdome.call("thinkdome.core.ui.api.get_page", { name: pageId });
      if (!pageConfig) throw new Error("Page configuration not found");

      document.getElementById('dynamicRuntimePageTitle').textContent = pageConfig.title || pageId;
      document.getElementById('dynamicRuntimePageSubtitle').textContent = `Role restriction: ${(pageConfig.allowed_roles || []).join(', ') || 'Everyone'}`;

      if (global.thinkdome && global.thinkdome.ui && typeof global.thinkdome.ui.renderPage === 'function') {
        global.thinkdome.ui.renderPage('#dynamicRuntimePageContainer', pageConfig);
      }

      if (typeof global.navTo === 'function') {
        global.navTo('dynamic-runtime');
      }
    } catch (err) {
      if (typeof global.showToast === 'function') global.showToast(`Failed to view page: ${err.message}`, 'error');
    }
  };

  global.deleteDynamicPageRPC = async function (pageId) {
    if (!confirm(`Delete Dynamic Page '${pageId}'?`)) return;
    try {
      await global.thinkdome.call("thinkdome.core.ui.api.delete_page", { name: pageId });
      if (typeof global.showToast === 'function') global.showToast(`Page '${pageId}' deleted`, 'success');
      await global.loadDynamicPlatformRegistryTable();
      if (typeof global.refreshWorkspaceMenu === 'function') await global.refreshWorkspaceMenu();
    } catch (err) {
      if (typeof global.showToast === 'function') global.showToast(`Delete failed: ${err.message}`, 'error');
    }
  };

  // ── Currently Configured Introspection Overview ─────────────────────────────

  global.loadPlatformConfiguredSummary = async function () {
    try {
      const summary = await global.thinkdome.call("thinkdome.core.ui.api.get_platform_summary");
      const wsCount = document.getElementById('summaryWorkspacesCount');
      const wsList = document.getElementById('summaryWorkspacesList');
      const pgCount = document.getElementById('summaryPagesCount');
      const pgList = document.getElementById('summaryPagesList');
      const rolesCount = document.getElementById('summaryRolesCount');
      const activeVer = document.getElementById('summaryActiveVersion');

      const workspaces = summary.workspaces || [];
      const pages = summary.pages || [];

      if (wsCount) wsCount.textContent = String(summary.total_workspaces || workspaces.length);
      if (wsList) wsList.textContent = workspaces.map(w => w.label || w.name).join(', ') || 'Default Build';

      if (pgCount) pgCount.textContent = String(summary.total_pages || pages.length);
      if (pgList) pgList.textContent = pages.map(p => p.title || p.name).slice(0, 3).join(', ') + (pages.length > 3 ? ` +${pages.length - 3} more` : '');

      const rolesSet = new Set();
      pages.forEach(p => (p.allowed_roles || []).forEach(r => rolesSet.add(r)));
      if (rolesCount) rolesCount.textContent = String(rolesSet.size || 2);

      if (activeVer) activeVer.textContent = summary.active_version || 'v1.0';
    } catch (err) {
      console.warn("Failed to load platform summary:", err);
    }
  };

  // ── Premade Recommended Templates Engine ─────────────────────────────────────

  const PREMADE_TEMPLATES = {
    developer: {
      workspaces: [
        {
          name: "developer",
          label: "AI & Dev Engineering Workspace",
          sequence: 1,
          icon: "🚀",
          description: "Recommended for AI agents, developers, and engineers.",
          items: [
            { name: "sandboxes", label: "Sandboxes Studio", route: "sandboxes", type: "page", icon: "box" },
            { name: "console", label: "Console & Terminal", route: "console", type: "page", icon: "terminal" },
            { name: "mcp", label: "MCP Tools Registry", route: "mcp", type: "page", icon: "grid" },
            { name: "apikeys", label: "API Keys Management", route: "apikeys", type: "page", icon: "settings" }
          ]
        }
      ],
      pages: [
        {
          name: "sandboxes",
          title: "Sandboxes Studio",
          allowed_roles: ["AGENT_STANDARD", "SUPER_ADMIN"],
          layout: [
            { type: "heading", text: "AI Sandboxes Studio & MicroVM Containers", level: 1 },
            { type: "stat", label: "Isolation Policy", value: "Docker / Strict Network Deny" }
          ]
        },
        {
          name: "console",
          title: "Console & IDE Environment",
          allowed_roles: ["AGENT_STANDARD", "SUPER_ADMIN"],
          layout: [
            { type: "heading", text: "Interactive Console & Code Execution", level: 1 }
          ]
        }
      ]
    },
    operations: {
      workspaces: [
        {
          name: "operations",
          label: "Security & Operations Admin",
          sequence: 2,
          icon: "🛡️",
          description: "Recommended for tenant security admins and system operators.",
          items: [
            { name: "users", label: "User Accounts", route: "users", type: "page", icon: "grid" },
            { name: "roles", label: "Role Permissions Manager", route: "roles", type: "page", icon: "settings" },
            { name: "audit", label: "Security Audit Trail", route: "audit", type: "page", icon: "terminal" },
            { name: "limits", label: "Network Audit & Limits", route: "limits", type: "page", icon: "box" }
          ]
        }
      ],
      pages: [
        {
          name: "users",
          title: "User Identity Accounts",
          allowed_roles: ["SUPER_ADMIN"],
          layout: [{ type: "heading", text: "RBAC User Accounts & Key Credentials", level: 1 }]
        },
        {
          name: "audit",
          title: "Security Audit Center",
          allowed_roles: ["SUPER_ADMIN"],
          layout: [{ type: "heading", text: "Tenant Security Audit Logs", level: 1 }]
        }
      ]
    },
    finance: {
      workspaces: [
        {
          name: "finance",
          label: "Finance & Resource Management",
          sequence: 3,
          icon: "💰",
          description: "Recommended for finance managers and resource controllers.",
          items: [
            { name: "billing", label: "Billing & Usage Reports", route: "billing", type: "page", icon: "grid" },
            { name: "account", label: "Account Settings", route: "account", type: "page", icon: "settings" }
          ]
        }
      ],
      pages: [
        {
          name: "billing",
          title: "Billing & Resource Consumption",
          allowed_roles: ["FINANCE_MANAGER", "SUPER_ADMIN"],
          layout: [{ type: "heading", text: "Resource Spending & Monthly Credit Usage", level: 1 }]
        }
      ]
    }
  };

  global.applyPremadeTemplate = async function (templateKey) {
    const tpl = PREMADE_TEMPLATES[templateKey];
    if (!tpl) return;

    if (!confirm(`Apply recommended premade template '${templateKey}' to ThinkDome UI Platform?`)) return;

    try {
      await global.thinkdome.call("thinkdome.core.ui.api.setup_dynamic_ui", { config: tpl });

      if (typeof global.showToast === 'function') {
        global.showToast(`Premade template '${templateKey}' applied successfully via RPC!`, 'success');
      }

      if (typeof global.refreshWorkspaceMenu === 'function') await global.refreshWorkspaceMenu();
      if (typeof global.loadDynamicWorkspace === 'function') await global.loadDynamicWorkspace();
      await global.loadPlatformConfiguredSummary();
      await global.loadDynamicPlatformRegistryTable();
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Failed to apply template: ${err.message}`, 'error');
      }
    }
  };

  // Legacy page-creation modal removed. Pages are created and edited inline in Workspace Manager.

  global.openCreateMenuModal = function () {
    const modal = document.getElementById('modalCreateSidebarMenu');
    if (modal) {
      document.getElementById('modalWsName').value = '';
      document.getElementById('modalWsLabel').value = '';
      modal.classList.add('active');
    }
  };

  global.closeCreateMenuModal = function () {
    document.getElementById('modalCreateSidebarMenu')?.classList.remove('active');
  };

  global.addModalMenuItem = function () {
    const list = document.getElementById('modalMenuItemsList');
    if (!list) return;

    const row = document.createElement('div');
    row.className = 'creator-block-row';
    row.innerHTML = `
      <input type="text" class="form-input item-label" placeholder="Item Label" value=""/>
      <input type="text" class="form-input item-route" placeholder="Target Page ID" value=""/>
      <select class="form-select item-icon" style="width:90px;">
        <option value="grid">Grid</option>
        <option value="terminal">Terminal</option>
        <option value="box">Box</option>
        <option value="settings">Settings</option>
      </select>
      <button type="button" class="btn btn-ghost btn-xs" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
  };

  global.submitModalCreateWorkspace = async function () {
    const wsName = (document.getElementById('modalWsName')?.value || '').trim().toLowerCase();
    const wsLabel = (document.getElementById('modalWsLabel')?.value || '').trim();

    if (!wsName || !wsLabel) {
      if (typeof global.showToast === 'function') global.showToast('Workspace Identifier and Label are required.', 'error');
      return;
    }

    const items = [...document.querySelectorAll('#modalMenuItemsList .creator-block-row')].map(row => {
      const label = row.querySelector('.item-label')?.value || 'Item';
      const route = row.querySelector('.item-route')?.value || 'dashboard';
      const icon = row.querySelector('.item-icon')?.value || 'grid';
      return { name: route, label: label, route: route, icon: icon, type: 'page' };
    });

    try {
      const wsConfig = {
        name: wsName,
        label: wsLabel,
        sequence: 10,
        items: items
      };

      await global.thinkdome.call("thinkdome.core.ui.api.create_workspace", { config: wsConfig });

      if (typeof global.showToast === 'function') {
        global.showToast(`Sidebar Navigation '${wsLabel}' published via RPC!`, 'success');
      }

      global.closeCreateMenuModal();
      if (typeof global.refreshWorkspaceMenu === 'function') await global.refreshWorkspaceMenu();
      if (typeof global.loadDynamicWorkspace === 'function') await global.loadDynamicWorkspace();
      await global.loadPlatformConfiguredSummary();
    } catch (err) {
      if (typeof global.showToast === 'function') {
        global.showToast(`Failed to publish navigation: ${err.message}`, 'error');
      }
    }
  };

})(typeof window !== 'undefined' ? window : globalThis);
