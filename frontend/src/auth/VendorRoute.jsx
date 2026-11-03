import React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { getRole } from "./token.js";

export default function VendorRoute({ children }) {
  if (getRole() !== "vendor") return <Navigate to="/login" replace />;
  return children || <Outlet />;
}
