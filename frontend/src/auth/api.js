import { clearSession, getDeviceId, getToken } from "./token.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiRequest(path, options = {}) {
  const { authenticated = true, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers || {});
  headers.set("X-Device-Id", getDeviceId());
  const token = authenticated ? getToken() : null;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (fetchOptions.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.status === 401 && token) {
    clearSession();
    window.location.assign("/login");
  }
  if (!response.ok) {
    throw new ApiError(payload?.detail || `Request failed (${response.status})`, response.status);
  }
  return payload;
}
