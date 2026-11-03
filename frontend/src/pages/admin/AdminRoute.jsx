import React from "react";
import { Navigate } from "react-router-dom";
import { getRole, ProtectedRoute } from "./deps.jsx";

function AdminRoleGate({ children }) {
  return getRole() === "admin" ? children : <Navigate to="/login" replace />;
}

/** P1's admin guard wraps P2's shared authenticated-user guard. */
export default function AdminRoute({ children }) {
  return (
    <ProtectedRoute>
      <AdminRoleGate>{children}</AdminRoleGate>
    </ProtectedRoute>
  );
}
