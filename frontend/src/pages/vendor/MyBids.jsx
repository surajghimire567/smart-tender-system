import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import "./vendor.css";

const date = (value) => new Intl.DateTimeFormat("en-NP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kathmandu" }).format(new Date(value));

export default function MyBids() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try { setError(""); setRows(await apiRequest("/vendor/bids")); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); const timer = window.setInterval(load, 20000); return () => window.clearInterval(timer); }, [load]);

  return (
    <main className="vendor-page">
      <header className="vendor-header"><h1>My bids and receipts</h1><div className="vendor-actions"><Link to="/tenders">Browse tenders</Link><button className="vendor-button" onClick={load}>Refresh</button></div></header>
      {error && <p className="vendor-error" role="alert">{error}</p>}
      {loading ? <p>Loading…</p> : rows.length === 0 ? <p>You have not submitted any bids.</p> : (
        <div className="vendor-table-wrap"><table className="vendor-table"><thead><tr><th>Tender</th><th>Status</th><th>Submitted</th><th>Receipt hash</th><th>Bid</th></tr></thead><tbody>
          {rows.map((row) => <tr key={row.bid_id}><td>{row.tender_title}</td><td>{row.tender_status}</td><td>{date(row.submitted_at)} NPT</td><td className="vendor-hash">{row.bid_hash}</td><td>{row.is_current ? "Current" : "Superseded"}{row.tender_status !== "published" && <> · <Link to={`/my-bids/${row.tender_id}/result`}>View my result</Link></>}</td></tr>)}
        </tbody></table></div>
      )}
    </main>
  );
}
