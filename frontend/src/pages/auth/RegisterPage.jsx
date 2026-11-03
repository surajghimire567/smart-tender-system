import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import "./Auth.css";

export default function RegisterPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", company_name: "", registration_number: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function update(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await apiRequest("/auth/register", {
        method: "POST", authenticated: false, body: JSON.stringify(form),
      });
      setForm({ name: "", email: "", password: "", company_name: "", registration_number: "" });
      navigate("/login", { replace: true, state: { notice: "Registration complete. Sign in to continue." } });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Vendor registration</h1>
        <label>Name<input name="name" autoComplete="name" minLength={2} maxLength={100} required value={form.name} onChange={update} /></label>
        <label>Email<input name="email" type="email" autoComplete="email" maxLength={254} required value={form.email} onChange={update} /></label>
        <label>Password<input name="password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required value={form.password} onChange={update} /></label>
        <label>Company name<input name="company_name" minLength={2} maxLength={200} required value={form.company_name} onChange={update} /></label>
        <label>Registration number<input name="registration_number" minLength={3} maxLength={50} required value={form.registration_number} onChange={update} /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button disabled={busy}>{busy ? "Registering…" : "Register"}</button>
        <p>Already registered? <Link to="/login">Sign in</Link></p>
      </form>
    </main>
  );
}
