"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/sb";
import { can } from "../../lib/profiles.mjs";
import { Card, ErrorBox } from "./ui";

export default function MeasurementReview({ reading, user, onSaved }) {
  const [saved, setSaved] = useState(
    reading.review || { status: "En revisión", note: "", version: 0 },
  );
  const [status, setStatus] = useState(saved.status);
  const [note, setNote] = useState(saved.note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const editable = can(user, "review");
  useEffect(() => {
    if (reading.review && reading.review.version !== saved.version) {
      setSaved(reading.review);
      setStatus(reading.review.status);
      setNote(reading.review.note);
      setError('');
      setMessage('');
    }
  }, [reading.review, saved.version]);
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api(`/api/readings/${reading.id}/review`, {
        method: "PATCH",
        body: { status, note, version: saved.version },
      });
      setSaved(updated);
      onSaved?.(updated);
      setStatus(updated.status);
      setNote(updated.note);
      setMessage(
        "Revisión guardada. Los reportes y las métricas usarán este estado.",
      );
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  if (!editable) return saved.note ? <p className="sb-hint measurement-review-note"><b>Observación del analista:</b> {saved.note}</p> : null;
  return (
    <Card
      className="measurement-review"
      title="Estado de la medición"
      subtitle="Solo las mediciones aprobadas se consideran en el desempeño."
    >
      <ErrorBox error={error} />
        <form className="sb-form" onSubmit={save}>
          <label>
            Estado
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              disabled={busy}
            >
              {["En revisión", "Aprobado", "Rechazado"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Observación{status === "Rechazado" ? " (obligatoria)" : ""}
            <textarea
              value={note}
              maxLength={2000}
              required={status === "Rechazado"}
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <div className="sb-actions full">
            <button
              type="submit"
              disabled={
                busy || (saved.status === status && saved.note === note)
              }
            >
              {busy ? "Guardando…" : "Guardar revisión"}
            </button>
            {message && <span role="status">{message}</span>}
          </div>
        </form>

    </Card>
  );
}
