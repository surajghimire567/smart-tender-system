import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import "./vendor.css";

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "NPR" });
const date = (value) => new Intl.DateTimeFormat("en-NP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kathmandu" }).format(new Date(value));

export default function TenderList() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      setError("");
      setRows(await apiRequest("/tenders?status=published"));
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); const timer = window.setInterval(load, 20000); return () => window.clearInterval(timer); }, [load]);

  return (
    <main className="vendor-page">
      <header className="vendor-header"><div><h1>Published tenders</h1><p className="vendor-muted">Only published tenders are listed to vendors.</p></div><button className="vendor-button" onClick={load}>Refresh</button></header>
      {error && <p className="vendor-error" role="alert">{error}</p>}
      {loading ? <p>Loading…</p> : rows.length === 0 ? <p>No published tenders are available.</p> : (
        <section className="vendor-grid">{rows.map((tender) => (
          <article className="vendor-card" key={tender.id}>
            <h2>{tender.title}</h2>
            <p>Ceiling price: {money.format(Number(tender.ceiling_price))}</p>
            <p>Deadline: {date(tender.deadline)} NPT</p>
            <p>{tender.is_open ? "Open for bidding" : "Closed for bidding"}</p>
            {tender.has_my_bid && <p className="vendor-muted">You have a bid receipt for this tender.</p>}
            <Link className="vendor-button" to={`/tenders/${tender.id}`}>View tender</Link>
          </article>
        ))}</section>
      )}
      <p><Link to="/my-bids">My bids and receipts</Link></p>
    </main>
  );
}
