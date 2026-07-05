/**
 * api.js — ThinkDome API Client
 * Centralized module for all API interactions with the ThinkDome backend.
 * All functions return { data, error } objects for consistent error handling.
 */

const API_BASE = "";

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
async function apiFetch(endpoint, options = {}, token = "", sandboxId = "") {
    const headers = {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(sandboxId ? { "X-Sandbox-Id": sandboxId } : {}),
        ...(options.headers || {}),
    };

    try {
        const response = await fetch(API_BASE + endpoint, {
            ...options,
            headers,
        });

        // Auto-logout on 401
        if (response.status === 401) {
            return { data: null, error: "UNAUTHORIZED" };
        }

        const data = await response.json();

        if (!response.ok) {
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
 * Register a new user account.
 * @returns {Promise<{ data: any, error }>}
 */
export async function register(username, password) {
    return apiFetch("/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
    });
}

/**
 * Log out the current session.
 * @returns {Promise<{ data: any, error }>}
 */
export async function logout(token) {
    return apiFetch("/v1/auth/logout", { method: "POST" }, token);
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
        return { data: JSON.parse(data.content), error: null };
    } catch {
        return { data: null, error: "Failed to parse directory listing." };
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