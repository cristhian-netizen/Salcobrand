// Pure helpers for the dataset sweep screen (DatasetImages.jsx), tested with node:test.

// "24 MB" / "2,4 MB" (es-CL): one decimal below 10 MB, whole numbers above.
export function fmtMB(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return '0 MB';
  const mb = n / (1024 * 1024);
  const shown = mb >= 10 ? Math.round(mb) : Math.max(0.1, Math.round(mb * 10) / 10);
  return shown.toLocaleString('es-CL', {maximumFractionDigits: 1}) + ' MB';
}

// Per-file progress while the originals go up sequentially: "3/8 · 24 MB".
export const progressLabel = (done, total, bytes) => `${done}/${total} · ${fmtMB(bytes)}`;

// Category header / chip subtitle: "12 fotos · 340 MB".
export function categorySummary(count, bytes) {
  return `${count === 1 ? '1 foto' : `${count || 0} fotos`} · ${fmtMB(bytes)}`;
}

// Totals of the loaded grid (the header must match what the grid shows, not a stale server count).
export const totalsOf = images => (images || []).reduce(
  (t, image) => ({count: t.count + 1, bytes: t.bytes + (Number(image.bytes) || 0)}), {count: 0, bytes: 0});

// "4000 × 3000 px" or null when HEIC dimensions could not be read (the photo is stored anyway).
export function dimensionsLabel(image) {
  return image && Number.isFinite(image.width) && Number.isFinite(image.height)
    ? `${image.width} × ${image.height} px` : null;
}
