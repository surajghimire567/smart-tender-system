import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearSession } from "../../auth/token.js";

export default function AdminShell() {
  const navigate = useNavigate();

  function logout() {
    clearSession();
    navigate("/login", { replace: true });
  }

  return (
    <>
      <header className="app-topbar">
        <NavLink className="app-brand" to="/admin" end>
          <span className="app-brand-mark" aria-hidden="true">ST</span>
          <span><strong>Smart Tender</strong><small>Administration</small></span>
        </NavLink>
        <nav className="app-navigation" aria-label="Admin navigation">
          <NavLink to="/admin" end>Overview</NavLink>
          <NavLink to="/admin/collusion-flags">Collusion flags</NavLink>
          <NavLink to="/admin/audit-logs">Audit log</NavLink>
          <button type="button" onClick={logout}>Log out</button>
        </nav>
      </header>
      <div className="app-main"><Outlet /></div>
    </>
  );
}
