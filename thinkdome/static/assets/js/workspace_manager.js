/**
 * workspace_manager.js — ThinkDome Framework-Style Workspace Manager
 * Implements:
 *   Card 1: Workspace Viewer (Tree & Group views, per-role filter, interactive inline edit & delete)
 *   Card 2: Page, Module & Process Role Mapper (Grant & Deny privilege giver + Granted view + Sidebar menu builder)
 *   Card 3: Standard UI Renderer Customizer — "The Boss" (Central Registry where everything registers first, role whitelisting, visual block customizer, transactional drafts & versioning)
 */

(function (global) {
  'use strict';

  // State Store
  const wmState = {
    activeCard: 'card1', // 'card1' | 'card2' | 'card3'
    viewMode: 'tree', // 'tree' | 'group'
    activeRoleFilter: '__all__',
    activeMapperTab: 'pages', // 'pages' | 'modules' | 'processes'
    activeMapperRole: 'AGENT_STANDARD',
    activeBossTab: 'register', // 'register' | 'designer' | 'registry' | 'versions'
    treeData: null,
    matrixData: null,
    registryData: null,
    designerPage: null,
    editingNodeId: null,
  };

  // Keep server-provided labels out of HTML/JavaScript contexts. The normal
  // renderer uses textContent, but a few compact table/group templates still
  // need HTML for layout; all values crossing that boundary must be escaped.
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>\"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
    }[character]));
  }

  function inlineArg(value) {
    return escapeHtml(JSON.stringify(String(value ?? '')));
  }

  function authHeaders(json = false) {
    const headers = {};
    const token = localStorage.getItem('thinkdome_token') || '';
    if (token) headers.Authorization = `Bearer ${token}`;
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  function roleHasAccess(item, role) {
    const normalized = String(role || '').toUpperCase();
    if (['ADMIN', 'ADMINISTRATOR', 'SUPERADMIN', 'SUPER_ADMIN', 'ENTERPRISE_ADMIN'].includes(normalized)) return true;
    if (item.role_access) {
      const accessRole = Object.keys(item.role_access).find(key => String(key).toUpperCase() === normalized);
      if (accessRole !== undefined) return Boolean(item.role_access[accessRole]);
    }
    const allowed = item.allowed_roles || item.roles || [];
    return !allowed.length || allowed.map(value => String(value).toUpperCase()).includes(normalized);
  }

  function switchWorkspaceCard(cardId) {
    wmState.activeCard = cardId;

    // Hide all card pages, show selected
    document.querySelectorAll('.wm-card-page').forEach(p => {
      p.style.display = 'none';
      p.classList.remove('active');
    });
    const idx = { card1: 1, card2: 2, card3: 3, card4: 4 }[cardId] || 1;
    const page = document.getElementById('wmPageCard' + idx);
    if (page) {
      page.style.display = 'block';
      page.classList.add('active');
    }

    // Update nav card active states
    document.querySelectorAll('.wm-nav-card').forEach(c => c.classList.remove('active'));
    const navCard = document.querySelector(`.wm-nav-card[data-wm-card="${cardId}"]`);
    if (navCard) navCard.classList.add('active');
  }


  // ── Main Entry Point ────────────────────────────────────────────────────────
  async function loadWorkspaceManager() {

    console.log('[WorkspaceManager] Initializing 3-Card Workspace Manager...');
    const sessionRole = (localStorage.getItem('thinkdome_user_role') || '').toUpperCase();
    if (sessionRole) wmState.activeMapperRole = sessionRole;
    try {
      await Promise.all([
        refreshWorkspaceViewerData(),
        refreshRoleMapperData(),
        refreshBossRegistryData(),
      ]);
      renderCard1Viewer();
      renderCard2Sidebar();
      renderCard2RoleMapper();
      renderCard3BossCustomizer();
    } catch (err) {
      console.error('[WorkspaceManager] Initialization error:', err);
    }
  }

  // ── Data Fetchers ────────────────────────────────────────────────────────────
  async function refreshWorkspaceViewerData() {
    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        wmState.treeData = await global.thinkdome.call('thinkdome.core.ui.api.get_tree_view');
      } else {
        const res = await fetch('/v1/ui/tree', { headers: authHeaders() });
        wmState.treeData = await res.json();
      }
      wmState.treeData = wmState.treeData || { workspaces: [], pages: [] };
      // The storage-backed workspace desk and the developer registry are two
      // valid framework sources. Merge the desk view into the tree so the
      // Viewer and Sidebar card inspect what users actually receive.
      const token = localStorage.getItem('thinkdome_token') || '';
      const workspaceResponse = await fetch('/v1/workspaces', { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
      if (workspaceResponse?.ok) {
        const payload = await workspaceResponse.json();
        const desks = Array.isArray(payload) ? payload : payload.workspaces || [];
        wmState.treeData.workspaces = wmState.treeData.workspaces || [];
        wmState.treeData.pages = wmState.treeData.pages || [];
        for (const desk of desks) {
          const menuResponse = await fetch(`/v1/workspaces/${encodeURIComponent(desk.workspace_id)}/menu`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
          const pageResponse = await fetch(`/v1/workspaces/${encodeURIComponent(desk.workspace_id)}/pages`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
          const menu = menuResponse?.ok ? await menuResponse.json() : { config: [] };
          const pages = pageResponse?.ok ? await pageResponse.json() : { pages: [] };
          const workspace = wmState.treeData.workspaces.find(item => item.name === desk.workspace_id);
          const node = workspace || { id: `workspace:${desk.workspace_id}`, name: desk.workspace_id, label: desk.name, type: 'workspace', roles: [], children: [] };
          const items = (menu.config || []).flatMap(section => (section.items || []).map(item => ({ id: `item:${desk.workspace_id}:${item.target}`, name: item.target, label: item.label, type: 'menu_item', route: item.target, icon: item.icon, roles: [], children: [], workspace: desk.workspace_id })));
          node.children = [...(node.children || []).filter(item => item.type !== 'menu_item'), ...items];
          if (!workspace) wmState.treeData.workspaces.push(node);
          const knownPages = new Set(wmState.treeData.pages.map(page => page.name));
          (pages.pages || []).forEach(page => { if (!knownPages.has(page.page_id)) wmState.treeData.pages.push({ id: `page:${page.page_id}`, name: page.page_id, label: page.title, type: 'page', roles: page.allowed_roles || [], children: page.blocks || [] }); });
        }
      }
    } catch (e) {
      console.warn('Failed to fetch tree view, falling back to local state:', e);
      wmState.treeData = { workspaces: [], pages: [] };
    }
  }

  async function refreshRoleMapperData() {
    wmState.matrixData = { roles: ['SUPER_ADMIN', 'ADMIN', 'ENTERPRISE_ADMIN', 'AGENT_STANDARD', 'GUEST'], pages: [], modules: [], processes: [] };
    try {
      try {
        if (global.thinkdome && typeof global.thinkdome.call === 'function') {
          wmState.matrixData = await global.thinkdome.call('thinkdome.core.ui.api.get_role_permission_matrix');
        } else {
          const res = await fetch('/v1/ui/permissions/matrix', { headers: { Authorization: `Bearer ${localStorage.getItem('thinkdome_token') || ''}` } });
          if (res.ok) wmState.matrixData = await res.json();
        }
      } catch (matrixError) {
        console.warn('Permission catalog unavailable; using live UI manifests:', matrixError);
      }
      wmState.matrixData = wmState.matrixData || { roles: ['SUPER_ADMIN', 'ADMIN', 'ENTERPRISE_ADMIN', 'AGENT_STANDARD', 'GUEST'], pages: [], modules: [], processes: [] };
      // Workspace pages are runtime configuration, not a second hand-maintained
      // permission catalog. Merge the effective navigation manifest into the
      // mapper so every configured page is immediately visible here.
      let navigation = null;
      try {
        if (global.thinkdome?.ui?.getNavigation) navigation = await global.thinkdome.ui.getNavigation();
      } catch (navigationError) {
        console.warn('Navigation manifest unavailable; continuing with workspace pages:', navigationError);
      }
      if (navigation) {
        wmState.matrixData.pages = wmState.matrixData.pages || [];
        wmState.matrixData.modules = wmState.matrixData.modules || [];
        const roles = wmState.matrixData.roles?.length ? wmState.matrixData.roles : ['SUPER_ADMIN', 'ADMIN', 'ENTERPRISE_ADMIN', 'AGENT_STANDARD', 'GUEST'];
        wmState.matrixData.roles = roles;
        const access = allowed => Object.fromEntries(roles.map(role => [role, !allowed?.length || allowed.some(value => String(value).toUpperCase() === String(role).toUpperCase())]));
        const existing = new Set((wmState.matrixData.pages || []).map(page => page.name));
        (navigation.pages || []).forEach(page => {
          const name = page.name || page.route || page.page_id;
          if (!name || existing.has(name)) return;
          const allowed = page.allowed_roles || [];
          wmState.matrixData.pages.push({ name, title: page.title || name, entity_type: 'page', allowed_roles: allowed, role_access: access(allowed) });
          existing.add(name);
        });
        const moduleNames = new Set((wmState.matrixData.modules || []).map(item => item.name));
        (navigation.workspaces || []).forEach(workspace => {
          const name = workspace.name;
          if (!name || moduleNames.has(name)) return;
          const allowed = workspace.allowed_roles || [];
          wmState.matrixData.modules.push({ name, title: workspace.label || name, entity_type: 'workspace', allowed_roles: allowed, role_access: access(allowed) });
          moduleNames.add(name);
        });
      }
      // Also include pages stored in the selected workspace desk. These pages
      // are authoritative runtime UI, even when they have not been registered
      // in the developer-config registry.
      const token = localStorage.getItem('thinkdome_token') || '';
      const workspaceResponse = await fetch('/v1/workspaces', { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
      if (workspaceResponse?.ok) {
        const workspacePayload = await workspaceResponse.json();
        const workspaces = Array.isArray(workspacePayload) ? workspacePayload : workspacePayload.workspaces || [];
        const roles = wmState.matrixData.roles?.length ? wmState.matrixData.roles : ['SUPER_ADMIN', 'ADMIN', 'ENTERPRISE_ADMIN', 'AGENT_STANDARD', 'GUEST'];
        const access = allowed => Object.fromEntries(roles.map(role => [role, !allowed?.length || allowed.some(value => String(value).toUpperCase() === String(role).toUpperCase())]));
        const existing = new Set((wmState.matrixData.pages || []).map(page => page.name));
        const pageResponses = await Promise.all(workspaces.map(workspace => fetch(`/v1/workspaces/${encodeURIComponent(workspace.workspace_id)}/pages`, { headers: { Authorization: `Bearer ${token}` } }).then(response => response.ok ? response.json() : null).catch(() => null)));
        pageResponses.forEach(payload => (payload?.pages || []).forEach(page => {
          const name = page.page_id;
          if (!name || existing.has(name)) return;
          const allowed = page.allowed_roles || [];
          wmState.matrixData.pages.push({ name, title: page.title || name, entity_type: 'page', allowed_roles: allowed, role_access: access(allowed) });
          existing.add(name);
        }));
      }
      // RBAC permission catalog: this is separate from UI page visibility and
      // must remain visible in the same mapper for complete role governance.
      try {
        const permissionResponse = await fetch('/v1/permissions', { headers: { Authorization: `Bearer ${token}` } });
        const roleResponse = await fetch('/v1/roles', { headers: { Authorization: `Bearer ${token}` } });
        if (permissionResponse.ok && roleResponse.ok) {
          const permissions = await permissionResponse.json();
          const rolePayload = await roleResponse.json();
          const roleRecords = Array.isArray(rolePayload) ? rolePayload : rolePayload.roles || [];
          wmState.permissionRoleIds = Object.fromEntries(roleRecords.map(role => [role.name, role.id]));
          const permissionDetails = await Promise.all(roleRecords.map(role => fetch(`/v1/roles/${encodeURIComponent(role.id)}`, { headers: { Authorization: `Bearer ${token}` } }).then(response => response.ok ? response.json() : null).catch(() => null)));
          const roleNames = roleRecords.map(role => role.name).filter(Boolean);
          wmState.matrixData.roles = [...new Set([...(wmState.matrixData.roles || []), ...roleNames])];
          wmState.matrixData.permissions = (Array.isArray(permissions) ? permissions : permissions.permissions || []).map(permission => {
            const grantedRoleIds = new Set(permissionDetails.map((detail, index) => detail && (detail.permissions || []).some(item => item.id === permission.id) ? roleRecords[index]?.id : null).filter(Boolean));
            const roleAccess = Object.fromEntries(roleRecords.map((role, index) => [role.name, grantedRoleIds.has(role.id)]));
            return { name: permission.id, title: `${permission.module}.${permission.resource}.${permission.action}`, description: permission.description || '', entity_type: 'permission', role_access: roleAccess };
          });
        }
      } catch (permissionError) {
        console.warn('Role permission module unavailable:', permissionError);
        wmState.matrixData.permissions = wmState.matrixData.permissions || [];
      }
    } catch (e) {
      console.warn('Failed to fetch matrix data:', e);
      wmState.matrixData = { roles: [], pages: [], modules: [], processes: [] };
    }
  }

  async function refreshBossRegistryData() {
    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        wmState.registryData = await global.thinkdome.call('thinkdome.core.ui.api.get_registry_summary');
      } else {
        const res = await fetch('/v1/ui/registry/summary', { headers: authHeaders() });
        wmState.registryData = await res.json();
      }
    } catch (e) {
      console.warn('Failed to fetch registry summary:', e);
      wmState.registryData = { registered_items: [], registered_components: [], versions: [] };
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // CARD 1: WORKSPACE VIEWER (Tree & Group Views, Role Filter, Interactive Edit/Delete)
  // ─────────────────────────────────────────────────────────────────────────────

  function renderCard1Viewer() {
    const container = document.getElementById('wmViewerCanvas');
    const roleSelect = document.getElementById('wmViewerRoleSelect');
    const toggleTreeBtn = document.getElementById('wmViewerBtnTree');
    const toggleGroupBtn = document.getElementById('wmViewerBtnGroup');

    if (!container) return;

    // Sync toggle buttons
    if (toggleTreeBtn && toggleGroupBtn) {
      toggleTreeBtn.classList.toggle('active', wmState.viewMode === 'tree');
      toggleGroupBtn.classList.toggle('active', wmState.viewMode === 'group');
    }

    // Populate role filter dropdown
    if (roleSelect && wmState.matrixData?.roles) {
      const current = roleSelect.value || wmState.activeRoleFilter;
      roleSelect.replaceChildren(
        new Option('All Roles (Super Admin View)', '__all__'),
        ...wmState.matrixData.roles.map(r => new Option(`Role: ${r}`, r, false, r === current))
      );
      roleSelect.value = current;
    }

    container.replaceChildren();

    const selectedRole = wmState.activeRoleFilter;

    if (wmState.viewMode === 'tree') {
      container.appendChild(buildTreeViewDOM(selectedRole));
    } else {
      container.appendChild(buildGroupViewDOM(selectedRole));
    }
  }

  function setViewerMode(mode) {
    wmState.viewMode = mode;
    renderCard1Viewer();
  }

  function setViewerRoleFilter(role) {
    wmState.activeRoleFilter = role;
    renderCard1Viewer();
  }

  function renderCard2Sidebar() {
    const container = document.getElementById('wmSidebarCanvas');
    if (!container) return;
    container.replaceChildren();
    const workspaces = wmState.treeData?.workspaces || [];
    if (!workspaces.length) {
      const empty = document.createElement('div'); empty.className = 'wm-empty-state';
      empty.textContent = 'No sidebar or workspace is configured. Add it through The Boss registration gateway.';
      container.appendChild(empty); return;
    }
    workspaces.forEach(workspace => {
      const card = document.createElement('section'); card.className = 'wm-sidebar-group';
      const head = document.createElement('div'); head.className = 'wm-group-head';
      const title = document.createElement('strong'); title.textContent = workspace.label || workspace.name;
      const edit = document.createElement('button'); edit.className = 'btn btn-ghost btn-xs'; edit.textContent = '✎ Edit'; edit.onclick = () => promptInlineEditNode(workspace);
      const del = document.createElement('button'); del.className = 'btn btn-danger-ghost btn-xs'; del.textContent = '⌫ Delete'; del.onclick = () => confirmInteractiveDelete(workspace);
      const actions = document.createElement('div'); actions.className = 'wm-node-controls'; actions.append(edit, del); head.append(title, actions); card.appendChild(head);
      const items = document.createElement('div'); items.className = 'wm-sidebar-items';
      (workspace.children || []).forEach(item => {
        item.workspace = workspace.name;
        const row = document.createElement('div'); row.className = 'wm-sidebar-item';
        const label = document.createElement('span'); label.textContent = item.label || item.name;
        const route = document.createElement('small'); route.textContent = item.route || 'configured item';
        const button = document.createElement('button'); button.className = 'btn btn-ghost btn-xs'; button.textContent = '✎'; button.title = 'Edit sidebar item'; button.onclick = () => promptInlineEditNode(item);
        row.append(label, route, button); items.appendChild(row);
      });
      if (!items.children.length) { const empty = document.createElement('small'); empty.className = 'wm-empty-sub'; empty.textContent = 'No sidebar items configured.'; items.appendChild(empty); }
      card.appendChild(items); container.appendChild(card);
    });
  }

  // Build Interactive Tree Structure DOM
  function buildTreeViewDOM(roleFilter) {
    const root = document.createElement('div');
    root.className = 'wm-tree-root';

    const wsNodes = wmState.treeData?.workspaces || [];
    const pageNodes = wmState.treeData?.pages || [];

    if (!wsNodes.length && !pageNodes.length) {
      const empty = document.createElement('div');
      empty.className = 'wm-empty-state';
      empty.textContent = 'No registered workspace or page structures found in system registry.';
      root.appendChild(empty);
      return root;
    }

    // Section 1: Workspaces & Sidebar Trees
    const wsHeader = document.createElement('div');
    wsHeader.className = 'wm-tree-section-header';
    wsHeader.innerHTML = '<span>▦ Registered Workspaces & Sidebar Trees</span>';
    root.appendChild(wsHeader);

    wsNodes.forEach(ws => {
      // Role check
      if (roleFilter !== '__all__' && !roleHasAccess(ws, roleFilter)) {
        return;
      }
      root.appendChild(createTreeNodeElement(ws, 'workspace', roleFilter));
    });

    // Section 2: Registered Dynamic Pages Trees
    const pageHeader = document.createElement('div');
    pageHeader.className = 'wm-tree-section-header';
    pageHeader.style.marginTop = '16px';
    pageHeader.innerHTML = '<span>📄 Registered Pages & Layout Components Tree</span>';
    root.appendChild(pageHeader);

    pageNodes.forEach(p => {
      if (roleFilter !== '__all__' && !roleHasAccess(p, roleFilter)) {
        return;
      }
      root.appendChild(createTreeNodeElement(p, 'page', roleFilter));
    });

    const partNodes = wmState.treeData?.ui_parts || [];
    if (partNodes.length) {
      const partHeader = document.createElement('div');
      partHeader.className = 'wm-tree-section-header'; partHeader.style.marginTop = '16px';
      partHeader.innerHTML = '<span>🧩 Registered UI Parts & Components</span>';
      root.appendChild(partHeader);
      partNodes.forEach(part => {
        if (roleFilter !== '__all__' && !roleHasAccess(part, roleFilter)) return;
        root.appendChild(createTreeNodeElement(part, 'component', roleFilter));
      });
    }

    return root;
  }

  function createTreeNodeElement(node, nodeType, roleFilter) {
    const item = document.createElement('div');
    item.className = `wm-tree-node wm-node-${nodeType}`;
    item.dataset.id = node.id;

    const row = document.createElement('div');
    row.className = 'wm-tree-row';

    // Expand toggle icon
    const hasChildren = node.children && node.children.length > 0;
    const expander = document.createElement('span');
    expander.className = 'wm-tree-expander';
    expander.textContent = hasChildren ? '▼' : '•';
    if (hasChildren) {
      expander.onclick = (e) => {
        e.stopPropagation();
        const childContainer = item.querySelector('.wm-tree-children');
        if (childContainer) {
          const isHidden = childContainer.style.display === 'none';
          childContainer.style.display = isHidden ? 'block' : 'none';
          expander.textContent = isHidden ? '▼' : '►';
        }
      };
    }
    row.appendChild(expander);

    // Node Icon
    const icon = document.createElement('span');
    icon.className = 'wm-node-icon';
    icon.textContent = node.icon || (nodeType === 'workspace' ? '▦' : nodeType === 'page' ? '📄' : '▫');
    row.appendChild(icon);

    // Label / Title (Editable)
    const labelSpan = document.createElement('span');
    labelSpan.className = 'wm-node-label';
    labelSpan.textContent = node.label || node.name;
    row.appendChild(labelSpan);

    // Type Tag
    const typeBadge = document.createElement('span');
    typeBadge.className = 'wm-node-type-badge';
    typeBadge.textContent = node.type || nodeType;
    row.appendChild(typeBadge);

    // Role tags
    if (node.roles && node.roles.length) {
      const roleBadge = document.createElement('span');
      roleBadge.className = 'wm-node-role-badge';
      roleBadge.textContent = node.roles.join(', ');
      row.appendChild(roleBadge);
    }

    // Action Controls: Interactive Edit & Delete
    const controls = document.createElement('div');
    controls.className = 'wm-node-controls';

    const editBtn = document.createElement('button');
    editBtn.className = 'btn btn-ghost btn-xs';
    editBtn.innerHTML = '✎ Edit';
    editBtn.onclick = (e) => {
      e.stopPropagation();
      promptInlineEditNode(node);
    };
    controls.appendChild(editBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger-ghost btn-xs';
    delBtn.innerHTML = '⌫ Delete';
    delBtn.onclick = (e) => {
      e.stopPropagation();
      confirmInteractiveDelete(node);
    };
    controls.appendChild(delBtn);

    row.appendChild(controls);
    item.appendChild(row);

    // Render children recursively
    if (hasChildren) {
      const childrenDiv = document.createElement('div');
      childrenDiv.className = 'wm-tree-children';

      node.children.forEach(child => {
        if (roleFilter !== '__all__' && !roleHasAccess(child, roleFilter)) {
          return;
        }
        childrenDiv.appendChild(createTreeNodeElement(child, child.type || 'component', roleFilter));
      });
      item.appendChild(childrenDiv);
    }

    return item;
  }

  // Build Interactive Group View DOM
  function buildGroupViewDOM(roleFilter) {
    const root = document.createElement('div');
    root.className = 'wm-group-grid';

    const pages = wmState.treeData?.pages || [];

    if (!pages.length) {
      const empty = document.createElement('div');
      empty.className = 'wm-empty-state';
      empty.textContent = 'No page groups available for rendering.';
      root.appendChild(empty);
      return root;
    }

    pages.forEach(p => {
      if (roleFilter !== '__all__' && !roleHasAccess(p, roleFilter)) {
        return;
      }

      const card = document.createElement('div');
      card.className = 'wm-group-card';

      const head = document.createElement('div');
      head.className = 'wm-group-head';
      const headInfo = document.createElement('div');
      const title = document.createElement('strong');
      title.className = 'wm-group-title';
      title.textContent = p.label || p.name;
      const roles = document.createElement('span');
      roles.className = 'wm-node-role-badge';
      roles.textContent = p.roles.length ? p.roles.join(', ') : 'Everyone';
      headInfo.append(title, roles);
      const controls = document.createElement('div');
      controls.className = 'wm-node-controls';
      const edit = document.createElement('button');
      edit.className = 'btn btn-ghost btn-xs';
      edit.textContent = '✎';
      edit.title = 'Edit page';
      edit.onclick = () => global.wmPromptInlineEditPage(p.name);
      const remove = document.createElement('button');
      remove.className = 'btn btn-danger-ghost btn-xs';
      remove.textContent = '⌫';
      remove.title = 'Delete page';
      remove.onclick = () => global.wmConfirmDeletePage(p.name);
      controls.append(edit, remove);
      head.append(headInfo, controls);
      card.appendChild(head);

      const body = document.createElement('div');
      body.className = 'wm-group-body';

      if (p.children && p.children.length) {
        p.children.forEach(c => {
          const itemRow = document.createElement('div');
          itemRow.className = 'wm-group-item-row';
          const icon = document.createElement('span');
          icon.className = 'wm-node-icon';
          icon.textContent = '✦';
          const itemLabel = document.createElement('span');
          const itemTitle = document.createElement('strong');
          itemTitle.textContent = c.label || c.name || 'Untitled';
          const itemType = document.createElement('small');
          itemType.textContent = ` (${c.type || 'component'})`;
          itemLabel.append(itemTitle, itemType);
          const itemEdit = document.createElement('button');
          itemEdit.className = 'btn btn-ghost btn-xs';
          itemEdit.style.marginLeft = 'auto';
          itemEdit.textContent = '✎ Edit';
          itemEdit.onclick = () => global.wmPromptInlineEditNodeById(c.id);
          itemRow.append(icon, itemLabel, itemEdit);
          body.appendChild(itemRow);
        });
      } else {
        const noBlocks = document.createElement('div');
        noBlocks.className = 'wm-empty-sub';
        noBlocks.textContent = 'No layout blocks configured.';
        body.appendChild(noBlocks);
      }

      card.appendChild(body);
      root.appendChild(card);
    });

    return root;
  }

  // Interactive Edit Prompt
  function promptInlineEditNode(node) {
    const newLabel = prompt(`Edit title/label for ${node.type} (${node.name}):`, node.label || node.name);
    if (newLabel && newLabel.trim()) {
      node.label = newLabel.trim();
      // Sync back to registry / developer config via API
      registerOrUpdateNode(node);
    }
  }

  async function registerOrUpdateNode(node) {
    try {
      const payload = {
        name: node.name,
        title: node.label,
        label: node.label,
        entity_type: node.type === 'workspace' ? 'workspace' : node.type === 'menu_item' ? 'menu_item' : 'page',
        allowed_roles: node.roles || []
      };
      if (node.type === 'menu_item') {
        await global.thinkdome.call('thinkdome.core.ui.api.update_menu_item', { workspace: node.workspace, item_name: node.name, data: { name: node.name, label: node.label, route: node.route || '', type: 'page', allowed_roles: node.roles || [] } });
        await loadWorkspaceManager();
        if (typeof global.showToast === 'function') global.showToast(`Updated '${node.label}' successfully.`, 'success');
        return;
      }
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.register_entity', { config: payload });
      } else {
        const response = await fetch('/v1/ui/registry/register', {
          method: 'POST',
          headers: authHeaders(true),
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Registry update was rejected by the server.');
      }
      await loadWorkspaceManager();
      if (typeof global.showToast === 'function') global.showToast(`Updated '${node.label}' successfully.`, 'success');
    } catch (e) {
      alert(`Failed to update node: ${e.message}`);
    }
  }

  async function confirmInteractiveDelete(node) {
    if (!confirm(`Are you sure you want to delete ${node.type} '${node.label || node.name}'? This action cannot be undone.`)) {
      return;
    }
    try {
      if (node.type === 'workspace') {
        await global.thinkdome.call('thinkdome.core.ui.api.delete_workspace', { name: node.name });
      } else if (node.type === 'page') {
        await global.thinkdome.call('thinkdome.core.ui.api.delete_page', { name: node.name });
      } else if (node.type === 'component') {
        await global.thinkdome.call('thinkdome.core.ui.api.delete_component', { name: node.name });
      } else if (node.type === 'menu_item') {
        await global.thinkdome.call('thinkdome.core.ui.api.remove_menu_item', { workspace: node.workspace, item_name: node.name });
      }
      await loadWorkspaceManager();
      if (typeof global.showToast === 'function') global.showToast(`Deleted '${node.name}'`, 'info');
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    }
  }

  // Expose global inline edit/delete helpers
  global.wmPromptInlineEditPage = function (pageName) {
    const page = wmState.treeData?.pages?.find(p => p.name === pageName);
    if (page) promptInlineEditNode(page);
  };

  global.wmConfirmDeletePage = function (pageName) {
    confirmInteractiveDelete({ type: 'page', name: pageName, label: pageName });
  };

  global.wmPromptInlineEditNodeById = function (nodeId) {
    alert(`Editing component node '${nodeId}'. Use Card 3 (The Boss) for granular block editing.`);
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // CARD 2: PAGE & ROLE MAPPER (Privilege Giver: Pages, Modules, Processes + Granted View)
  // ─────────────────────────────────────────────────────────────────────────────

  function renderCard2RoleMapper() {
    const matrixContainer = document.getElementById('wmRoleMatrixContainer');
    const grantedContainer = document.getElementById('wmGrantedViewContainer');
    const roleSelect = document.getElementById('wmMapperRoleSelect');

    if (!matrixContainer) return;

    // The tree endpoint is the runtime UI source of truth. If the optional
    // permission catalog is empty or unavailable, promote those live page
    // nodes into the mapper instead of showing a misleading zero-page state.
    wmState.matrixData = wmState.matrixData || { roles: [], pages: [], modules: [], processes: [] };
    wmState.matrixData.pages = wmState.matrixData.pages || [];
    const matrixRoles = wmState.matrixData.roles?.length ? wmState.matrixData.roles : ['SUPER_ADMIN', 'ADMIN', 'ENTERPRISE_ADMIN', 'AGENT_STANDARD', 'GUEST'];
    wmState.matrixData.roles = matrixRoles;
    const knownPages = new Set(wmState.matrixData.pages.map(page => page.name));
    (wmState.treeData?.pages || []).forEach(page => {
      const name = page.name || page.route;
      if (!name || knownPages.has(name)) return;
      const allowed = page.roles || [];
      wmState.matrixData.pages.push({ name, title: page.label || name, allowed_roles: allowed, role_access: Object.fromEntries(matrixRoles.map(role => [role, !allowed.length || allowed.some(value => String(value).toUpperCase() === String(role).toUpperCase())])) });
      knownPages.add(name);
    });

    // Populate role selector for mapper
    if (roleSelect && wmState.matrixData?.roles) {
      if (wmState.activeMapperRole && !wmState.matrixData.roles.includes(wmState.activeMapperRole)) wmState.matrixData.roles = [...wmState.matrixData.roles, wmState.activeMapperRole];
      roleSelect.replaceChildren(
        ...wmState.matrixData.roles.map(r => new Option(`Target Role: ${r}`, r, false, r === wmState.activeMapperRole))
      );
      roleSelect.value = wmState.activeMapperRole;
    }

    renderMapperTabs();
    renderMapperMatrix(matrixContainer);
    renderMapperGrantedView(grantedContainer);
  }

  function renderMapperTabs() {
    const tabPages = document.getElementById('wmMapperTabPages');
    const tabModules = document.getElementById('wmMapperTabModules');
    const tabProcesses = document.getElementById('wmMapperTabProcesses');
    const tabPermissions = document.getElementById('wmMapperTabPermissions');
    const tabUiParts = document.getElementById('wmMapperTabUiParts');

    if (tabPages && tabModules && tabProcesses && tabPermissions && tabUiParts) {
      tabPages.classList.toggle('active', wmState.activeMapperTab === 'pages');
      tabModules.classList.toggle('active', wmState.activeMapperTab === 'modules');
      tabProcesses.classList.toggle('active', wmState.activeMapperTab === 'processes');
      tabPermissions.classList.toggle('active', wmState.activeMapperTab === 'permissions');
      tabUiParts.classList.toggle('active', wmState.activeMapperTab === 'ui_parts');
    }
  }

  function setMapperTab(tabName) {
    wmState.activeMapperTab = tabName;
    renderCard2RoleMapper();
  }

  function setMapperRole(roleName) {
    wmState.activeMapperRole = roleName;
    renderCard2RoleMapper();
  }

  function renderMapperMatrix(container) {
    container.replaceChildren();

    const roles = wmState.matrixData?.roles || ['SUPER_ADMIN', 'ADMIN', 'AGENT_STANDARD'];
    const activeTab = wmState.activeMapperTab;
    const items = wmState.matrixData?.[activeTab] || [];

    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'wm-empty-state';
      empty.textContent = `No ${activeTab} configured in permission catalog.`;
      container.appendChild(empty);
      return;
    }

    const table = document.createElement('table');
    table.className = 'wm-matrix-table';

    // Header
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    const entityHead = document.createElement('th');
    entityHead.textContent = `${activeTab.toUpperCase()} ENTITY`;
    headRow.appendChild(entityHead);
    roles.forEach(r => {
      const th = document.createElement('th');
      th.className = r === wmState.activeMapperRole ? 'wm-active-col' : '';
      th.textContent = r;
      headRow.appendChild(th);
    });
    const actionsHead = document.createElement('th');
    actionsHead.textContent = 'ACTIONS';
    headRow.appendChild(actionsHead);
    thead.appendChild(headRow);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    items.forEach(item => {
      const row = document.createElement('tr');

      const nameCell = document.createElement('td');
      const itemTitle = document.createElement('strong');
      itemTitle.textContent = item.title || item.name;
      const itemName = document.createElement('small');
      itemName.className = 'mono-muted';
      itemName.textContent = item.name;
      nameCell.append(itemTitle, document.createElement('br'), itemName);
      row.appendChild(nameCell);

      roles.forEach(r => {
        const cell = document.createElement('td');
        cell.className = `wm-matrix-cell ${r === wmState.activeMapperRole ? 'wm-active-col' : ''}`;
        const isGranted = roleHasAccess(item, r);

        const badge = document.createElement('button');
        badge.className = `wm-grant-badge ${isGranted ? 'granted' : 'denied'}`;
        badge.innerHTML = isGranted ? '✓ GRANTED' : '✕ DENIED';
        badge.title = `Click to toggle privilege for ${r}`;
        badge.onclick = () => toggleRolePrivilege(activeTab, item.name, r, !isGranted);

        cell.appendChild(badge);
        row.appendChild(cell);
      });

      // Quick Actions per row
      const actionCell = document.createElement('td');
      const actionGroup = document.createElement('div');
      actionGroup.className = 'btn-group';
      const grantButton = document.createElement('button');
      grantButton.className = 'btn btn-xs btn-success';
      grantButton.textContent = `Grant ${wmState.activeMapperRole}`;
      grantButton.onclick = () => toggleRolePrivilege(activeTab, item.name, wmState.activeMapperRole, true);
      const denyButton = document.createElement('button');
      denyButton.className = 'btn btn-xs btn-danger';
      denyButton.textContent = 'Deny';
      denyButton.onclick = () => toggleRolePrivilege(activeTab, item.name, wmState.activeMapperRole, false);
      actionGroup.append(grantButton, denyButton);
      actionCell.appendChild(actionGroup);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    });

    table.appendChild(tbody);
    container.appendChild(table);
  }

  // Render "Granted View" panel showing what the selected role receives
  function renderMapperGrantedView(container) {
    if (!container) return;
    container.replaceChildren();

    const role = wmState.activeMapperRole;

    const head = document.createElement('div');
    head.className = 'wm-granted-head';
    const headTitle = document.createElement('span');
    headTitle.append('👁 GRANTED PRIVILEGE SUMMARY FOR: ');
    const roleStrong = document.createElement('strong');
    roleStrong.textContent = role;
    headTitle.appendChild(roleStrong);
    const headHint = document.createElement('small');
    headHint.textContent = 'Live preview of accessible interface modules and processes';
    head.append(headTitle, headHint);
    container.appendChild(head);

    const pages = (wmState.matrixData?.pages || []).filter(p => roleHasAccess(p, role));
    const modules = (wmState.matrixData?.modules || []).filter(m => roleHasAccess(m, role));
    const processes = (wmState.matrixData?.processes || []).filter(pr => roleHasAccess(pr, role));
    const permissions = (wmState.matrixData?.permissions || []).filter(permission => roleHasAccess(permission, role));
    const uiParts = (wmState.matrixData?.ui_parts || []).filter(part => roleHasAccess(part, role));

    const list = document.createElement('div');
    list.className = 'wm-granted-list';

    [['📄 Granted Pages', pages], ['▦ Granted Modules', modules], ['⚡ Granted Processes', processes],
      ['🔐 Granted Role Permissions', permissions], ['🧩 Granted UI Parts', uiParts]].forEach(([label, entries]) => {
      const section = document.createElement('div');
      section.className = 'wm-granted-section';
      const sectionTitle = document.createElement('strong');
      sectionTitle.textContent = `${label} (${entries.length})`;
      const cloud = document.createElement('div');
      cloud.className = 'wm-tag-cloud';
      if (entries.length) entries.forEach(entry => {
        const tag = document.createElement('span');
        tag.className = 'wm-tag-granted';
        tag.textContent = entry.title || entry.name;
        cloud.appendChild(tag);
      });
      else {
        const empty = document.createElement('em');
        empty.className = 'mono-muted';
        empty.textContent = 'Nothing granted';
        cloud.appendChild(empty);
      }
      section.append(sectionTitle, cloud);
      list.appendChild(section);
    });

    container.appendChild(list);
  }

  async function toggleRolePrivilege(category, entityName, role, grant) {
    try {
      const action = grant ? 'grant' : 'deny';
      if (category === 'permissions') {
        const roleId = wmState.permissionRoleIds?.[role];
        if (!roleId) throw new Error(`Role '${role}' is not available in the RBAC service.`);
        const token = localStorage.getItem('thinkdome_token') || '';
        const endpoint = `/v1/roles/${encodeURIComponent(roleId)}/permissions${grant ? '' : `/${encodeURIComponent(entityName)}`}`;
        const response = await fetch(endpoint, { method: grant ? 'POST' : 'DELETE', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, ...(grant ? { body: JSON.stringify({ permission_id: entityName }) } : {}) });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Role permission update failed');
      } else if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.bulk_update_roles', {
          entity_type: category === 'pages' ? 'page' : category === 'modules' ? 'workspace' : category === 'ui_parts' ? 'component' : 'process',
          target_names: [entityName],
          role: role,
          action: action
        });
      } else {
        const response = await fetch('/v1/ui/permissions/bulk', {
          method: 'POST',
          headers: authHeaders(true),
          body: JSON.stringify({
            entity_type: category === 'pages' ? 'page' : category === 'modules' ? 'workspace' : category === 'ui_parts' ? 'component' : category === 'permissions' ? 'permission' : 'process',
            target_names: [entityName],
            role: role,
            action: action
          })
        });
        if (!response.ok) throw new Error('Privilege update was rejected by the server.');
      }
      await refreshRoleMapperData();
      renderCard2RoleMapper();
      renderCard1Viewer();
    } catch (e) {
      alert(`Privilege update failed: ${e.message}`);
    }
  }

  global.wmBulkGrantRole = function (category, entityName, role, action) {
    toggleRolePrivilege(category, entityName, role, action === 'grant');
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // CARD 3: STANDARD UI RENDERER CUSTOMIZER — "THE BOSS" (CENTRAL REGISTRY & WHITELIST)
  // ─────────────────────────────────────────────────────────────────────────────

  function renderCard3BossCustomizer() {
    renderBossTabs();

    const regContainer = document.getElementById('wmBossRegistryTab');
    const formContainer = document.getElementById('wmBossRegisterTab');
    const designerContainer = document.getElementById('wmBossDesignerTab');
    const versionContainer = document.getElementById('wmBossVersionsTab');

    if (regContainer) regContainer.style.display = wmState.activeBossTab === 'registry' ? 'block' : 'none';
    if (formContainer) formContainer.style.display = wmState.activeBossTab === 'register' ? 'block' : 'none';
    if (designerContainer) designerContainer.style.display = wmState.activeBossTab === 'designer' ? 'block' : 'none';
    if (versionContainer) versionContainer.style.display = wmState.activeBossTab === 'versions' ? 'block' : 'none';

    if (wmState.activeBossTab === 'registry' && regContainer) renderBossRegistryTable(regContainer);
    if (wmState.activeBossTab === 'register' && formContainer) renderBossRegistrationForm(formContainer);
    if (wmState.activeBossTab === 'designer' && designerContainer) renderBossPageDesigner(designerContainer);
    if (wmState.activeBossTab === 'versions' && versionContainer) renderBossVersionsTable(versionContainer);

    // Update Boss Live Indicator Counts
    const regCount = document.getElementById('wmBossCountRegistered');
    const verCount = document.getElementById('wmBossCountVersions');
    const compCount = document.getElementById('wmBossCountComponents');

    if (regCount) regCount.textContent = wmState.registryData?.total_registered || '0';
    if (verCount) verCount.textContent = wmState.registryData?.versions?.length || '0';
    if (compCount) compCount.textContent = wmState.registryData?.registered_components?.length || '0';
  }

  function renderBossTabs() {
    const tabs = ['register', 'registry', 'designer', 'versions'];
    tabs.forEach(t => {
      const btn = document.getElementById(`wmBossTab_${t}`);
      if (btn) btn.classList.toggle('active', wmState.activeBossTab === t);
    });
  }

  function setBossTab(tabName) {
    wmState.activeBossTab = tabName;
    renderCard3BossCustomizer();
  }

  // Boss Tab 1: Registration Form ("Everything registers here first")
  function renderBossRegistrationForm(container) {
    if (container.children.length > 0) return; // Form already built

    container.innerHTML = `
      <div class="wm-card-box">
        <div class="wm-card-head">
          <span class="workspace-card-kicker">THE BOSS REGISTRY GATEWAY</span>
          <h3>Register New UI Part / Page / Component</h3>
          <p class="sub">Every component, page, or workspace must be registered through this framework gatekeeper first.</p>
        </div>
        <form onsubmit="wmSubmitBossRegistration(event)">
          <div class="wm-form-grid">
            <div class="field">
              <label>Entity Type *</label>
              <select id="wmRegType" class="form-select">
                <option value="page">Dynamic Page</option>
                <option value="workspace">Workspace Container</option>
                <option value="component">Custom UI Component</option>
                <option value="menu_item">Sidebar Menu Item</option>
              </select>
            </div>
            <div class="field">
              <label>Identifier Name *</label>
              <input type="text" id="wmRegName" class="form-input" placeholder="e.g. analytics_dashboard" required />
            </div>
            <div class="field">
              <label>Title / Label</label>
              <input type="text" id="wmRegTitle" class="form-input" placeholder="e.g. Executive Analytics" />
            </div>
            <div class="field">
              <label>Role Whitelist (Allowed Roles)</label>
              <input type="text" id="wmRegRoles" class="form-input" placeholder="SUPER_ADMIN, ADMIN, AGENT_STANDARD" />
              <small class="mono-muted">Comma-separated. Empty means public/all roles.</small>
            </div>
          </div>
          <div class="field" style="margin-top:14px;">
            <label>Declarative Configuration (JSON Layout / Schema)</label>
            <textarea id="wmRegConfigJson" class="form-textarea" rows="4" placeholder='{"icon": "chart", "sequence": 10, "layout": []}'></textarea>
          </div>
          <div class="wm-form-actions">
            <button type="submit" class="btn btn-primary">✦ Register in Framework</button>
            <span id="wmRegStatus" class="mono-muted"></span>
          </div>
        </form>
      </div>
    `;
  }

  global.wmSubmitBossRegistration = async function (e) {
    e.preventDefault();
    const type = document.getElementById('wmRegName') ? document.getElementById('wmRegType').value : 'page';
    const name = document.getElementById('wmRegName').value.trim();
    const title = document.getElementById('wmRegTitle').value.trim() || name;
    const rolesRaw = document.getElementById('wmRegRoles').value.trim();
    const jsonRaw = document.getElementById('wmRegConfigJson').value.trim();

    const allowed_roles = rolesRaw ? rolesRaw.split(',').map(r => r.trim()) : [];
    let configObj = {};
    if (jsonRaw) {
      try {
        configObj = JSON.parse(jsonRaw);
      } catch (err) {
        alert('Invalid JSON in Declarative Configuration!');
        return;
      }
    }

    // Declarative JSON may add layout metadata, but cannot override the
    // identity and whitelist selected in the form.
    const payload = {
      ...configObj,
      entity_type: type,
      name: name,
      title: title,
      label: title,
      allowed_roles: allowed_roles,
    };

    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.register_entity', { config: payload });
      } else {
        const response = await fetch('/v1/ui/registry/register', {
          method: 'POST',
          headers: authHeaders(true),
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Registration was rejected by the server.');
      }
      await loadWorkspaceManager();
      setBossTab('registry');
      if (typeof global.showToast === 'function') global.showToast(`Successfully registered '${name}' in central registry!`, 'success');
    } catch (err) {
      alert(`Registration failed: ${err.message}`);
    }
  };

  // Boss Tab 2: Registry Table
  function renderBossRegistryTable(container) {
    container.replaceChildren();

    const items = wmState.registryData?.registered_items || [];

    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'wm-empty-state';
      empty.textContent = 'No registered items found in UIManager developer config table.';
      container.appendChild(empty);
      return;
    }

    const table = document.createElement('table');
    table.className = 'wm-matrix-table';

    const columns = ['TYPE', 'REGISTERED KEY', 'TITLE / LABEL', 'MANAGED SOURCE', 'ROLE WHITELIST', 'VERSION HASH', 'ACTIONS'];
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    columns.forEach(column => { const th = document.createElement('th'); th.textContent = column; headerRow.appendChild(th); });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    items.forEach(item => {
      const row = document.createElement('tr');
      const values = [item.entity_type, item.managed_key, item.title, item.managed_source,
        (item.allowed_roles || []).length ? item.allowed_roles.join(', ') : 'ALL ROLES', item.version_hash];
      values.forEach((value, index) => {
        const cell = document.createElement('td');
        if (index === 0) { const badge = document.createElement('span'); badge.className = 'wm-node-type-badge'; badge.textContent = value; cell.appendChild(badge); }
        else if (index === 1) { const strong = document.createElement('strong'); strong.className = 'mono-muted'; strong.textContent = value; cell.appendChild(strong); }
        else if (index === 2) { const strong = document.createElement('strong'); strong.textContent = value; cell.appendChild(strong); }
        else if (index === 3) { const small = document.createElement('small'); small.textContent = value; cell.appendChild(small); }
        else if (index === 4) { const badge = document.createElement('span'); badge.className = 'wm-node-role-badge'; badge.textContent = value; cell.appendChild(badge); }
        else { const code = document.createElement('code'); code.className = 'mono-muted'; code.textContent = value; cell.appendChild(code); }
        row.appendChild(cell);
      });
      const actionCell = document.createElement('td');
      const edit = document.createElement('button');
      edit.className = 'btn btn-xs btn-ghost';
      edit.textContent = '✎ Whitelist / Edit';
      edit.onclick = () => global.wmBossEditRegistryItem(item.managed_key);
      actionCell.appendChild(edit);
      row.appendChild(actionCell);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    container.appendChild(table);
  }

  global.wmBossEditRegistryItem = function (key) {
    const item = wmState.registryData?.registered_items?.find(i => i.managed_key === key);
    if (!item) return;

    const newRoles = prompt(`Update Whitelisted Roles for '${item.managed_key}' (comma separated):`, item.allowed_roles.join(', '));
    if (newRoles !== null) {
      const allowed_roles = newRoles ? newRoles.split(',').map(r => r.trim()) : [];
      item.config.allowed_roles = allowed_roles;
      item.config.name = item.managed_key;
      item.config.entity_type = item.entity_type;
      wmSubmitBossRegistrationObj(item.config);
    }
  };

  async function wmSubmitBossRegistrationObj(configObj) {
    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.register_entity', { config: configObj });
      } else {
        const response = await fetch('/v1/ui/registry/register', {
          method: 'POST',
          headers: authHeaders(true),
          body: JSON.stringify(configObj)
        });
        if (!response.ok) throw new Error('Registry update was rejected by the server.');
      }
      await loadWorkspaceManager();
      if (typeof global.showToast === 'function') global.showToast('Registry item updated.', 'success');
    } catch (e) {
      alert(`Update failed: ${e.message}`);
    }
  }

  // Boss Tab 3: Visual Page Designer
  function renderBossPageDesigner(container) {
    container.innerHTML = `
      <div class="workspace-editor-panel pages-panel">
        <div class="workspace-panel-head">
          <div>
            <span class="workspace-panel-icon">🎨</span>
            <div>
              <h3>Standard UI Renderer Customizer</h3>
              <p>Design blocks and layout for registered framework pages.</p>
            </div>
          </div>
        </div>
        <div id="wmBossInlineCustomizer" class="workspace-inline-customizer">
          <div class="workspace-inline-head">
            <div><span class="workspace-label">Standard UI Customizer</span><strong>Selected Page Designer</strong></div>
            <button type="button" class="btn btn-primary btn-sm" onclick="wmSaveBossDesignerPage()">Save &amp; Publish Page</button>
          </div>
          <div class="workspace-inline-fields">
            <label class="field-label">Target Page
              <select id="wmBossDesignerPageSelect" class="form-select" onchange="wmLoadBossDesignerPage(this.value)"></select>
            </label>
            <label class="field-label">Title
              <input id="wmBossDesignerTitle" class="form-input" />
            </label>
          </div>
          <div class="workspace-inline-editor-grid">
            <div>
              <div class="workspace-inline-section-title">Add Component Blocks</div>
              <div class="workspace-block-palette workspace-block-palette-inline">
                <button type="button" class="workspace-block-add" onclick="wmAddBossBlock('heading')"><strong>Heading</strong><small>Section Title</small></button>
                <button type="button" class="workspace-block-add" onclick="wmAddBossBlock('card')"><strong>Card</strong><small>Info Tile</small></button>
                <button type="button" class="workspace-block-add" onclick="wmAddBossBlock('stat')"><strong>Stat</strong><small>Metric Figure</small></button>
                <button type="button" class="workspace-block-add" onclick="wmAddBossBlock('table')"><strong>Table</strong><small>Data Grid</small></button>
              </div>
              <div id="wmBossBlocksList" class="workspace-block-list"></div>
            </div>
            <div>
              <div class="workspace-inline-section-title">Live Renderer Preview</div>
              <div id="wmBossDesignerPreview" class="workspace-page-preview-surface"></div>
            </div>
          </div>
        </div>
      </div>
    `;

    // Populate designer select
    const select = document.getElementById('wmBossDesignerPageSelect');
    const pages = wmState.treeData?.pages || [];
    if (select && pages.length) {
      select.replaceChildren(...pages.map(p => new Option(p.label || p.name, p.name)));
      wmLoadBossDesignerPage(pages[0].name);
    }
  }

  global.wmLoadBossDesignerPage = function (pageName) {
    const page = wmState.treeData?.pages?.find(p => p.name === pageName);
    if (!page) return;
    wmState.designerPage = JSON.parse(JSON.stringify(page));

    const titleInput = document.getElementById('wmBossDesignerTitle');
    if (titleInput) titleInput.value = page.label || page.name;

    const list = document.getElementById('wmBossBlocksList');
    if (list) {
      list.replaceChildren();
      (page.children || []).forEach(c => {
        wmAddBossBlockDOM(c.type, c.details || { title: c.label });
      });
    }
    wmRenderBossDesignerPreview();
  };

  global.wmAddBossBlock = function (type) {
    wmAddBossBlockDOM(type, { title: `New ${type}`, text: `Sample ${type} content` });
    wmRenderBossDesignerPreview();
  };

  function wmAddBossBlockDOM(type, details = {}) {
    const list = document.getElementById('wmBossBlocksList');
    if (!list) return;

    const row = document.createElement('div');
    row.className = 'workspace-block-row';
    const select = document.createElement('select');
    select.className = 'form-select block-type';
    ['heading', 'card', 'stat', 'table'].forEach(optionType => {
      const option = new Option(optionType[0].toUpperCase() + optionType.slice(1), optionType, false, optionType === type);
      select.appendChild(option);
    });
    const titleInput = document.createElement('input');
    titleInput.className = 'form-input block-title';
    titleInput.placeholder = 'Title / Label';
    titleInput.value = details.title || details.label || '';
    const bodyInput = document.createElement('input');
    bodyInput.className = 'form-input block-body';
    bodyInput.placeholder = 'Content / Value';
    bodyInput.value = details.text || details.value || '';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'icon-btn danger';
    remove.title = 'Remove block';
    remove.textContent = '⌫';
    remove.onclick = () => { row.remove(); wmRenderBossDesignerPreview(); };
    row.append(select, titleInput, bodyInput, remove);
    row.querySelectorAll('input, select').forEach(i => i.addEventListener('input', wmRenderBossDesignerPreview));
    list.appendChild(row);
  }

  function wmCollectBossBlocks() {
    return [...document.querySelectorAll('#wmBossBlocksList .workspace-block-row')].map(row => {
      const type = row.querySelector('.block-type').value;
      const title = row.querySelector('.block-title').value.trim();
      const body = row.querySelector('.block-body').value.trim();
      return { type, title, text: body, label: title, value: body };
    });
  }

  function wmRenderBossDesignerPreview() {
    const preview = document.getElementById('wmBossDesignerPreview');
    if (!preview) return;
    const blocks = wmCollectBossBlocks();
    preview.replaceChildren();

    if (!blocks.length) {
      preview.innerHTML = '<div class="wm-empty-state">No blocks added. Palette button to insert components.</div>';
      return;
    }

    blocks.forEach(b => {
      const compEl = document.createElement('div');
      compEl.className = `workspace-preview-block preview-${b.type}`;
      const heading = document.createElement('strong');
      heading.textContent = `[${b.type.toUpperCase()}] ${b.title || 'Untitled'}`;
      const body = document.createElement('p');
      body.textContent = b.text || '';
      compEl.append(heading, body);
      preview.appendChild(compEl);
    });
  }

  global.wmRenderBossDesignerPreview = wmRenderBossDesignerPreview;

  global.wmSaveBossDesignerPage = async function () {
    const select = document.getElementById('wmBossDesignerPageSelect');
    const titleInput = document.getElementById('wmBossDesignerTitle');
    if (!select) return;

    const pageName = select.value;
    const title = titleInput ? titleInput.value.trim() : pageName;
    const blocks = wmCollectBossBlocks();

    const payload = {
      name: pageName,
      title: title,
      entity_type: 'page',
      layout: blocks
    };

    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.create_page', { config: payload });
      } else {
        const response = await fetch('/v1/ui/registry/register', {
          method: 'POST',
          headers: authHeaders(true),
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Page publish was rejected by the server.');
      }
      await loadWorkspaceManager();
      if (typeof global.showToast === 'function') global.showToast(`Saved and published page '${title}'!`, 'success');
    } catch (e) {
      alert(`Save failed: ${e.message}`);
    }
  };

  // Boss Tab 4: Published Versions Table
  function renderBossVersionsTable(container) {
    container.replaceChildren();

    const versions = wmState.registryData?.versions || [];

    if (!versions.length) {
      const empty = document.createElement('div');
      empty.className = 'wm-empty-state';
      empty.textContent = 'No published UI configuration snapshots recorded yet.';
      container.appendChild(empty);
      return;
    }

    const table = document.createElement('table');
    table.className = 'wm-matrix-table';

    const headerRow = document.createElement('tr');
    ['VERSION', 'VERSION ID', 'PUBLISHED BY', 'PUBLISHED AT', 'ACTIONS'].forEach(label => {
      const th = document.createElement('th'); th.textContent = label; headerRow.appendChild(th);
    });
    const thead = document.createElement('thead'); thead.appendChild(headerRow); table.appendChild(thead);
    const tbody = document.createElement('tbody');
    versions.forEach(version => {
      const row = document.createElement('tr');
      const versionCell = document.createElement('td');
      const versionStrong = document.createElement('strong'); versionStrong.textContent = `v${version.version_num}`; versionCell.appendChild(versionStrong);
      const idCell = document.createElement('td');
      const idCode = document.createElement('code'); idCode.className = 'mono-muted'; idCode.textContent = version.version_id; idCell.appendChild(idCode);
      const publisherCell = document.createElement('td'); publisherCell.textContent = version.published_by || '';
      const dateCell = document.createElement('td');
      const date = document.createElement('small'); date.textContent = new Date(Number(version.published_at) * 1000).toLocaleString(); dateCell.appendChild(date);
      const actionCell = document.createElement('td');
      const restore = document.createElement('button'); restore.className = 'btn btn-xs btn-ghost'; restore.textContent = '↺ Restore Snapshot';
      restore.onclick = () => global.wmRestoreBossVersion(version.version_id);
      actionCell.appendChild(restore);
      row.append(versionCell, idCell, publisherCell, dateCell, actionCell); tbody.appendChild(row);
    });
    table.appendChild(tbody);

    container.appendChild(table);
  }

  global.wmRestoreBossVersion = async function (versionId) {
    if (!confirm(`Restore UI platform state to snapshot '${versionId}'?`)) return;
    try {
      if (global.thinkdome && typeof global.thinkdome.call === 'function') {
        await global.thinkdome.call('thinkdome.core.ui.api.restore_version', { version_id: versionId });
      } else {
        const response = await fetch(`/v1/ui/versions/${encodeURIComponent(versionId)}/restore`, { method: 'POST', headers: authHeaders() });
        if (!response.ok) throw new Error('Version restore was rejected by the server.');
      }
      await loadWorkspaceManager();
      if (typeof global.showToast === 'function') global.showToast(`Restored version '${versionId}'`, 'success');
    } catch (e) {
      alert(`Restore failed: ${e.message}`);
    }
  };

  // Expose public API
  // Keep a namespaced handle because app.js also has a shell/workspace-data
  // loader. Both must run; neither is allowed to overwrite the other.
  global.loadFrameworkWorkspaceManager = loadWorkspaceManager;
  global.loadWorkspaceManager = loadWorkspaceManager;
  global.switchWorkspaceCard = switchWorkspaceCard;
  global.setViewerMode = setViewerMode;
  global.setViewerRoleFilter = setViewerRoleFilter;
  global.setMapperTab = setMapperTab;
  global.setMapperRole = setMapperRole;
  global.setBossTab = setBossTab;

})(typeof window !== 'undefined' ? window : globalThis);
