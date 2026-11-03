import React from "react";
import { Route, Routes } from "react-router-dom";
import AdminRoutes from "./pages/admin/AdminRoutes.jsx";
import VendorRoutes from "./pages/vendor/VendorRoutes.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/admin/*" element={<AdminRoutes />} />
      <Route path="/*" element={<VendorRoutes />} />
    </Routes>
  );
}
