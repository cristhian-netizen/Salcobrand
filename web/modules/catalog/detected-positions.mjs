// Positions the server detects when a planogram PDF is uploaded (zones/levels proposed for review).
// Applying them replaces the editor rows only after the person confirms it; nothing is saved by itself.
export const detectedRows = (detected) => (detected?.positionRows || []).map((row) => ({
  level: row.level || 1,
  position: row.position || 1,
  faces: row.faces || 1,
  productId: row.productId || '',
  sku: row.sku || '',
  barcode: row.barcode || '',
  legacy_item_id: null,
  legacy_title: '',
  detected_title: row.detected_title || '',
}));

// detected_title is a review hint, never part of the saved planogram payload.
export const cleanRow = ({ detected_title, ...row }) => row;
