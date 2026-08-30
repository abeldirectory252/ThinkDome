/**
 * thinkdome.js — ThinkDome Framework Frontend Client Engine (Frappe-style)
 * Provides `thinkdome.call()`, session handling, UI Builder, and Data-Driven Workspace Desk Rendering.
 */

(function (global) {
  'use strict';

  const thinkdome = global.thinkdome || {};

  // ── Session Context ────────────────────────────────────────────────────────
  thinkdome.session = {
    user: localStorage.getItem("thinkdome_username") || "Guest",
    role: localStorage.getItem("thinkdome_user_role") || "GUEST",
    token: localStorage.getItem("thinkdome_token") || "",
  };

  // ── Frappe-style thinkdome.call() RPC Engine ──────────────────────────────
  thinkdome.call = async function (method, kwargs = {}) {
    const token = localStorage.getItem("thinkdome_token") || thinkdome.session.token || "";
    const headers = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };

    // Route to /api/method/{method_path}
    const endpoint = `/api/method/${method.replace(/^\/+/, "")}`;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(kwargs),
      });

      const json = await response.json().catch(() => ({}));

      if (!response.ok) {
        const errorMsg = json.message || json.detail || `Server error (${response.status})`;
        const excType = json.exc_type || "RPCError";
        console.error(`[ThinkDome RPC Error] ${excType}: ${errorMsg}`, json);

        if (response.status === 401 && typeof global.invalidateClientSession === "function") {
          global.invalidateClientSession();
        }

        throw new Error(`[${excType}] ${errorMsg}`);
      }

      return json.message !== undefined ? json.message : json;
    } catch (err) {
      if (err.message.startsWith("[")) throw err;
      // Fallback network error
      console.error(`[ThinkDome Network Error] ${err.message}`);
      throw err;
    }
  };

  // Expose window.call as alias
  global.call = thinkdome.call;

  // ── ThinkDome Dynamic UI Framework ──────────────────────────────────────────
  thinkdome.ui = thinkdome.ui || {};

  thinkdome.ui.getNavigation = async function () {
    return await thinkdome.call("thinkdome.core.ui.api.get_navigation");
  };

  thinkdome.ui.loadUIBuilder = async function () {
    return await thinkdome.call("thinkdome.core.ui.api.get_ui_builder");
  };

  thinkdome.ui.saveDraft = async function (data) {
    return await thinkdome.call("thinkdome.core.ui.api.save_ui_draft", { data });
  };

  thinkdome.ui.previewDraft = async function (draftId) {
    return await thinkdome.call("thinkdome.core.ui.api.preview_ui", { draft_id: draftId });
  };

  thinkdome.ui.publishDraft = async function (draftId) {
    return await thinkdome.call("thinkdome.core.ui.api.publish_ui", { draft_id: draftId });
  };

  thinkdome.ui.listVersions = async function () {
    return await thinkdome.call("thinkdome.core.ui.api.list_versions");
  };

  thinkdome.ui.restoreVersion = async function (versionId) {
    return await thinkdome.call("thinkdome.core.ui.api.restore_version", { version_id: versionId });
  };

  // ── Data-Driven Page Rendering Engine ──────────────────────────────────────
  function textNode(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = value == null ? '' : String(value);
    return el;
  }

  thinkdome.ui.renderComponent = function (comp) {
    if (!comp || !comp.type) throw new Error('Component type is required');

    const type = comp.type;

    if (type === 'heading') {
      const level = Math.min(Math.max(parseInt(comp.level || 1), 1), 6);
      const tag = `h${level}`;
      const el = document.createElement(tag);
      el.className = `td-heading td-heading-l${level}`;
      el.textContent = comp.text || '';
      return el;
    }

    if (type === 'card') {
      const card = document.createElement('div');
      card.className = 'td-card shadow-sm border rounded-lg p-4 bg-white mb-4';
      const head = document.createElement('div');
      head.className = 'flex items-center justify-between';
      head.appendChild(textNode('span', 'text-sm font-medium text-gray-500', comp.title));
      if (comp.icon) head.appendChild(textNode('span', 'text-gray-400', comp.icon));
      card.append(head, textNode('div', 'text-2xl font-bold text-gray-900 mt-2', comp.value));
      return card;
    }

    if (type === 'stat') {
      const stat = document.createElement('div');
      stat.className = 'td-stat border-l-4 border-blue-500 pl-4 py-2 my-2';
      stat.append(
        textNode('div', 'text-xs uppercase tracking-wider text-gray-400', comp.label),
        textNode('div', 'text-xl font-bold text-gray-800', comp.value == null ? 0 : comp.value)
      );
      return stat;
    }

    if (type === 'row') {
      const row = document.createElement('div');
      row.className = 'td-row flex flex-wrap -mx-2 mb-4';
      (comp.columns || []).forEach(col => {
        const colEl = document.createElement('div');
        const width = col.width || 12;
        colEl.className = `td-col w-full md:w-${width}/12 px-2`;
        (col.components || []).forEach(childComp => {
          colEl.appendChild(thinkdome.ui.renderComponent(childComp));
        });
        row.appendChild(colEl);
      });
      return row;
    }

    if (type === 'grid') {
      const grid = document.createElement('div');
      const cols = comp.columns || 2;
      grid.className = 'td-grid';
      grid.style.setProperty('--td-columns', Math.max(1, Math.min(Number(cols) || 2, 6)));
      if (comp.gap != null) grid.style.gap = `${Math.max(0, Number(comp.gap) || 0)}px`;
      (comp.components || []).forEach(childComp => {
        grid.appendChild(thinkdome.ui.renderComponent(childComp));
      });
      return grid;
    }

    if (type === 'stack' || type === 'section' || type === 'column') {
      const wrapper = document.createElement('div');
      wrapper.className = `td-${type}`;
      if (type === 'stack' && comp.gap != null) wrapper.style.gap = `${Math.max(0, Number(comp.gap) || 0)}px`;
      if (type === 'section' && comp.title) wrapper.appendChild(textNode('h3', 'td-section-title', comp.title));
      if (type === 'column' && comp.width) wrapper.dataset.width = String(comp.width);
      (comp.components || []).forEach(child => wrapper.appendChild(thinkdome.ui.renderComponent(child)));
      return wrapper;
    }

    if (type === 'tabs') {
      const tabs = document.createElement('div');
      tabs.className = 'td-tabs';
      (comp.items || []).forEach(item => {
        const panel = document.createElement('section');
        panel.className = 'td-tab-panel';
        if (item.label) panel.appendChild(textNode('h3', 'td-tab-label', item.label));
        (item.components || []).forEach(child => panel.appendChild(thinkdome.ui.renderComponent(child)));
        tabs.appendChild(panel);
      });
      return tabs;
    }

    if (type === 'link') {
      const link = document.createElement('a');
      link.className = 'td-link';
      link.href = `#${String(comp.route || '').replace(/^#/, '')}`;
      link.textContent = comp.label || comp.route || '';
      return link;
    }

    // Default container fallback
    throw new Error(`Unsupported component type '${type}'`);
  };

  // Render the page contract returned by UIManager. Pages are not HTML
  // templates: the server supplies a component layout and this registry is
  // the only client-side translation layer.
  thinkdome.ui.renderPage = function (container, page) {
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container) return;
    container.replaceChildren();

    const layout = Array.isArray(page && page.layout) ? page.layout : [];
    if (!layout.length) {
      const empty = document.createElement('p');
      empty.className = 'td-empty-state';
      empty.textContent = 'This page has no configured content.';
      container.appendChild(empty);
      return;
    }

    layout.forEach(component => {
      try {
        container.appendChild(thinkdome.ui.renderComponent(component));
      } catch (error) {
        // A malformed component must not prevent the rest of the manifest
        // from rendering. Configuration validation remains server-owned.
        const failed = document.createElement('p');
        failed.className = 'td-component-error';
        failed.textContent = `Unable to render component: ${error.message}`;
        container.appendChild(failed);
      }
    });
  };

  // ── Workspace Desk Rendering Engine (theme-native) ────────────────────────

  // Helper: icon marks using the existing access-hub-mark pattern
  const ICON_MAP = {
    sandboxes: '⬡', console: '▸', terminal: '▸', billing: '$',
    apikeys: '⚿', audit: '≡', users: '♙', roles: '◈',
    settings: '⚙', dashboard: '▦', default: '✦'
  };

  function iconFor(name) {
    return ICON_MAP[name] || ICON_MAP[(name || '').toLowerCase()] || ICON_MAP.default;
  }

  thinkdome.ui.renderShortcuts = function (shortcuts, isStudio) {
    const grid = document.createElement('div');
    grid.className = 'desk-shortcuts';

    (shortcuts || []).forEach(function (sc, idx) {
      const pill = document.createElement('button');
      pill.className = 'desk-shortcut' + (isStudio ? ' studio-outline' : '');
      pill.innerHTML =
        '<span class="desk-shortcut-mark">' + iconFor(sc.route || sc.name) + '</span>' +
        '<span>' + (sc.label || sc.name) + '</span>' +
        (sc.count !== undefined ? '<span class="desk-shortcut-badge">' + sc.count + '</span>' : '');

      if (isStudio) {
        var ctrl = document.createElement('span');
        ctrl.className = 'studio-item-controls';
        ctrl.innerHTML = '<button class="btn btn-danger btn-xs" onclick="event.stopPropagation();removeWorkspaceShortcut(' + idx + ')">✕</button>';
        pill.appendChild(ctrl);
      } else {
        pill.onclick = function () {
          if (sc.route && typeof global.navTo === 'function') global.navTo(sc.route);
        };
      }
      grid.appendChild(pill);
    });

    return grid;
  };

  thinkdome.ui.renderNumberCards = function (cards, isStudio) {
    var grid = document.createElement('div');
    grid.className = 'desk-stats';

    (cards || []).forEach(function (card, idx) {
      var el = document.createElement('div');
      el.className = 'desk-stat' + (isStudio ? ' studio-outline' : '');

      var trendClass = '';
      if (card.trend) {
        trendClass = card.trend.startsWith('-') ? ' negative' : ' positive';
      }

      el.innerHTML =
        '<div class="stat-top"><span>' + (card.label || 'Metric') + '</span></div>' +
        '<div class="stat-value">' + (card.value || '0') + '</div>' +
        (card.trend ? '<div class="stat-sub' + trendClass + '">' + card.trend + '</div>' : '');

      if (isStudio) {
        var ctrl = document.createElement('span');
        ctrl.className = 'studio-item-controls';
        ctrl.innerHTML = '<button class="btn btn-danger btn-xs" onclick="event.stopPropagation();removeWorkspaceNumberCard(' + idx + ')">✕</button>';
        el.appendChild(ctrl);
      }
      grid.appendChild(el);
    });

    return grid;
  };

  thinkdome.ui.renderCardGroups = function (groups, isStudio) {
    var grid = document.createElement('div');
    grid.className = 'desk-groups';

    (groups || []).forEach(function (group, gIdx) {
      var card = document.createElement('div');
      card.className = 'desk-group' + (isStudio ? ' studio-outline' : '');

      // Head
      var head = document.createElement('div');
      head.className = 'desk-group-head';
      head.innerHTML = '<strong>' + (group.title || group.name) + '</strong>';
      if (isStudio) {
        head.innerHTML += '<button class="btn btn-ghost btn-xs" onclick="addCardGroupItem(' + gIdx + ')">+ Add Link</button>';
      }
      card.appendChild(head);

      // Items
      (group.items || []).forEach(function (item, iIdx) {
        var row = document.createElement('div');
        row.className = 'desk-group-item';
        row.innerHTML =
          '<div class="desk-group-item-info">' +
            '<span class="desk-group-item-mark">' + iconFor(item.route || item.name) + '</span>' +
            '<div class="desk-group-item-copy">' +
              '<strong>' + (item.label || item.name) + '</strong>' +
              (item.description ? '<small>' + item.description + '</small>' : '') +
            '</div>' +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:6px;">' +
            (item.badge ? '<span class="desk-version-tag">' + item.badge + '</span>' : '') +
            (isStudio
              ? '<button class="btn btn-danger btn-xs" onclick="event.stopPropagation();removeCardGroupItem(' + gIdx + ',' + iIdx + ')">✕</button>'
              : '<span class="desk-group-item-arrow">↗</span>') +
          '</div>';

        if (!isStudio) {
          row.onclick = function () {
            if (item.route && typeof global.navTo === 'function') global.navTo(item.route);
          };
        }
        card.appendChild(row);
      });

      grid.appendChild(card);
    });

    return grid;
  };

  thinkdome.ui.renderWorkspaceDesk = function (container, workspace, isStudio) {
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container) return;

    container.innerHTML = '';

    var shell = document.createElement('div');
    shell.className = 'desk-shell';

    // 1. Hero — same pattern as access-hero
    var hero = document.createElement('div');
    hero.className = 'access-hero';
    hero.innerHTML =
      '<div class="access-hero-copy">' +
        '<span class="access-eyebrow">WORKSPACE</span>' +
        '<h2>' + (workspace.label || workspace.name || 'Workspace') +
          ' <span class="desk-version-tag">v' + (workspace.version || '1.0') + '</span></h2>' +
        '<p>' + (workspace.description || 'Configurable role-aware workspace desk.') + '</p>' +
      '</div>' +
      '<span class="access-hero-orbit" aria-hidden="true">' + (workspace.icon || '▦') + '</span>';

    // Edit button — placed below hero when not in studio mode
    if (!isStudio) {
      var editRow = document.createElement('div');
      editRow.style.cssText = 'display:flex;gap:10px;justify-content:flex-end;margin-top:-12px;';
      editRow.innerHTML = '<button class="btn btn-primary btn-sm" onclick="toggleWorkspaceStudioMode(true)">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:5px;">' +
          '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>' +
        '</svg>Edit Workspace</button>';
      shell.appendChild(hero);
      shell.appendChild(editRow);
    } else {
      shell.appendChild(hero);
    }

    // 2. Shortcuts section
    if ((workspace.shortcuts || []).length > 0 || isStudio) {
      var scSection = document.createElement('div');
      var scHead = document.createElement('div');
      scHead.className = 'desk-section-label';
      scHead.innerHTML = '<span>Shortcuts</span><small>Quick access</small>';
      if (isStudio) {
        scHead.innerHTML += '<button class="btn btn-ghost btn-xs" style="margin-left:auto" onclick="openAddShortcutModal()">+ Add</button>';
      }
      scSection.appendChild(scHead);
      scSection.appendChild(thinkdome.ui.renderShortcuts(workspace.shortcuts, isStudio));
      shell.appendChild(scSection);
    }

    // 3. Number Cards (KPI metrics)
    if ((workspace.number_cards || []).length > 0 || isStudio) {
      var ncSection = document.createElement('div');
      var ncHead = document.createElement('div');
      ncHead.className = 'desk-section-label';
      ncHead.innerHTML = '<span>Key Metrics</span><small>Real-time indicators</small>';
      if (isStudio) {
        ncHead.innerHTML += '<button class="btn btn-ghost btn-xs" style="margin-left:auto" onclick="openAddNumberCardModal()">+ Add</button>';
      }
      ncSection.appendChild(ncHead);
      ncSection.appendChild(thinkdome.ui.renderNumberCards(workspace.number_cards, isStudio));
      shell.appendChild(ncSection);
    }

    // 4. Card link groups
    if ((workspace.card_groups || []).length > 0 || isStudio) {
      var cgSection = document.createElement('div');
      var cgHead = document.createElement('div');
      cgHead.className = 'desk-section-label';
      cgHead.innerHTML = '<span>Modules</span><small>Workspace resources</small>';
      if (isStudio) {
        cgHead.innerHTML += '<button class="btn btn-ghost btn-xs" style="margin-left:auto" onclick="openAddCardGroupModal()">+ Add</button>';
      }
      cgSection.appendChild(cgHead);
      cgSection.appendChild(thinkdome.ui.renderCardGroups(workspace.card_groups, isStudio));
      shell.appendChild(cgSection);
    }

    container.appendChild(shell);
  };

  global.thinkdome = thinkdome;
})(typeof window !== 'undefined' ? window : globalThis);
