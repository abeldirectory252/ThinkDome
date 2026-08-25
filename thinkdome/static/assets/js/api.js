/**
 * api.js — ThinkDome API Client
 * Centralized module for all API interactions with the ThinkDome backend.
 * All functions return { data, error } objects for consistent error handling.
 */

const API_BASE = "";
let refreshRequest = null;

function showServerErrorPopup() {
    const id = "thinkdome-server-error-popup";
    let popup = document.getElementById(id);
    if (!popup) {
        popup = document.createElement("div");
        popup.id = id;
        popup.setAttribute("role", "alertdialog");
        popup.setAttribute("aria-modal", "true");
        popup.setAttribute("aria-labelledby", `${id}-title`);
        popup.setAttribute("aria-describedby", `${id}-message`);
        popup.className = "modal-overlay active";
        popup.innerHTML = `<div class="modal-card" style="max-width:420px">
          <div class="modal-header"><h3 id="${id}-title">Server error</h3><button type="button" class="close-modal-btn" data-close-server-error aria-label="Close message">×</button></div>
          <div class="modal-body"><p id="${id}-message" class="modal-text">The server could not complete your request. Please contact the administrator.</p></div>
          <div class="modal-footer"><button type="button" class="btn btn-ghost" data-close-server-error>Close</button></div>
        </div>`;
        popup.addEventListener("click", (event) => {
            const target = event.target;
            if (target === popup || (target instanceof Element && target.closest("[data-close-server-error]"))) {
                popup.remove();
            }
        });
        document.body.appendChild(popup);
        popup.querySelector("[data-close-server-error]")?.focus();
    }
}

export function showValidationErrorPopup(message = "Please review the highlighted fields and try again.") {
    const id = "thinkdome-validation-error-popup";
    let popup = document.getElementById(id);
    if (popup) return;

    popup = document.createElement("div");
    popup.id = id;
    popup.setAttribute("role", "alertdialog");
    popup.setAttribute("aria-modal", "true");
    popup.setAttribute("aria-labelledby", `${id}-title`);
    popup.setAttribute("aria-describedby", `${id}-message`);

    const panel = document.createElement("div");
    panel.className = "modal-overlay active";
    const content = document.createElement("div");
    content.className = "modal-card";
    content.style.maxWidth = "420px";
    const header = document.createElement("div");
    header.className = "modal-header";
    const title = document.createElement("h3");
    title.id = `${id}-title`;
    title.textContent = "Please check your information";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "close-modal-btn";
    dismiss.textContent = "×";
    dismiss.setAttribute("aria-label", "Close message");
    dismiss.dataset.closeValidationError = "true";
    header.append(title, dismiss);
    const main = document.createElement("div");
    main.className = "modal-body";
    const body = document.createElement("p");
    body.id = `${id}-message`;
    body.textContent = message;
    body.className = "modal-text";
    main.appendChild(body);
    const footer = document.createElement("div");
    footer.className = "modal-footer";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-ghost";
    close.textContent = "Close";
    close.dataset.closeValidationError = "true";
    footer.appendChild(close);
    content.append(header, main, footer);
    panel.appendChild(content);
    popup.appendChild(panel);
    popup.addEventListener("click", (event) => {
        const target = event.target;
        if (target === popup || (target instanceof Element && target.closest("[data-close-validation-error]"))) popup.remove();
    });
    document.body.appendChild(popup);
    close.focus();
}

function validationMessage(data) {
    const fields = new Set((Array.isArray(data?.detail) ? data.detail : [])
        .map((error) => Array.isArray(error?.loc) ? error.loc.at(-1) : null));
    if (fields.has("username") && fields.has("password")) {
        return "Use a username with at least 3 characters and a password with at least 6 characters.";
    }
    if (fields.has("username")) return "Use a username with at least 3 characters.";
    if (fields.has("password")) return "Use a password with at least 6 characters.";
    return "Please review the highlighted fields and try again.";
}

async function refreshAccessToken() {
    // Keep the refresh token in its HTTP-only cookie; this avoids persisting
    // long-lived credentials in localStorage. Share a pending refresh so a
    // dashboard render does not rotate the one-time token more than once.
    if (!refreshRequest) {
        refreshRequest = fetch(API_BASE + "/v1/auth/refresh", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
        })
            .then(async (response) => {
                if (!response.ok) return null;
                const data = await response.json();
                if (!data?.access_token) return null;
                localStorage.setItem("thinkdome_token", data.access_token);
                return data.access_token;
            })
            .catch(() => null)
            .finally(() => {
                refreshRequest = null;
            });
    }
    return refreshRequest;
}

// ─────────────────────────────────────────────
// Internal Helpers
// ─────────────────────────────────────────────

/**
 * Core fetch wrapper. Attaches auth headers, handles 401 auto-logout,
 * and normalizes errors into a consistent { data, error } shape.
 *
 * @param {string} endpoint - URL path (e.g. "/v1/admin/keys")
 * @param {object} options  - fetch options (method, body, extra headers)
 * @param {string} token    - Bearer token for Authorization header
 * @param {string} [sandboxId] - Optional X-Sandbox-Id header value
 * @returns {Promise<{ data: any, error: string|null }>}
 */
async function apiFetch(endpoint, options = {}, token = "", sandboxId = "", retryAfterRefresh = true) {
    const headers = {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(sandboxId ? { "X-Sandbox-Id": sandboxId } : {}),
        ...(options.headers || {}),
    };

    try {
        const response = await fetch(API_BASE + endpoint, {
            credentials: "same-origin",
            ...options,
            headers,
        });

        // Access JWTs are deliberately short-lived. Refresh from the HTTP-only
        // cookie and retry the original request once before reporting logout.
        if (response.status === 401) {
            // Login/registration requests do not have a refreshable session.
            // Avoid a guaranteed second 401 request and provide a useful,
            // non-sensitive message to the user instead of exposing a raw
            // protocol sentinel such as "UNAUTHORIZED".
            const isAuthenticationEndpoint = endpoint.startsWith("/v1/auth/");
            if (retryAfterRefresh && token && !isAuthenticationEndpoint) {
                const refreshedToken = await refreshAccessToken();
                if (refreshedToken) {
                    return apiFetch(endpoint, options, refreshedToken, sandboxId, false);
                }
            }
            const error = isAuthenticationEndpoint && endpoint.endsWith("/login")
                ? "The username or password is incorrect. Please check your credentials and try again."
                : "Your session has expired or you are not authorized for this action. Please sign in again.";
            showValidationErrorPopup(error);
            return { data: null, error };
        }

        let data = {};
        try { data = await response.json(); } catch (_) { data = {}; }

        if (!response.ok) {
            if (response.status >= 500) {
                showServerErrorPopup();
                return { data: null, error: "SERVER_ERROR" };
            }
            if (response.status === 422) {
                const message = validationMessage(data);
                showValidationErrorPopup(message);
                return { data: null, error: message };
            }
            let errorMsg = "Request failed.";
            if (typeof data.detail === "string") {
                errorMsg = data.detail;
            } else if (Array.isArray(data.detail)) {
                errorMsg = data.detail
                    .map((err) => {
                        if (typeof err === "string") return err;
                        const field = (err.loc || []).filter((l) => l !== "body").join(" → ");
                        return field ? `${field}: ${err.msg}` : err.msg;
                    })
                    .join("; ");
            } else if (data.error?.message) {
                errorMsg = data.error.message;
            }
            return { data: null, error: errorMsg };
        }

        return { data, error: null };
    } catch (err) {
        showServerErrorPopup();
        return { data: null, error: err.message || "Network error" };
    }
}

// ─────────────────────────────────────────────
// Auth API
// ─────────────────────────────────────────────

/**
 * Log in with username + password.
 * @returns {Promise<{ data: { access_token, username }, error }>}
 */
export async function login(username, password) {
    return apiFetch("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
    });
}

/**
 * Register a new user account with an assigned enterprise role.
 * @returns {Promise<{ data: any, error }>}
 */
export async function register(username, password, role = "AGENT_STANDARD") {
    return apiFetch("/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password, role }),
    });
}

/**
 * Fetch dynamic roles catalog.
 */
export async function getRoles(token) {
    return apiFetch("/v1/roles", { method: "GET" }, token);
}

/**
 * Dynamically create a new role.
 */
export async function createRole(roleData, token) {
    return apiFetch("/v1/roles", {
        method: "POST",
        body: JSON.stringify(roleData),
    }, token);
}

/**
 * Assign role to user.
 */
export async function assignUserRole(userId, roleId, token) {
    return apiFetch(`/v1/users/${userId}/roles`, {
        method: "POST",
        body: JSON.stringify({ role_id: roleId }),
    }, token);
}

/**
 * Log out the current session.
 * @returns {Promise<{ data: any, error }>}
 */
export async function logout(token) {
    return apiFetch("/v1/auth/logout", { method: "POST" }, token);
}

export async function getCurrentUser(token = localStorage.getItem("thinkdome_token") || "") {
    return apiFetch("/v1/auth/me", { method: "GET" }, token);
}

// ─────────────────────────────────────────────
// Orchestrator / Tool Execution API
// ─────────────────────────────────────────────

/**
 * Send a ToolUse payload to the orchestrator endpoint.
 * @param {object} toolPayload - Valid ToolUse JSON object
 * @param {string} token
 * @param {string} [sandboxId]
 * @returns {Promise<{ data: { content, is_error }, error }>}
 */
export async function orchestrate(toolPayload, token, sandboxId = "") {
    return apiFetch(
        "/v1/orchestrate",
        { method: "POST", body: JSON.stringify(toolPayload) },
        token,
        sandboxId
    );
}

/**
 * List files/directories inside the sandbox at a given path.
 * @param {string} path       - Directory path (e.g. ".")
 * @param {string} token
 * @param {string} [sandboxId]
 * @returns {Promise<{ data: Array<{ name, path, type, size_bytes }>, error }>}
 */
export async function listDir(path, token, sandboxId = "") {
    const { data, error } = await orchestrate(
        {
            type: "tool_use",
            id: "toolu_list_dir",
            name: "list_dir",
            input: { path },
        },
        token,
        sandboxId
    );

    if (error) return { data: null, error };
    if (data?.error) return { data: null, error: data.error.message };
    if (data?.is_error) return { data: null, error: data.content };

    try {
        // Tool responses may be returned directly or wrapped by the
        // orchestrator adapter. Normalize both forms before the terminal
        // renders the result.
        let payload = data.content;
        if (typeof payload === "object" && payload !== null) payload = payload.content ?? payload.data ?? payload;
        let parsed = typeof payload === "string" ? JSON.parse(payload) : payload;
        if (typeof parsed === "string") parsed = JSON.parse(parsed);
        if (!Array.isArray(parsed)) throw new Error("Directory listing was not an array");
        return { data: parsed, error: null };
    } catch (err) {
        return { data: null, error: `Failed to parse directory listing: ${err.message}` };
    }
}

/**
 * Read a file's contents from the sandbox.
 * @param {string} filePath
 * @param {string} token
 * @param {string} [sandboxId]
 * @returns {Promise<{ data: string, error }>}
 */
export async function readFile(filePath, token, sandboxId = "") {
    const { data, error } = await orchestrate(
        {
            type: "tool_use",
            id: "toolu_read_file",
            name: "read_file",
            input: { path: filePath },
        },
        token,
        sandboxId
    );

    if (error) return { data: null, error };
    if (data?.error) return { data: null, error: data.error.message };
    if (data?.is_error) return { data: null, error: data.content };

    return { data: data.content, error: null };
}

/**
 * Write content to a file inside the sandbox.
 * @param {string} filePath
 * @param {string} content
 * @param {string} token
 * @param {string} [sandboxId]
 * @returns {Promise<{ data: any, error }>}
 */
export async function writeFile(filePath, content, token, sandboxId = "") {
    const { data, error } = await orchestrate(
        {
            type: "tool_use",
            id: "toolu_write_file",
            name: "write_file",
            input: { path: filePath, content },
        },
        token,
        sandboxId
    );

    if (error) return { data: null, error };
    if (data?.error) return { data: null, error: data.error.message };
    if (data?.is_error) return { data: null, error: data.content };

    return { data, error: null };
}

export async function getFileBoxVolume(token) {
    return apiFetch("/v1/filebox/volume", { method: "GET" }, token);
}

export async function listFileBoxes(token) {
    return apiFetch("/v1/filebox", { method: "GET" }, token);
}

export async function putFileBox(filename, content, token, permanent = true) {
    const encoded = btoa(unescape(encodeURIComponent(content)));
    return apiFetch("/v1/filebox", {
        method: "POST",
        body: JSON.stringify({ filename, content_base64: encoded, folder: "workspace", permanent, conflict: "override" })
    }, token);
}

// ─────────────────────────────────────────────
// API Key Management
// ─────────────────────────────────────────────

/**
 * Fetch all API keys for the authenticated user.
 * @returns {Promise<{ data: Array<{ key_id, display_name, masked_token, token_type, status }>, error }>}
 */
export async function getApiKeys(token) {
    return apiFetch("/v1/admin/keys", { method: "GET" }, token);
}

/**
 * Create a new API key.
 * @param {{ display_name: string, token_type: string, expires_at: string|null }} keyData
 * @returns {Promise<{ data: { token, key_id, ... }, error }>}
 */
export async function createApiKey(keyData, token) {
    return apiFetch(
        "/v1/admin/keys",
        { method: "POST", body: JSON.stringify(keyData) },
        token
    );
}

/**
 * Revoke an existing API key by ID.
 * @param {string} keyId
 * @returns {Promise<{ data: any, error }>}
 */
export async function revokeApiKey(keyId, token) {
    return apiFetch(
        `/v1/admin/keys/${keyId}/revoke`,
        { method: "POST" },
        token
    );
}

// ─────────────────────────────────────────────
// Request Logs
// ─────────────────────────────────────────────

/**
 * Fetch recent request/execution logs.
 * @param {number} [limit=50]
 * @returns {Promise<{ data: Array<log>, error }>}
 */
export async function getRequestLogs(token, limit = 50) {
    return apiFetch(`/v1/admin/logs?limit=${limit}`, { method: "GET" }, token);
}

/**
 * Clear all stored request logs.
 * @returns {Promise<{ data: any, error }>}
 */
export async function clearRequestLogs(token) {
    return apiFetch("/v1/admin/logs/clear", { method: "POST" }, token);
}

// ─────────────────────────────────────────────
// Audit Trail
// ─────────────────────────────────────────────

/**
 * Fetch audit trail events.
 * @param {number} [limit=100]
 * @returns {Promise<{ data: Array<audit>, error }>}
 */
export async function getAuditLogs(token, limit = 100) {
    return apiFetch(`/v1/admin/audits?limit=${limit}`, { method: "GET" }, token);
}

/**
 * Fetch a single audit log entry with full details and related execution data.
 * @param {string} token
 * @param {number} auditId
 * @returns {Promise<{ data: object, error }>}
 */
export async function getAuditDetail(token, auditId) {
    return apiFetch(`/v1/admin/audits/${auditId}`, { method: "GET" }, token);
}

// ─────────────────────────────────────────────
// Sandbox Management
// ─────────────────────────────────────────────

/**
 * Fetch all sandboxes.
 * @returns {Promise<{ data: Array<sandbox>, error }>}
 */
export async function getSandboxes(token) {
    return apiFetch("/v1/admin/sandboxes", { method: "GET" }, token);
}

/**
 * Create (deploy) a new sandbox environment.
 * @param {{ name: string, memory_mb: number, cpu_cores: number, timeout_sec: number, network_enabled: boolean }} config
 * @returns {Promise<{ data: sandbox, error }>}
 */
export async function createSandbox(config, token) {
    return apiFetch(
        "/v1/admin/sandboxes",
        { method: "POST", body: JSON.stringify(config) },
        token
    );
}

/**
 * Toggle a sandbox's active/stopped state.
 * @param {string} sandboxId
 * @returns {Promise<{ data: any, error }>}
 */
export async function toggleSandbox(sandboxId, token) {
    return apiFetch(
        `/v1/admin/sandboxes/${sandboxId}/toggle`,
        { method: "POST" },
        token
    );
}

/**
 * Permanently terminate and delete a sandbox.
 * @param {string} sandboxId
 * @returns {Promise<{ data: any, error }>}
 */
export async function terminateSandbox(sandboxId, token) {
    return apiFetch(
        `/v1/admin/sandboxes/${sandboxId}`,
        { method: "DELETE" },
        token
    );
}

// ─────────────────────────────────────────────
// Schema
// ─────────────────────────────────────────────

/**
 * Fetch the orchestrator JSON schema definition.
 * @returns {Promise<{ data: string, error }>} Raw JSON text of the schema
 */
export async function getOrchestratorSchema() {
    try {
        const response = await fetch("/orchestrator_schema.json");
        if (!response.ok) return { data: null, error: "Schema file not found." };
        const text = await response.text();
        return { data: text, error: null };
    } catch (err) {
        return { data: null, error: err.message };
    }
}

// ─────────────────────────────────────────────
// Billing API
// ─────────────────────────────────────────────

/**
 * Fetch billing cycles and sandbox cost usage reports.
 */
export async function getBillingData(cycleKey) {
    const token = localStorage.getItem('thinkdome_token');
    return apiFetch(`/v1/admin/billing?cycle=${encodeURIComponent(cycleKey)}`, { method: "GET" }, token);
}

/**
 * Request an invoice PDF compilation for a given billing cycle.
 * @param {string} cycleKey - Billing cycle identifier (e.g. 'this', 'last', 'ytd')
 * @param {string} token
 * @returns {Promise<{ data: { invoice_id, download_url }, error }>}
 */
export async function downloadInvoice(cycleKey, token) {
    return apiFetch(`/v1/admin/billing/invoice?cycle=${encodeURIComponent(cycleKey)}`, { method: "POST" }, token);
}

/**
 * Fetch all registered tools and their metadata.
 * @param {string} token
 * @returns {Promise<{ data: Array, error }>}
 */
export async function getTools(token) {
    return apiFetch("/v1/tools", { method: "GET" }, token);
}
