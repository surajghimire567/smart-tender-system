/**
 * Person 2 auth-contract stubs for Person 1's module.
 * TODO: replace this file's exports with imports from Person 2's auth/token.js,
 * auth/device.js, and ProtectedRoute when that branch is merged.
 * These browser checks are UX only; FastAPI's require_role("admin") is the
 * security boundary.
 */
import React from "react";
import { Navigate } from "react-router-dom";

export function getToken() {
  return window.localStorage.getItem("st_token");
}

export function getRole() {
  return window.localStorage.getItem("st_role");
}

export function setSession(token, role) {
  window.localStorage.setItem("st_token", token);
  window.localStorage.setItem("st_role", role);
}

export function clearSession() {
  window.localStorage.removeItem("st_token");
  window.localStorage.removeItem("st_role");
  window.localStorage.removeItem("st_device_id");
}

export function getDeviceId() {
  return window.localStorage.getItem("st_device_id") || "unknown";
}

export function ProtectedRoute({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}
