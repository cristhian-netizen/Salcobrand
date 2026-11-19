"""Postgres para producción (DATABASE_URL=postgresql://...) con la misma interfaz mínima de sqlite3 que usa db.py:
conn.execute(sql, params) con `?`, filas como dict (row["col"], row.keys(), dict(row)), cur.lastrowid, cur.rowcount.

- `?` → `%s` (fuera de comillas); `%` literal → `%%` cuando hay parámetros.
- INSERT en tablas con id autoincremental: se agrega `RETURNING id` y se expone como `lastrowid`.
- Pool de conexiones por proceso (psycopg2 ThreadedConnectionPool); una conexión rota se descarta.
- Sin claves foráneas (SQLite no las aplicaba: db.py borra en el orden que quiere).
- migrate_from_sqlite(): copia una base SQLite existente (la de EFS) a Postgres una sola vez, conservando ids.
"""
import os
import re
import sqlite3
import threading
from management_schema import SCHEMA as MANAGEMENT_SCHEMA
from contextlib import closing, contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

def _url_from_env() -> str:
    """DATABASE_URL, o compuesta desde DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD (así la entrega ECS: la contraseña
    llega desde Secrets Manager como variable propia)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url or not os.environ.get("DB_HOST"):
        return url
    from urllib.parse import quote

    password = os.environ.get("DB_PASSWORD", "")
    secret_arn = os.environ.get("DB_PASSWORD_SECRET_ARN", "").strip()
    if not password and secret_arn:  # la contraseña vive en Secrets Manager; la lee el rol de la tarea
        import boto3

        password = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")) \
            .get_secret_value(SecretId=secret_arn)["SecretString"].strip()
    return (f"postgresql://{quote(os.environ.get('DB_USER', 'salcobrand'), safe='')}:{quote(password, safe='')}"
            f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}/{os.environ.get('DB_NAME', 'salcobrand')}"
            f"?sslmode={os.environ.get('DB_SSLMODE', 'require')}")


URL = _url_from_env()
SERIAL_TABLES = {"readings", "planogram_items", "stock_actions", "supplier_stockouts", "shadow_runs", "captures"}
_pool = None
_pool_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, planogram_id TEXT,
  owner_client TEXT, store_id TEXT, gondola_id TEXT
);
CREATE TABLE IF NOT EXISTS readings (
  id BIGSERIAL PRIMARY KEY, point_id TEXT NOT NULL, created_at TEXT NOT NULL, total_facings INTEGER,
  shelf_levels_detected INTEGER, empty_space_pct DOUBLE PRECISION, products_json TEXT, categories_json TEXT, notes TEXT,
  image_path TEXT, image_paths_json TEXT, linear_meters DOUBLE PRECISION, planogram_id TEXT, compliance_json TEXT,
  engine_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_point ON readings(point_id, id);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at TEXT NOT NULL,
  role TEXT, store_id TEXT, store_name TEXT
);
CREATE TABLE IF NOT EXISTS planograms (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, module_cm DOUBLE PRECISION, bands INTEGER, source_filename TEXT,
  created_at TEXT NOT NULL, owner_client TEXT
);
CREATE TABLE IF NOT EXISTS planogram_items (
  id BIGSERIAL PRIMARY KEY, planogram_id TEXT NOT NULL, order_seq INTEGER, section_label TEXT, module INTEGER,
  band INTEGER, segment INTEGER, position_in_section INTEGER, title TEXT NOT NULL, internal_code TEXT, barcode TEXT,
  expected_facings INTEGER, tag TEXT, price_clp DOUBLE PRECISION, price_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_planogram_items_pg ON planogram_items(planogram_id);
CREATE TABLE IF NOT EXISTS stock_actions (
  id BIGSERIAL PRIMARY KEY, point_id TEXT NOT NULL, planogram_item_id BIGINT, product_title TEXT NOT NULL,
  action_type TEXT NOT NULL, quantity INTEGER NOT NULL, note TEXT, created_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS supplier_stockouts (
  id BIGSERIAL PRIMARY KEY, point_id TEXT NOT NULL, planogram_item_id BIGINT NOT NULL, product_title TEXT NOT NULL,
  note TEXT, created_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS api_jobs (
  job_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, point_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, reading_id BIGINT, error TEXT, payload_json TEXT, engine_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_jobs_status ON api_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS shadow_runs (
  id BIGSERIAL PRIMARY KEY, job_id TEXT, reading_id BIGINT, created_at TEXT NOT NULL, main_version TEXT,
  shadow_version TEXT, result_json TEXT
);
CREATE TABLE IF NOT EXISTS capture_links (
  token TEXT PRIMARY KEY, store_id TEXT NOT NULL, label TEXT, created_at TEXT NOT NULL, created_by TEXT,
  expires_at TEXT, active INTEGER NOT NULL DEFAULT 1, max_per_day INTEGER, locales_json TEXT
);
CREATE TABLE IF NOT EXISTS captures (
  id BIGSERIAL PRIMARY KEY, token TEXT NOT NULL, store_id TEXT NOT NULL, created_at TEXT NOT NULL,
  rel_path TEXT NOT NULL, bytes INTEGER, width INTEGER, height INTEGER, franja TEXT, device TEXT,
  tipo TEXT, cliente_id TEXT, tomada_en TEXT, origen TEXT
);
CREATE INDEX IF NOT EXISTS idx_captures_store ON captures(store_id, created_at);
-- migración 8-nov-2026 (bases creadas antes): enlace universal y tipo de foto; idempotente, columnas sin NOT NULL
-- (la versión anterior del servicio sigue insertando con su lista de columnas durante el despliegue)
ALTER TABLE capture_links ADD COLUMN IF NOT EXISTS locales_json TEXT;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS tipo TEXT;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS cliente_id TEXT;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS tomada_en TEXT;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS origen TEXT;
CREATE INDEX IF NOT EXISTS idx_captures_cliente ON captures(token, cliente_id);
-- Additive profile migration. Existing accounts and readings remain valid.
ALTER TABLE users ADD COLUMN IF NOT EXISTS store_ids_json TEXT;
ALTER TABLE readings ADD COLUMN IF NOT EXISTS captured_by TEXT;
ALTER TABLE readings ADD COLUMN IF NOT EXISTS capture_context_json TEXT;
ALTER TABLE readings ADD COLUMN IF NOT EXISTS plan_snapshot_json TEXT;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
SCHEMA += MANAGEMENT_SCHEMA
SCHEMA += """
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_internal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS portal_access INTEGER NOT NULL DEFAULT 1;
ALTER TABLE management_shelf_types ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'Estante';
ALTER TABLE management_shelf_types ADD COLUMN IF NOT EXISTS supplier TEXT NOT NULL DEFAULT '';
ALTER TABLE management_shelf_types ADD COLUMN IF NOT EXISTS height_cm DOUBLE PRECISION;
ALTER TABLE management_shelf_types ADD COLUMN IF NOT EXISTS deleted INTEGER NOT NULL DEFAULT 0;
-- multi-catalog (nov-2026): the Kilby catalog each product was/will be sent to
ALTER TABLE management_kilby_products ADD COLUMN IF NOT EXISTS catalog TEXT;
DROP INDEX IF EXISTS management_shelf_name_ci;
CREATE UNIQUE INDEX IF NOT EXISTS management_shelf_name_active_ci ON management_shelf_types(LOWER(name)) WHERE deleted=0;
"""
TABLE_ORDER = [
    "points", "users", "planograms", "planogram_items", "readings",
    "stock_actions", "supplier_stockouts", "api_jobs", "shadow_runs",
    "capture_links", "captures", "management_clients", "management_people",
    "management_reading_alerts", "management_settings", "management_reading_reviews",
    "management_reading_details", "management_capture_requests", "management_catalog_state",
    "management_products", "management_planograms", "management_stores",
    "management_shelf_types", "management_assignments", "management_instances",
    "management_events", "management_training_labels", "management_training_suggestions", "management_plan_scope_state", "management_plan_scopes",
    "management_integrations", "management_kilby_products", "management_kilby_trainings",
]


def enabled() -> bool:
    return URL.startswith("postgres")


def _translate(sql: str) -> str:
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self):
        try:
            return self._cur.fetchone()
        except psycopg2.ProgrammingError:  # sentencia sin filas
            return None

    def fetchall(self):
        try:
            return self._cur.fetchall()
        except psycopg2.ProgrammingError:
            return []

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=()):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        args = tuple(params) if params else None
        q = _translate(sql) if args is not None else sql
        m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, re.I)
        if m and m.group(1).lower() in SERIAL_TABLES and "returning" not in sql.lower():
            cur.execute(q + " RETURNING id", args)
            row = cur.fetchone()
            return Cursor(cur, row["id"] if row else None)
        cur.execute(q, args)
        return Cursor(cur)

    def executescript(self, script: str):
        with self.raw.cursor() as cur:
            cur.execute(script)

    def commit(self):
        self.raw.commit()


# ThreadedConnectionPool raises PoolError as soon as every connection is busy. FastAPI serves sync
# endpoints from a ~40-thread pool, so bursts above DB_POOL_MAX turned into HTTP 500s. A semaphore of
# the same size makes extra requests wait for a free connection instead.
# A thread that already holds a connection and asks for another (nested get_conn) reuses it: waiting on
# the semaphore there would let threads holding every slot block each other until the timeout.
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
_slots = threading.BoundedSemaphore(POOL_MAX)
_held = threading.local()
POOL_WAIT_S = float(os.environ.get("DB_POOL_WAIT_S", "30"))


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1, POOL_MAX, dsn=URL, connect_timeout=10,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
                application_name=os.environ.get("ROLE", "app"))
        return _pool


@contextmanager
def connection():
    outer = getattr(_held, "conn", None)
    if outer is not None:
        # Same transaction as the enclosing block, which commits or rolls back.
        yield outer
        return
    if not _slots.acquire(timeout=POOL_WAIT_S):
        raise psycopg2.pool.PoolError("connection pool exhausted (waited %.0f s)" % POOL_WAIT_S)
    try:
        with _connection() as conn:
            _held.conn = conn
            try:
                yield conn
            finally:
                _held.conn = None
    finally:
        _slots.release()


@contextmanager
def _connection():
    pool = _get_pool()
    raw = pool.getconn()
    broken = False
    try:
        if raw.closed:
            pool.putconn(raw, close=True)
            raw = pool.getconn()
        yield Connection(raw)
        raw.commit()
    except Exception as exc:
        broken = raw.closed or isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))
        try:
            if not raw.closed:
                raw.rollback()
        except Exception:
            broken = True
        raise
    finally:
        pool.putconn(raw, close=broken)


def init_schema():
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(424242)")
        conn.executescript(SCHEMA)


def meta_get(key: str):
    with connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(key: str, value: str):
    with connection() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (key, value))


def migrate_from_sqlite(sqlite_path) -> dict:
    """Copia la base SQLite a Postgres UNA vez (marca meta.sqlite_migrated). Si Postgres ya tiene puntos o lecturas y no
    está marcado, no copia nada (no pisa datos). Conserva ids y ajusta las secuencias. Todo en una transacción."""
    from datetime import datetime, timezone

    if meta_get("sqlite_migrated"):
        return {"skipped": "ya migrada"}
    if not os.path.exists(sqlite_path):
        meta_set("sqlite_migrated", "sin archivo sqlite")
        return {"skipped": "no hay sqlite"}
    counts = {}
    with closing(sqlite3.connect(str(sqlite_path))) as src, connection() as conn:
        src.row_factory = sqlite3.Row
        conn.execute("SELECT pg_advisory_xact_lock(424243)")
        if conn.execute("SELECT value FROM meta WHERE key = 'sqlite_migrated'").fetchone():
            return {"skipped": "ya migrada"}
        seeded_tables = {"planograms", "planogram_items", "management_catalog_state"}
        checks = [f"(SELECT COUNT(*) FROM {table})" for table in TABLE_ORDER if table not in seeded_tables]
        busy = conn.execute("SELECT " + " + ".join(checks) + " AS n").fetchone()["n"]
        if busy:
            conn.execute("INSERT INTO meta (key, value) VALUES ('sqlite_migrated', 'omitida: postgres ya tenía datos') "
                         "ON CONFLICT (key) DO NOTHING")
            return {"skipped": "postgres ya tenía datos"}
        conn.execute("DELETE FROM planogram_items")  # semilla previa (si la hubo): la fuente de verdad es SQLite
        conn.execute("DELETE FROM planograms")
        for t in TABLE_ORDER:
            try:
                rows = src.execute(f"SELECT * FROM {t}").fetchall()
            except sqlite3.OperationalError:
                counts[t] = 0
                continue
            if not rows:
                counts[t] = 0
                continue
            pg_cols = {r["column_name"] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?", (t,)).fetchall()}
            cols = list(rows[0].keys())
            unsupported = set(cols) - pg_cols
            if unsupported:
                raise ValueError(f"Columnas de {t} pendientes de migración: {sorted(unsupported)}")
            if t == "management_catalog_state":
                conn.execute("DELETE FROM management_catalog_state")
            sql = f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            with closing(conn.raw.cursor()) as cur:
                psycopg2.extras.execute_batch(cur, sql, [tuple(r[c] for c in cols) for r in rows], page_size=500)
            counts[t] = len(rows)
            if t in SERIAL_TABLES:
                conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 1), "
                             f"(SELECT MAX(id) FROM {t}) IS NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('sqlite_migrated', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (datetime.now(timezone.utc).isoformat() + " " + str(counts),))
    print(f"[db] migración SQLite → Postgres: {counts}", flush=True)
    return counts
