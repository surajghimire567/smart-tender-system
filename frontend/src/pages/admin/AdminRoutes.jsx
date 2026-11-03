import React from "react";
import { Route, Routes } from "react-router-dom";
import AdminRoute from "./AdminRoute.jsx";
import "./admin.css";
import AdminDashboard from "./AdminDashboard.jsx";
import TenderDetail from "./TenderDetail.jsx";

/** Mount this component at /admin/* inside the existing React Router tree. */
export default function AdminRoutes() {
  return (
    <Routes>
      <Route index element={<AdminRoute><AdminDashboard /></AdminRoute>} />
      <Route path="tenders/:tenderId" element={<AdminRoute><TenderDetail /></AdminRoute>} />
    </Routes>
  );
}
