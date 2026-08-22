export type ApiError = { code: string; message: string };
export type HealthResponse = { status: string; component?: string };
export type User = { username: string; role?: string; organization_id?: string; status?: string };
export type PlacementResponse = {
  sandbox_id: string;
  node_id: string;
  organization_id: string;
  project_id: string;
  placement_version: number;
};
export type Node = { node_id: string; region: string; state: string };

export class ThinkDomeApiError extends Error {
  constructor(public readonly status: number, public readonly error: ApiError) {
    super(error.message);
  }
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Request-ID", requestId());
  const token = sessionStorage.getItem("thinkdome_session_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = body?.code && body?.message ? body : { code: "GENERAL::UNKNOWN_ERROR", message: `Request failed (${response.status})` };
    throw new ThinkDomeApiError(response.status, error);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  nodes: () => request<{ nodes: Node[] }>("/v1/control-plane/nodes"),
  me: async () => (await request<{ user: User }>("/v1/auth/me")).user,
  login: async (username: string, password: string) => {
    const result = await request<{ session_token: string; user: User }>("/v1/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }),
    });
    sessionStorage.setItem("thinkdome_session_token", result.session_token);
    return result.user;
  },
  logout: async () => {
    const result = await request<{ status: string }>("/v1/auth/logout", { method: "POST" });
    sessionStorage.removeItem("thinkdome_session_token");
    return result;
  },
  createPlacement: (organizationId: string, payload: { project_id: string; sandbox_id: string }, idempotencyKey: string) =>
    request<PlacementResponse>("/v1/control-plane/placements", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Organization-ID": organizationId, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    }),
};
