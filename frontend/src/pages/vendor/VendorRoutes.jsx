import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import ProtectedRoute from "../../auth/ProtectedRoute.jsx";
import VendorRoute from "../../auth/VendorRoute.jsx";
import LoginPage from "../auth/LoginPage.jsx";
import RegisterPage from "../auth/RegisterPage.jsx";
import MyBids from "./MyBids.jsx";
import TenderDetail from "./TenderDetail.jsx";
import TenderList from "./TenderList.jsx";
import VendorResult from "./VendorResult.jsx";
import VendorShell from "./VendorShell.jsx";
import { getRole, getToken } from "../../auth/token.js";

function HomeRedirect() {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <Navigate to={getRole() === "admin" ? "/admin" : "/tenders"} replace />;
}

export default function VendorRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomeRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<VendorRoute />}>
          <Route element={<VendorShell />}>
            <Route path="/tenders" element={<TenderList />} />
            <Route path="/tenders/:tenderId" element={<TenderDetail />} />
            <Route path="/my-bids" element={<MyBids />} />
            <Route path="/my-bids/:tenderId/result" element={<VendorResult />} />
            <Route path="*" element={<main className="vendor-page"><h1>Page not found</h1><p><a href="/tenders">Browse published tenders</a></p></main>} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}
