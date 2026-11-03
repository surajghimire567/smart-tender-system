import { clearSession, getDeviceId, getToken } from "./deps.jsx";

const API_BASE = "http://localhost:8000";

export async function adminRequest(path, options = {}) {
  const { backgroundRefresh = false, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers || {});
  const token = getToken();
  const deviceId = getDeviceId();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Device-Id", deviceId || "unknown");
  if (backgroundRefresh) headers.set("X-Background-Refresh", "true");
  if (fetchOptions.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);

  if (response.status === 401) {
    clearSession();
    window.location.assign("/login");
    throw new Error(payload?.detail || "Not authenticated");
  }
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  return payload;
}
