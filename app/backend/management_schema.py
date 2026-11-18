"""Additive master data: physical gondolas keep their original points/readings IDs."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS management_clients (
  id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  tenant_json TEXT NOT NULL, model_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  updated_by TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS management_people (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', data_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS management_person_username_ci ON management_people(LOWER(username));
CREATE UNIQUE INDEX IF NOT EXISTS management_person_email_ci ON management_people(LOWER(email)) WHERE email<>'';
CREATE TABLE IF NOT EXISTS management_reading_alerts (
  reading_id BIGINT NOT NULL, kind TEXT NOT NULL, fingerprint TEXT NOT NULL,
  status TEXT NOT NULL, version INTEGER NOT NULL, updated_by TEXT, updated_at TEXT,
  PRIMARY KEY(reading_id, kind)
);
CREATE TABLE IF NOT EXISTS management_settings (
  id INTEGER PRIMARY KEY, data_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
  updated_by TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS management_reading_reviews (
  reading_id BIGINT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL, updated_by TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS management_review_status ON management_reading_reviews(status, reading_id);
CREATE TABLE IF NOT EXISTS management_reading_details (
  reading_id BIGINT PRIMARY KEY, data_json TEXT NOT NULL, version INTEGER NOT NULL,
  updated_by TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS management_capture_requests (
  request_key TEXT PRIMARY KEY, submitted_by TEXT NOT NULL, point_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS management_capture_owner ON management_capture_requests(submitted_by, created_at);
CREATE TABLE IF NOT EXISTS management_catalog_state (
  id INTEGER PRIMARY KEY, version INTEGER NOT NULL
);
INSERT INTO management_catalog_state (id, version) VALUES (1, 1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS management_products (
  id TEXT PRIMARY KEY, sku TEXT NOT NULL, name TEXT NOT NULL, data_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS management_product_sku_ci ON management_products(LOWER(sku));
CREATE TABLE IF NOT EXISTS management_planograms (
  id TEXT PRIMARY KEY, data_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS management_stores (
  code TEXT PRIMARY KEY, name TEXT NOT NULL, store_type TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '', commune TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
  manager TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Activo', description TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS management_store_code_ci ON management_stores(LOWER(code));
CREATE TABLE IF NOT EXISTS management_shelf_types (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, width_cm DOUBLE PRECISION NOT NULL, depths_json TEXT NOT NULL,
  photo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Activo', version INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL DEFAULT 'Estante', supplier TEXT NOT NULL DEFAULT '', height_cm DOUBLE PRECISION,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS management_assignments (
  store_code TEXT NOT NULL, type_id TEXT NOT NULL, quantity INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL, PRIMARY KEY(store_code, type_id)
);
CREATE TABLE IF NOT EXISTS management_instances (
  id TEXT PRIMARY KEY, store_code TEXT NOT NULL, type_id TEXT NOT NULL, number INTEGER NOT NULL,
  point_id TEXT NOT NULL UNIQUE, label TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
  UNIQUE(store_code, type_id, number)
);
CREATE TABLE IF NOT EXISTS management_events (
  id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, resource_id TEXT NOT NULL,
  before_json TEXT, after_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS management_training_labels (
 id TEXT PRIMARY KEY, reading_id INTEGER NOT NULL, image_index INTEGER NOT NULL, item_index INTEGER NOT NULL,
 data_json TEXT NOT NULL, crop_path TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(reading_id,image_index,item_index)
);
CREATE TABLE IF NOT EXISTS management_plan_scope_state (
 plan_id TEXT PRIMARY KEY REFERENCES planograms(id) ON DELETE CASCADE, initialized_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS management_plan_scopes (
 plan_id TEXT NOT NULL REFERENCES planograms(id) ON DELETE CASCADE,
 store_code TEXT NOT NULL REFERENCES management_stores(code) ON DELETE CASCADE,
 category TEXT NOT NULL, subcategory TEXT NOT NULL, type_id TEXT NOT NULL DEFAULT '',
 assigned_by TEXT NOT NULL, assigned_at TEXT NOT NULL,
 PRIMARY KEY(plan_id,store_code,category,subcategory,type_id)
);
CREATE INDEX IF NOT EXISTS management_plan_scope_lookup ON management_plan_scopes(store_code,category,subcategory,type_id);
"""
