import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearSession } from "../../auth/token.js";

export default function VendorShell() {
  const navigate = useNavigate();

  function logout() {
    clearSession();
    navigate("/login", { replace: true });
  }

  return (
    <>
      <header className="app-topbar">
        <NavLink className="app-brand" to="/tenders">
          <span className="app-brand-mark" aria-hidden="true">ST</span>
          <span><strong>Smart Tender</strong><small>Vendor workspace</small></span>
        </NavLink>
        <nav className="app-navigation" aria-label="Vendor navigation">
          <NavLink to="/tenders">Browse tenders</NavLink>
          <NavLink to="/my-bids">My bids</NavLink>
          <button type="button" onClick={logout}>Log out</button>
        </nav>
      </header>
      <div className="app-main"><Outlet /></div>
    </>
  );
}
