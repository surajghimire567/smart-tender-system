import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../../auth/api.js";
import { formatKathmandu } from "../../utils/format.js";

const RULE_LABELS = {
  repeated_undercutting: "Repeated 1–2% undercutting",
  high_win_share: "High win share",
};

export default function CollusionFlags() {
  const [filters, setFilters] = useState({ rule: "", tender_id: "", vendor_id: "" });
  const [applied, setApplied] = useState(filters);
  const [flags, setFlags] = useState([]);
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(selected = applied) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    for (const key of ["rule", "tender_id", "vendor_id"]) {
      const value = selected[key].trim();
      if (value) params.set(key, value);
    }
    try {
      const suffix = params.size ? "?" + params.toString() : "";
      setFlags(await apiRequest("/auction/collusion/flags" + suffix));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(applied); }, [applied]);

  async function runScan() {
    setScanning(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest("/auction/collusion/scan", { method: "POST" });
      setScan(result);
      setNotice("Scan complete: " + result.new_flags + " new flag(s), " + result.already_saved + " already recorded.");
      await load(applied);
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    setApplied({ ...filters });
    if (JSON.stringify(filters) === JSON.stringify(applied)) load(filters);
  }

  return (
    <main className="admin-page">
      <header className="admin-header">
        <div>
          <p className="eyebrow">L10 · both collusion rules</p>
          <h1>Collusion flags</h1>
          <p>Saved evidence from repeated close bids and unusually high win shares.</p>
        </div>
        <button type="button" disabled={scanning} onClick={runScan}>{scanning ? "Scanning…" : "Run collusion scan"}</button>
      </header>

      {notice && <p className="success-message" role="status">{notice}</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {scan && <section className="scan-summary" role="status">
        <div><strong>{scan.pairs_flagged}</strong><span>vendor pairs</span></div>
        <div><strong>{scan.vendors_flagged}</strong><span>high win-share vendors</span></div>
        <div><strong>{scan.flags_found}</strong><span>evidence rows found</span></div>
        <div><strong>{scan.tenders_scanned.length}</strong><span>closed tenders scanned</span></div>
      </section>}

      <form className="admin-card audit-filters" onSubmit={submit}>
        <label>Rule<select value={filters.rule} onChange={(e) => setFilters({ ...filters, rule: e.target.value })}>
          <option value="">All rules</option>
          <option value="repeated_undercutting">Repeated 1–2% undercutting</option>
          <option value="high_win_share">High win share</option>
        </select></label>
        <label>Tender ID<input inputMode="numeric" value={filters.tender_id} onChange={(e) => setFilters({ ...filters, tender_id: e.target.value })} /></label>
        <label>Vendor ID<input inputMode="numeric" value={filters.vendor_id} onChange={(e) => setFilters({ ...filters, vendor_id: e.target.value })} /></label>
        <button type="submit">Filter flags</button>
      </form>

      <section className="admin-card">
        <div className="section-heading"><div><h2>Saved flags</h2><p>Only closed tenders are included in collusion scans.</p></div><button className="secondary" type="button" onClick={() => load()}>Refresh</button></div>
        {loading ? <p>Loading flags…</p> : flags.length === 0 ? <p>No flags match these filters.</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Rule</th><th>Tender</th><th>Vendor(s)</th><th>Evidence</th><th>Flagged (NPT)</th></tr></thead>
              <tbody>{flags.map((flag) => (
                <tr key={flag.id}>
                  <td><span className={"rule-pill rule-" + flag.rule}>{RULE_LABELS[flag.rule] ?? flag.rule}</span></td>
                  <td><Link to={"/admin/tenders/" + flag.tender_id}># {flag.tender_id}</Link></td>
                  <td>{flag.vendor_id_b === null ? "Vendor # " + flag.vendor_id_a : "# " + flag.vendor_id_a + " and # " + flag.vendor_id_b}</td>
                  <td className="flag-evidence">{flag.flag_reason}</td>
                  <td>{formatKathmandu(flag.flagged_at)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
