const TOKEN_KEY = "st_token";
const ROLE_KEY = "st_role";
const DEVICE_KEY = "st_device_id";

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getRole() {
  return window.localStorage.getItem(ROLE_KEY);
}

export function setSession(token, role) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(ROLE_KEY, role);
  getDeviceId();
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(ROLE_KEY);
  window.localStorage.removeItem(DEVICE_KEY);
}

export function getDeviceId() {
  let value = window.localStorage.getItem(DEVICE_KEY);
  if (!value) {
    value = window.crypto.randomUUID();
    window.localStorage.setItem(DEVICE_KEY, value);
  }
  return value;
}
