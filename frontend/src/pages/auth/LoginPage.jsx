import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import { setSession } from "../../auth/token.js";
import "./Auth.css";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await apiRequest("/auth/login", {
        method: "POST", authenticated: false,
        body: JSON.stringify({ email, password }),
      });
      setSession(result.access_token, result.role);
      setPassword("");
      navigate(result.role === "admin" ? "/admin" : "/tenders", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Sign in</h1>
        <label>Email<input type="email" autoComplete="email" maxLength={254} required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" minLength={1} maxLength={72} required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p>New vendor? <Link to="/register">Register</Link></p>
      </form>
    </main>
  );
}
