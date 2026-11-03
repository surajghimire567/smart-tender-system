import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import Countdown from "./Countdown.jsx";
import StatusPill from "./StatusPill.jsx";
import TenderForm from "./TenderForm.jsx";
import { formatKathmandu, formatNpr } from "../../utils/format.js";

export default function TenderDetail() {
  const { tenderId } = useParams();
  const [tender, setTender] = useState(null);
  const [ranking, setRanking] = useState(null);
  const [flags, setFlags] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  async function refreshTender({ backgroundRefresh = false } = {}) {
    setError("");
    try {
      const data = await apiRequest(`/admin/tenders/${tenderId}`, { backgroundRefresh });
      setTender(data);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refreshTender();
    const timer = window.setInterval(() => refreshTender({ backgroundRefresh: true }), 20000);
    return () => window.clearInterval(timer);
  }, [tenderId]);

  async function runAction(path, method = "POST", body = undefined, successMessage = "Updated.") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiRequest(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      setNotice(successMessage);
      await refreshTender();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadRanking() {
    setError("");
    try {
      setRanking(await apiRequest(`/admin/tenders/${tenderId}/ranking`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadFlags() {
    setError("");
    try {
      setFlags(await apiRequest(`/admin/tenders/${tenderId}/flags`));
    } catch (err) {
      setError(err.message);
    }
  }

  if (!tender) {
    return <main className="admin-page"><Link to="/admin">← Dashboard</Link>{error ? <p className="error-message" role="alert">{error}</p> : <p>Loading tender…</p>}</main>;
  }

  return (
    <main className="admin-page">
      <Link to="/admin">← Dashboard</Link>
      <header className="admin-header">
        <div>
          <p className="eyebrow">Tender #{tender.id}</p>
          <h1>{tender.title}</h1>
          <StatusPill status={tender.status} />
        </div>
        <button className="secondary" type="button" onClick={refreshTender}>Refresh</button>
      </header>

      {error && <p className="error-message" role="alert">{error}</p>}
      {notice && <p className="success-message" role="status">{notice}</p>}

      <section className="admin-card tender-summary">
        <p>{tender.description}</p>
        <dl>
          <div><dt>Base price</dt><dd>{formatNpr(tender.base_price)}</dd></div>
          <div><dt>Ceiling price</dt><dd>{formatNpr(tender.ceiling_price)}</dd></div>
          <div><dt>Deadline (NPT)</dt><dd>{formatKathmandu(tender.deadline)}</dd></div>
          <div><dt>Countdown</dt><dd><Countdown deadline={tender.deadline} status={tender.status} /></dd></div>
          <div><dt>Created</dt><dd>{formatKathmandu(tender.created_at)}</dd></div>
        </dl>
        <div className="button-row">
          {tender.status === "draft" && <button type="button" className="secondary" onClick={() => setEditing((value) => !value)}>Edit draft</button>}
          {tender.status === "draft" && <button type="button" disabled={busy} onClick={() => runAction(`/admin/tenders/${tender.id}/publish`, "POST", undefined, "Tender published.")}>Publish</button>}
          {tender.status === "published" && <button type="button" className="danger" disabled={busy} onClick={() => runAction(`/admin/tenders/${tender.id}/close`, "POST", undefined, "Tender closed.")}>Close tender</button>}
          {(tender.status === "closed" || tender.status === "awarded") && <button type="button" className="secondary" onClick={loadRanking}>Load ranking</button>}
          {(tender.status === "closed" || tender.status === "awarded") && <button type="button" className="secondary" onClick={loadFlags}>Load collusion flags</button>}
        </div>
      </section>

      {editing && tender.status === "draft" && (
        <TenderForm tender={tender} onCancel={() => setEditing(false)} onSaved={(saved) => {
          setTender(saved);
          setEditing(false);
          setNotice("Draft updated.");
        }} />
      )}

      {ranking && (
        <section className="admin-card">
          <h2>Post-deadline ranking</h2>
          <p>{ranking.ranked} eligible current bid(s); sorted lowest first.</p>
          {ranking.ranking.length === 0 ? <p>No eligible bids were ranked.</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Rank</th><th>Bid ID</th><th>Vendor ID</th><th>Amount</th><th>Submitted (NPT)</th><th>Gap %</th><th>Award</th></tr></thead>
                <tbody>{ranking.ranking.map((bid) => (
                  <tr key={bid.bid_id}>
                    <td>{bid.rank}</td><td>{bid.bid_id}</td><td>{bid.vendor_id}</td>
                    <td>{formatNpr(bid.amount)}</td><td>{formatKathmandu(bid.submitted_at)}</td>
                    <td>{bid.gap_pct === null ? "—" : `${bid.gap_pct}%`}</td>
                    <td>{tender.status === "closed" ? <button disabled={busy} onClick={() => runAction(`/admin/tenders/${tender.id}/award`, "POST", { winning_bid_id: bid.bid_id }, `Award saved for bid #${bid.bid_id}.`)}>Award this bid</button> : "Awarded"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {ranking.excluded?.length > 0 && <div><h3>Excluded bids</h3><ul>{ranking.excluded.map((bid) => <li key={bid.bid_id}>Bid #{bid.bid_id} · vendor #{bid.vendor_id}: {bid.reason}</li>)}</ul></div>}
        </section>
      )}

      {flags && (
        <section className="admin-card">
          <h2>Collusion flags</h2>
          {flags.length === 0 ? <p>No flags recorded for this tender.</p> : (
            <ul className="flag-list">
              {flags.map((flag) => (
                <li key={flag.id}>
                  <strong>{flag.vendor_id_b === null ? `Vendor #${flag.vendor_id_a}` : `Vendor pair #${flag.vendor_id_a} / #${flag.vendor_id_b}`}</strong>
                  <span>{flag.rule === "high_win_share" ? "High win share" : "Repeated undercutting"}</span>
                  <span>{flag.flag_reason}</span>
                  <time>{formatKathmandu(flag.flagged_at)}</time>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}
