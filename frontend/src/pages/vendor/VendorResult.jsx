import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import "./vendor.css";

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "NPR" });

export default function VendorResult() {
  const { tenderId } = useParams();
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try { setError(""); setResult(await apiRequest(`/vendor/tenders/${tenderId}/result`)); }
    catch (err) { setError(err.message); setResult(null); }
    finally { setLoading(false); }
  }, [tenderId]);
  useEffect(() => { load(); const timer = window.setInterval(load, 20000); return () => window.clearInterval(timer); }, [load]);

  return (
    <main className="vendor-page">
      <header className="vendor-header"><h1>My tender result</h1><button className="vendor-button" onClick={load}>Refresh</button></header>
      {loading && <p>Loading result…</p>}
      {error && <p className="vendor-error" role="alert">{error}</p>}
      {result && <section className="vendor-card">
        <p>Tender #{result.tender_id} · {result.status}</p>
        <p>My rank: {result.my_rank}</p>
        <p>My bid amount: {money.format(Number(result.my_amount))}</p>
        <p>Total current bids: {result.total_bids}</p>
        <p>Outcome: {result.outcome}</p>
      </section>}
      <p><Link to="/my-bids">Back to my bids</Link></p>
    </main>
  );
}
