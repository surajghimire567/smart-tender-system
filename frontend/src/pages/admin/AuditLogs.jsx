import React, { useEffect, useState } from "react";
import { apiRequest } from "../../auth/api.js";
import { formatKathmandu } from "../../utils/format.js";

const PAGE_SIZE = 50;

export default function AuditLogs() {
  const [filters, setFilters] = useState({ tender_id: "", actor_id: "", action: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(offset = 0, selected = applied) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    for (const key of ["tender_id", "actor_id", "action"]) {
      const value = selected[key].trim();
      if (value) params.set(key, value);
    }
    try {
      setPage(await apiRequest("/admin/audit-logs?" + params.toString()));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(0, applied); }, [applied]);

  function submit(event) {
    event.preventDefault();
    setApplied({ ...filters });
    if (JSON.stringify(filters) === JSON.stringify(applied)) load(0, filters);
  }

  const first = page.total === 0 ? 0 : page.offset + 1;
  const last = Math.min(page.offset + page.items.length, page.total);

  return (
    <main className="admin-page">
      <header className="admin-header">
        <div>
          <p className="eyebrow">L6 · L9 · append-only events</p>
          <h1>Audit log</h1>
          <p>Review tender activity, login and device warnings, and sealed-bid receipts.</p>
        </div>
        <button className="secondary" type="button" onClick={() => load(page.offset)}>Refresh</button>
      </header>

      <form className="admin-card audit-filters" onSubmit={submit}>
        <label>Tender ID<input inputMode="numeric" value={filters.tender_id} onChange={(e) => setFilters({ ...filters, tender_id: e.target.value })} /></label>
        <label>Actor ID<input inputMode="numeric" value={filters.actor_id} onChange={(e) => setFilters({ ...filters, actor_id: e.target.value })} /></label>
        <label>Action<input maxLength={80} placeholder="e.g. DEVICE_ANOMALY" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} /></label>
        <button type="submit">Apply filters</button>
      </form>

      {error && <p className="error-message" role="alert">{error}</p>}
      <section className="admin-card">
        <div className="section-heading">
          <div><h2>Recorded events</h2><p>{page.total} event(s) match these filters.</p></div>
          <span className="audit-range">{first}–{last} of {page.total}</span>
        </div>
        {loading ? <p>Loading audit events…</p> : page.items.length === 0 ? <p>No matching events.</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time (NPT)</th><th>Action</th><th>Tender</th><th>Actor</th><th>IP</th><th>Details</th></tr></thead>
              <tbody>{page.items.map((event) => (
                <tr key={event.id}>
                  <td>{formatKathmandu(event.timestamp)}</td>
                  <td><span className={"audit-action audit-action-" + event.action.toLowerCase()}>{event.action}</span></td>
                  <td>{event.tender_id ?? "—"}</td>
                  <td>{event.actor_id ?? "System"}</td>
                  <td>{event.ip_address ?? "—"}</td>
                  <td><details><summary>Inspect</summary><pre>{JSON.stringify(event.details ?? {}, null, 2)}</pre></details></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="button-row audit-pagination">
          <button className="secondary" type="button" disabled={loading || page.offset <= 0} onClick={() => load(Math.max(0, page.offset - PAGE_SIZE))}>Previous</button>
          <button className="secondary" type="button" disabled={loading || page.offset + PAGE_SIZE >= page.total} onClick={() => load(page.offset + PAGE_SIZE)}>Next</button>
        </div>
      </section>
    </main>
  );
}
