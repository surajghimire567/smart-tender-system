import React from "react";
import { Route, Routes } from "react-router-dom";
import ProtectedRoute from "../../auth/ProtectedRoute.jsx";
import VendorRoute from "../../auth/VendorRoute.jsx";
import LoginPage from "../auth/LoginPage.jsx";
import RegisterPage from "../auth/RegisterPage.jsx";
import MyBids from "./MyBids.jsx";
import TenderDetail from "./TenderDetail.jsx";
import TenderList from "./TenderList.jsx";
import VendorResult from "./VendorResult.jsx";

export default function VendorRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<VendorRoute />}>
          <Route path="/tenders" element={<TenderList />} />
          <Route path="/tenders/:tenderId" element={<TenderDetail />} />
          <Route path="/my-bids" element={<MyBids />} />
          <Route path="/my-bids/:tenderId/result" element={<VendorResult />} />
        </Route>
      </Route>
    </Routes>
  );
}
