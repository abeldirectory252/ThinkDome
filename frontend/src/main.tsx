import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ShieldCheck, Server, Activity, LogOut } from "lucide-react";
import "./styles.css";
import { api, ThinkDomeApiError, type HealthResponse, type User } from "./api/client";

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [nodeCount, setNodeCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [placement, setPlacement] = useState<{ sandbox_id: string; node_id: string } | null>(null);
  const [sandboxForm, setSandboxForm] = useState({ project_id: "", sandbox_id: "" });
  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
    api.health().then(setHealth).catch((e: unknown) => {
      setError(e instanceof ThinkDomeApiError ? `${e.error.code}: ${e.error.message}` : "Control plane is unavailable");
    });
  }, []);
  useEffect(() => {
    if (user) api.nodes().then((result) => setNodeCount(result.nodes.length)).catch(() => setNodeCount(null));
  }, [user]);
  if (!user) return <div className="login"><div className="login-card"><div className="logo"><ShieldCheck /> Think<span>Dome</span></div><p className="eyebrow">SECURE OPERATOR CONSOLE</p><h1>Sign in</h1><form onSubmit={(event) => { event.preventDefault(); setAuthError(""); api.login(credentials.username, credentials.password).then(setUser).catch((e: unknown) => setAuthError(e instanceof ThinkDomeApiError ? e.error.message : "Sign in failed")); }}><input aria-label="Username" placeholder="Username" value={credentials.username} onChange={(e) => setCredentials({ ...credentials, username: e.target.value })} /><input aria-label="Password" type="password" placeholder="Password" value={credentials.password} onChange={(e) => setCredentials({ ...credentials, password: e.target.value })} /><button type="submit">Sign in</button></form>{authError && <div className="alert">{authError}</div>}</div></div>;
  return <div className="shell">
    <aside><div className="logo"><ShieldCheck /> Think<span>Dome</span></div><nav><a className="active"><Activity /> Overview</a><a><Server /> Sandboxes</a></nav><div className="tenant">Tenant<br /><strong>Production workspace</strong></div></aside>
    <main><header><div><p className="eyebrow">CONTROL PLANE</p><h1>Execution overview</h1><small className="identity">{user.username} · {user.role}</small></div><button className="ghost" onClick={() => api.logout().finally(() => setUser(null))}><LogOut size={16} /> Sign out</button></header>
      {error && <div className="alert">{error}</div>}
      <section className="grid"><article><span>Control plane</span><strong className={health?.status === "ok" ? "good" : "warn"}>{health?.status === "ok" ? "Operational" : "Checking…"}</strong><small>{health?.component ?? "API health endpoint"}</small></article><article><span>Isolation policy</span><strong className="good">Enforced</strong><small>MicroVM / Docker policy chain</small></article><article><span>Ready nodes</span><strong className={nodeCount === null ? "warn" : "good"}>{nodeCount === null ? "Unavailable" : nodeCount}</strong><small>Live leases reconciled continuously</small></article></section>
      <section className="panel"><div><p className="eyebrow">QUICK START</p><h2>Create a secure sandbox</h2><p>Reserve an isolated environment on a healthy execution node.</p><form className="placement-form" onSubmit={(event) => { event.preventDefault(); setError(""); setPlacement(null); if (!user.organization_id) { setError("TENANT::CONTEXT_REQUIRED: your account has no organization context"); return; } api.createPlacement(user.organization_id, sandboxForm, crypto.randomUUID()).then(setPlacement).catch((e: unknown) => setError(e instanceof ThinkDomeApiError ? `${e.error.code}: ${e.error.message}` : "Placement failed")); }}><input required aria-label="Project ID" placeholder="Project ID" value={sandboxForm.project_id} onChange={(e) => setSandboxForm({ ...sandboxForm, project_id: e.target.value })} /><input required aria-label="Sandbox ID" placeholder="Sandbox ID" value={sandboxForm.sandbox_id} onChange={(e) => setSandboxForm({ ...sandboxForm, sandbox_id: e.target.value })} /><button type="submit">Place sandbox</button></form>{placement && <div className="success">{placement.sandbox_id} reserved on {placement.node_id}</div>}</div></section>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
