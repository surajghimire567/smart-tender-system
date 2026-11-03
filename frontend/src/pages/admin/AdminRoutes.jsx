import React from "react";
import { Route, Routes } from "react-router-dom";
import AdminRoute from "./AdminRoute.jsx";
import "./admin.css";
import AdminDashboard from "./AdminDashboard.jsx";
import TenderDetail from "./TenderDetail.jsx";
import AdminShell from "./AdminShell.jsx";
import AuditLogs from "./AuditLogs.jsx";
import CollusionFlags from "./CollusionFlags.jsx";

export default function AdminRoutes() {
  return (
    <Routes>
      <Route element={<AdminRoute><AdminShell /></AdminRoute>}>
        <Route index element={<AdminDashboard />} />
        <Route path="tenders/:tenderId" element={<TenderDetail />} />
        <Route path="audit-logs" element={<AuditLogs />} />
        <Route path="collusion-flags" element={<CollusionFlags />} />
        <Route path="*" element={<main className="admin-page"><h1>Admin page not found</h1><p><a href="/admin">Back to overview</a></p></main>} />
      </Route>
    </Routes>
  );
}
