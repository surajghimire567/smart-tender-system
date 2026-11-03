import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { adminRequest } from "./api.js";
import Countdown from "./Countdown.jsx";
import StatusPill from "./StatusPill.jsx";
import TenderForm from "./TenderForm.jsx";
import { formatKathmandu, formatNpr } from "../../utils/format.js";

export default function AdminDashboard() {
  const [tenders, setTenders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    setError("");
    try {
      const rows = await adminRequest("/admin/tenders");
      setTenders(rows);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 20000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="admin-page">
      <header className="admin-header">
        <div>
          <p className="eyebrow">Smart Tender System</p>
          <h1>Admin dashboard</h1>
          <p>Manage tender drafts, publication, closure, ranking, flags, and awards.</p>
        </div>
        <button className="secondary" type="button" onClick={refresh}>Refresh</button>
      </header>

      {error && <p className="error-message" role="alert">{error}</p>}
      {notice && <p className="success-message" role="status">{notice}</p>}

      <TenderForm onSaved={(tender) => {
        setNotice(`Draft tender #${tender.id} created.`);
        refresh();
      }} />

      <section className="admin-card">
        <div className="section-heading">
          <div><h2>Tenders</h2><p>Countdowns are display-only; server time controls tender state.</p></div>
          <button className="secondary" type="button" onClick={refresh}>Refresh list</button>
        </div>
        {loading ? <p>Loading tenders…</p> : tenders.length === 0 ? <p>No tenders yet.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Tender</th><th>Status</th><th>Deadline (NPT)</th><th>Time remaining</th><th>Ceiling price</th><th /></tr>
              </thead>
              <tbody>
                {tenders.map((tender) => (
                  <tr key={tender.id}>
                    <td>{tender.id}</td>
                    <td><Link to={`/admin/tenders/${tender.id}`}>{tender.title}</Link></td>
                    <td><StatusPill status={tender.status} /></td>
                    <td>{formatKathmandu(tender.deadline)}</td>
                    <td><Countdown deadline={tender.deadline} status={tender.status} /></td>
                    <td>{formatNpr(tender.ceiling_price)}</td>
                    <td><Link className="button-link" to={`/admin/tenders/${tender.id}`}>Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
