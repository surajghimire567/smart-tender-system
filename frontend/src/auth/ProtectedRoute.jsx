import React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { getToken } from "./token.js";

export default function ProtectedRoute({ children }) {
  return getToken() ? (children || <Outlet />) : <Navigate to="/login" replace />;
}
