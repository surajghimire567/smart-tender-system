import React, { useEffect, useState } from "react";
import { apiRequest } from "../../auth/api.js";
import { fromKathmanduInput, toKathmanduInput } from "../../utils/format.js";

function blankForm() {
  return { title: "", description: "", base_price: "", ceiling_price: "", deadline: "" };
}

export default function TenderForm({ tender = null, onSaved, onCancel }) {
  const [form, setForm] = useState(blankForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const editing = Boolean(tender);

  useEffect(() => {
    if (!tender) {
      setForm(blankForm());
      return;
    }
    setForm({
      title: tender.title,
      description: tender.description,
      base_price: String(tender.base_price),
      ceiling_price: String(tender.ceiling_price),
      deadline: toKathmanduInput(tender.deadline),
    });
  }, [tender]);

  function setField(event) {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const body = {
      title: form.title,
      description: form.description,
      base_price: form.base_price,
      ceiling_price: form.ceiling_price,
      deadline: fromKathmanduInput(form.deadline),
    };
    try {
      const saved = editing
        ? await apiRequest(`/admin/tenders/${tender.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : await apiRequest("/admin/tenders", {
            method: "POST",
            body: JSON.stringify(body),
          });
      onSaved?.(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="admin-card tender-form" onSubmit={submit}>
      <h2>{editing ? "Edit draft tender" : "Create draft tender"}</h2>
      {error && <p className="error-message" role="alert">{error}</p>}
      <label>
        Title
        <input name="title" minLength="1" required value={form.title} onChange={setField} />
      </label>
      <label>
        Description
        <textarea name="description" required value={form.description} onChange={setField} rows="4" />
      </label>
      <div className="form-grid">
        <label>
          Base price (NPR)
          <input name="base_price" type="number" min="0.01" step="0.01" required value={form.base_price} onChange={setField} />
        </label>
        <label>
          Ceiling price (NPR)
          <input name="ceiling_price" type="number" min="0.01" step="0.01" required value={form.ceiling_price} onChange={setField} />
        </label>
      </div>
      <label>
        Deadline (Asia/Kathmandu)
        <input name="deadline" type="datetime-local" required value={form.deadline} onChange={setField} />
      </label>
      <div className="button-row">
        <button type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Save draft" : "Create draft"}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
