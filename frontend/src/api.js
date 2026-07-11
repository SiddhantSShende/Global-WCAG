// Thin API client. Adds X-API-Key (for RBAC-enabled deployments) and returns a
// uniform { ok, status, data } shape.
const KEY = "gw-apikey";

export const getApiKey = () => localStorage.getItem(KEY) || "";
export function setApiKey() {
  const v = window.prompt("API key (leave blank if auth is disabled):", getApiKey());
  if (v === null) return;
  if (v.trim()) localStorage.setItem(KEY, v.trim());
  else localStorage.removeItem(KEY);
}

export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !headers["content-type"]) headers["content-type"] = "application/json";
  const k = getApiKey();
  if (k) headers["X-API-Key"] = k;
  let res, data = null;
  try {
    res = await fetch(path, { ...opts, headers });
    try { data = await res.json(); } catch { /* non-json */ }
    return { ok: res.ok, status: res.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: { detail: String(e) } };
  }
}

export const prettyStatus = (s) =>
  String(s || "").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
