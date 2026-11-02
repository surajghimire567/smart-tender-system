import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import "./vendor.css";

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "NPR" });
const date = (value) => new Intl.DateTimeFormat("en-NP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kathmandu" }).format(new Date(value));

function Receipt({ value }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  async function copy() {
    await navigator.clipboard.writeText(value.bid_hash);
    setCopied(true);
  }
  return <section className="vendor-card"><h2>Bid receipt</h2><p>Bid #{value.bid_id} · submitted {date(value.submitted_at)} NPT</p><p className="vendor-hash">{value.bid_hash}</p><div className="vendor-actions"><button className="vendor-button" onClick={copy}>Copy receipt hash</button>{copied && <span>Copied</span>}</div><p className="vendor-muted">The bid amount remains sealed; keep this hash receipt.</p></section>;
}

export default function TenderDetail() {
  const { tenderId } = useParams();
  const [tender, setTender] = useState(null);
  const [amount, setAmount] = useState("");
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try { setError(""); setTender(await apiRequest(`/tenders/${tenderId}`)); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, [tenderId]);
  useEffect(() => { load(); const timer = window.setInterval(load, 20000); return () => window.clearInterval(timer); }, [load]);

  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await apiRequest(`/tenders/${tenderId}/bids`, { method: "POST", body: JSON.stringify({ amount }) });
      setAmount("");
      setReceipt(result);
      await load();
    } catch (err) { setError(err.message); }
  }

  if (loading) return <main className="vendor-page"><p>Loading tender…</p></main>;
  if (!tender) return <main className="vendor-page"><p className="vendor-error" role="alert">{error || "Tender not found"}</p><Link to="/tenders">Back to tenders</Link></main>;
  return (
    <main className="vendor-page">
      <p><Link to="/tenders">← Published tenders</Link></p>
      <article className="vendor-card">
        <h1>{tender.title}</h1><p>{tender.description}</p>
        <p>Ceiling price: {money.format(Number(tender.ceiling_price))}</p>
        <p>Deadline: {date(tender.deadline)} NPT</p>
        <p>{tender.is_open ? "Open for bidding" : "Not open for bidding"}</p>
        {tender.my_current_bid && <Receipt value={tender.my_current_bid} />}
      </article>
      {tender.is_open && <form className="vendor-form" onSubmit={submit}>
        <h2>Submit a bid</h2>
        <label>Bid amount (NPR)<input type="number" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <button className="vendor-button">Seal bid</button>
        <p className="vendor-muted">The server validates the deadline and ceiling. The amount is not shown again after submission.</p>
      </form>}
      {error && <p className="vendor-error" role="alert">{error}</p>}
      {receipt && <Receipt value={receipt} />}
    </main>
  );
}
