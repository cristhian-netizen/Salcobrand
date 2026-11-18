import json
import os
import re
import sqlite3
from management_schema import SCHEMA as MANAGEMENT_SCHEMA
from profiles import PROFILES, LEGACY_PROFILES, INTERNAL_PROFILES
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "data.db"
PLANOGRAM_SEED_PATH = Path(__file__).resolve().parent / "planogramas" / "planograms_seed.json"

# Altura promedio asumida por nivel de estante (metros). Es un supuesto de referencia,
# no una medición: la altura real de cada góndola varía por local y categoría.
LEVEL_HEIGHT_M = 0.35

# Umbral mínimo de similitud de texto (Jaccard sobre tokens) para considerar que un
# producto detectado por la IA corresponde a una posición específica del planograma.
MATCH_THRESHOLD = 0.35
# Bajo este puntaje (contra TODO el planograma, no solo el nivel candidato), un producto
# detectado se considera ajeno al planograma ("fuera de lugar").
FOREIGN_THRESHOLD = 0.15
# Similitud de nombre (Jaccard) entre dos PRODUCTOS DETECTADOS para asumir que son el
# mismo producto visto dos veces (aparece repetido en la percha o quedó dividido entre
# fotos superpuestas), y no dos productos distintos.
DUPLICATE_THRESHOLD = 0.6
# Meta de rotulación de precios pedida por la farmacia: 95% de las posiciones con
# producto detectado deben tener rótulo de precio visible.
PRICE_TAG_TARGET_PCT = 95

SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  planogram_id TEXT
);
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  point_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  total_facings INTEGER,
  shelf_levels_detected INTEGER,
  empty_space_pct REAL,
  products_json TEXT,
  categories_json TEXT,
  notes TEXT,
  image_path TEXT,
  FOREIGN KEY (point_id) REFERENCES points(id)
);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planograms (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  module_cm REAL,
  bands INTEGER,
  source_filename TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planogram_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  planogram_id TEXT NOT NULL,
  order_seq INTEGER,
  section_label TEXT,
  module INTEGER,
  band INTEGER,
  segment INTEGER,
  position_in_section INTEGER,
  title TEXT NOT NULL,
  internal_code TEXT,
  barcode TEXT,
  expected_facings INTEGER,
  tag TEXT,
  price_clp REAL,
  FOREIGN KEY (planogram_id) REFERENCES planograms(id)
);
CREATE TABLE IF NOT EXISTS stock_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  point_id TEXT NOT NULL,
  planogram_item_id INTEGER,
  product_title TEXT NOT NULL,
  action_type TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  note TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  FOREIGN KEY (point_id) REFERENCES points(id)
);
CREATE TABLE IF NOT EXISTS supplier_stockouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  point_id TEXT NOT NULL,
  planogram_item_id INTEGER NOT NULL,
  product_title TEXT NOT NULL,
  note TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  FOREIGN KEY (point_id) REFERENCES points(id)
);
CREATE TABLE IF NOT EXISTS api_jobs (
  job_id TEXT PRIMARY KEY,
  client_id TEXT NOT NULL,
  point_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  reading_id INTEGER,
  error TEXT,
  payload_json TEXT,
  engine_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_jobs_status ON api_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS capture_links (
  token TEXT PRIMARY KEY, store_id TEXT NOT NULL, label TEXT, created_at TEXT NOT NULL, created_by TEXT,
  expires_at TEXT, active INTEGER NOT NULL DEFAULT 1, max_per_day INTEGER, locales_json TEXT
);
CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, store_id TEXT NOT NULL, created_at TEXT NOT NULL,
  rel_path TEXT NOT NULL, bytes INTEGER, width INTEGER, height INTEGER, franja TEXT, device TEXT,
  tipo TEXT, cliente_id TEXT, tomada_en TEXT, origen TEXT
);
CREATE INDEX IF NOT EXISTS idx_captures_store ON captures(store_id, created_at);
CREATE TABLE IF NOT EXISTS shadow_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  reading_id INTEGER,
  created_at TEXT NOT NULL,
  main_version TEXT,
  shadow_version TEXT,
  result_json TEXT
);
"""


# Producción: Postgres (DATABASE_URL). Desarrollo y pruebas: SQLite en DATA_DIR/data.db, como siempre.
USE_PG = os.environ.get("DATABASE_URL", "").strip().startswith("postgres") or bool(os.environ.get("DB_HOST"))
if USE_PG:
    import pgcompat


@contextmanager
def get_conn():
    if USE_PG:
        with pgcompat.connection() as conn:
            yield conn
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(role: str = None):
    """Crea el esquema. En Postgres, el rol 'api' (o 'all') además migra una sola vez la base SQLite de EFS y siembra
    los planogramas; el rol 'worker' solo crea el esquema y espera a que la API marque meta.ready."""
    role = role or os.environ.get("ROLE", "all")
    if USE_PG:
        pgcompat.init_schema()
        if role in ("api", "all"):
            pgcompat.migrate_from_sqlite(DB_PATH)
            _seed_planograms_if_empty()
            with get_conn() as conn:
                conn.execute("UPDATE users SET role = 'admin' WHERE role IS NULL OR role = ''")
            _backfill_authors()
            pgcompat.meta_set("ready", now_iso())
        return
    with get_conn() as conn:
        conn.executescript(SCHEMA + MANAGEMENT_SCHEMA)
        for statement in (
            "ALTER TABLE management_shelf_types ADD COLUMN kind TEXT NOT NULL DEFAULT 'Estante'",
            "ALTER TABLE management_shelf_types ADD COLUMN supplier TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE management_shelf_types ADD COLUMN height_cm DOUBLE PRECISION",
            "ALTER TABLE management_shelf_types ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE readings ADD COLUMN image_paths_json TEXT",
            "ALTER TABLE readings ADD COLUMN linear_meters REAL",
            "ALTER TABLE readings ADD COLUMN planogram_id TEXT",
            "ALTER TABLE readings ADD COLUMN compliance_json TEXT",
            "ALTER TABLE points ADD COLUMN planogram_id TEXT",
            "ALTER TABLE planogram_items ADD COLUMN price_source TEXT",
            "ALTER TABLE readings ADD COLUMN engine_json TEXT",
            "ALTER TABLE readings ADD COLUMN captured_by TEXT",
            "ALTER TABLE readings ADD COLUMN capture_context_json TEXT",
            "ALTER TABLE readings ADD COLUMN plan_snapshot_json TEXT",
            # API v1: el cliente que creó el punto/planograma por la API (NULL = creado en la app)
            "ALTER TABLE points ADD COLUMN owner_client TEXT",
            "ALTER TABLE points ADD COLUMN store_id TEXT",
            "ALTER TABLE points ADD COLUMN gondola_id TEXT",
            "ALTER TABLE planograms ADD COLUMN owner_client TEXT",
            # roles: 'tienda' (solo su local), 'supervisor' (ve todo), 'admin' (ve todo y administra usuarios)
            "ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_internal INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN portal_access INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN role TEXT",
            "ALTER TABLE users ADD COLUMN store_id TEXT",
            "ALTER TABLE users ADD COLUMN store_name TEXT",
            "ALTER TABLE users ADD COLUMN store_ids_json TEXT",
            # captura por enlace (8-nov-2026): enlace universal (lista de locales) y tipo de foto (góndola / producto)
            "ALTER TABLE capture_links ADD COLUMN locales_json TEXT",
            "ALTER TABLE captures ADD COLUMN tipo TEXT",
            "ALTER TABLE captures ADD COLUMN cliente_id TEXT",
            "ALTER TABLE captures ADD COLUMN tomada_en TEXT",
            "ALTER TABLE captures ADD COLUMN origen TEXT",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
        conn.execute('DROP INDEX IF EXISTS management_shelf_name_ci')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS management_shelf_name_active_ci ON management_shelf_types(LOWER(name)) WHERE deleted=0')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_cliente ON captures(token, cliente_id)")
        # usuarios creados antes de los roles conservan acceso total
        conn.execute("UPDATE users SET role = 'admin' WHERE role IS NULL OR role = ''")
    _backfill_authors()
    _seed_planograms_if_empty()


ROLES = (*PROFILES, *LEGACY_PROFILES, *INTERNAL_PROFILES)


def _backfill_authors():
    """Recover only recorded job authors; never guess an owner for historical photos."""
    with get_conn() as conn:
        jobs = conn.execute("SELECT reading_id, payload_json FROM api_jobs WHERE reading_id IS NOT NULL ORDER BY created_at").fetchall()
        for job in jobs:
            try:
                author = json.loads(job["payload_json"] or "{}").get("user")
            except (ValueError, AttributeError):
                continue
            if isinstance(author, str) and author:
                conn.execute("UPDATE readings SET captured_by = ? WHERE id = ? AND captured_by IS NULL", (author, job["reading_id"]))


def _scope_where(scope, column="store_id"):
    if scope is None:
        return "1=1", ()
    values = (scope,) if isinstance(scope, str) else tuple(scope)
    return (f"{column} IN ({','.join('?' for _ in values)})", values) if values else ("1=0", ())


def _reading_where(point_id, captured_by=None):
    return ("point_id = ?", (point_id,)) if captured_by is None else ("point_id = ? AND captured_by = ?", (point_id, captured_by))


def _seed_planograms_if_empty():
    if not PLANOGRAM_SEED_PATH.exists():
        return
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM planograms").fetchone()
        if row["c"]:
            return
        seed = json.loads(PLANOGRAM_SEED_PATH.read_text(encoding="utf-8"))
        for pg in seed:
            _insert_planogram(conn, pg)


def _insert_planogram(conn, pg: dict) -> None:
    conn.execute(
        "INSERT INTO planograms (id, name, module_cm, bands, source_filename, created_at, owner_client) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pg["id"], pg["name"], pg.get("module_cm"), pg.get("bands"), pg.get("source_filename"), now_iso(),
         pg.get("owner_client")),
    )
    for it in pg["items"]:
        conn.execute(
            "INSERT INTO planogram_items (planogram_id, order_seq, section_label, module, band, "
            "segment, position_in_section, title, internal_code, barcode, expected_facings, tag, price_clp, price_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pg["id"], it["order_seq"], it["section_label"], it["module"], it["band"],
                it["segment"], it["position_in_section"], it["title"], it.get("internal_code"),
                it.get("barcode"), it["expected_facings"], it.get("tag"), it.get("price_clp"), it.get("price_source"),
            ),
        )


def create_planogram(pg: dict) -> None:
    with get_conn() as conn:
        _insert_planogram(conn, pg)


def delete_planogram(planogram_id: str) -> None:
    import catalog_service
    with get_conn() as conn:
        catalog_service.lock_catalog(conn)
        plan = get_planogram(planogram_id)
        if plan:
            catalog_service.freeze_readings(conn, plan)
        conn.execute("UPDATE points SET planogram_id = NULL WHERE planogram_id = ?", (planogram_id,))
        conn.execute("DELETE FROM planogram_items WHERE planogram_id = ?", (planogram_id,))
        conn.execute("DELETE FROM management_plan_scopes WHERE plan_id=?",(planogram_id,))
        conn.execute("DELETE FROM management_plan_scope_state WHERE plan_id=?",(planogram_id,))
        conn.execute("DELETE FROM planograms WHERE id = ?", (planogram_id,))
        conn.execute("DELETE FROM management_planograms WHERE id = ?", (planogram_id,))
        catalog_service.changed(conn)


def replace_planogram(pg: dict) -> None:
    import catalog_service
    with get_conn() as conn:
        catalog_service.lock_catalog(conn)
        if conn.execute("SELECT id FROM management_planograms WHERE id = ?", (pg["id"],)).fetchone():
            raise ValueError("Este planograma tiene edición de catálogo. Actualízalo desde su modal para conservar su PDV y versión.")
        before = get_planogram(pg["id"])
        if before:
            catalog_service.freeze_readings(conn, before)
            conn.execute("DELETE FROM planogram_items WHERE planogram_id = ?", (pg["id"],))
            conn.execute("DELETE FROM planograms WHERE id = ?", (pg["id"],))
        _insert_planogram(conn, pg)
        catalog_service.changed(conn)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def user_exists(username: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    return row is not None


def create_user(username: str, password_hash: str, salt: str, role: str = "admin",
                store_id: str = None, store_name: str = None, store_ids=None, conn=None) -> None:
    if role not in ROLES:
        raise ValueError(f"Rol desconocido: {role}")
    with (nullcontext(conn) if conn is not None else get_conn()) as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, created_at, role, store_id, store_name, store_ids_json, auth_version, is_internal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (username, password_hash, salt, now_iso(), role, store_id or None, store_name or None,
             json.dumps(store_ids) if store_ids is not None else None, int(role in INTERNAL_PROFILES)),
        )

        conn.execute('UPDATE management_people SET version=version+1 WHERE LOWER(username)=LOWER(?)', (username,))


def count_users() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def _user_public(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "username": row["username"],
        "role": (row["role"] if "role" in keys else None) or "admin",
        "store_id": row["store_id"] if "store_id" in keys else None,
        "store_name": row["store_name"] if "store_name" in keys else None,
        "store_ids": json.loads(row["store_ids_json"]) if "store_ids_json" in keys and row["store_ids_json"] else ([row["store_id"]] if "store_id" in keys and row["store_id"] else []),
        "created_at": row["created_at"],
    }


def list_users() -> list:
    """Usuarios con su rol y local (sin hash ni sal)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE is_internal=0 AND portal_access=1 ORDER BY username").fetchall()
    return [_user_public(r) for r in rows]


def update_user(username: str, role: str = None, store_id=None, store_name=None, set_store: bool = False,
                password_hash: str = None, salt: str = None, store_ids=None, conn=None) -> dict:
    """Cambia rol, local (si set_store=True, también permite dejarlo vacío) y/o contraseña."""
    sets, params = [], []
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Rol desconocido: {role}")
        sets.append("role = ?"); params.append(role)
    if set_store:
        sets.append("store_id = ?"); params.append(store_id or None)
        sets.append("store_name = ?"); params.append(store_name or None)
        sets.append("store_ids_json = ?"); params.append(json.dumps(store_ids) if store_ids is not None else None)
    if password_hash is not None and salt is not None:
        sets.append("password_hash = ?"); params.append(password_hash)
        sets.append("salt = ?"); params.append(salt)
    with (nullcontext(conn) if conn is not None else get_conn()) as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        if sets:
            sets.append('auth_version = auth_version + 1')
            conn.execute('UPDATE management_people SET version=version+1 WHERE LOWER(username)=LOWER(?)', (username,))
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE username = ?", (*params, username))
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _user_public(row) if row else None


def store_names() -> dict:
    """{store_id: store_name} conocido por los usuarios de tienda (el nombre del local vive en users)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT store_id, store_name FROM users WHERE store_id IS NOT NULL AND store_id != '' ORDER BY username"
        ).fetchall()
    out = {}
    for r in rows:
        if r["store_name"] and r["store_id"] not in out:
            out[r["store_id"]] = r["store_name"]
    with get_conn() as conn:
        for row in conn.execute("SELECT code, name FROM management_stores").fetchall():
            out[row["code"]] = row["name"]
    return out


def point_store_id(point_id: str):
    """(existe, store_id) del punto."""
    with get_conn() as conn:
        row = conn.execute("SELECT store_id FROM points WHERE id = ?", (point_id,)).fetchone()
    return (True, row["store_id"]) if row else (False, None)


def reading_point_id(reading_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT point_id FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return row["point_id"] if row else None


def stock_action_point(action_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT point_id FROM stock_actions WHERE id = ?", (action_id,)).fetchone()
    return row["point_id"] if row else None


def supplier_stockout_point(stockout_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT point_id FROM supplier_stockouts WHERE id = ?", (stockout_id,)).fetchone()
    return row["point_id"] if row else None


def update_user_password(username: str, password_hash: str, salt: str) -> None:
    with get_conn() as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        conn.execute("UPDATE users SET password_hash = ?, salt = ?, auth_version=auth_version+1 WHERE username = ?", (password_hash, salt, username))
        conn.execute('UPDATE management_people SET version=version+1 WHERE LOWER(username)=LOWER(?)', (username,))


def list_usernames() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT username FROM users WHERE is_internal=0 AND portal_access=1 ORDER BY username").fetchall()
    return [r["username"] for r in rows]


def delete_user(username: str, conn=None) -> None:
    with (nullcontext(conn) if conn is not None else get_conn()) as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        conn.execute('DELETE FROM management_people WHERE LOWER(username)=LOWER(?)', (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def get_user(username: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["role"] = d.get("role") or "admin"
    d.setdefault("store_id", None)
    d.setdefault("store_name", None)
    d["store_ids"] = json.loads(d["store_ids_json"]) if d.get("store_ids_json") else ([d["store_id"]] if d["store_id"] else [])
    return d


def point_exists(point_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM points WHERE id = ?", (point_id,)).fetchone()
    return row is not None


def next_point_id() -> str:
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM points").fetchall()
    max_n = 0
    for row in rows:
        try:
            n = int(row["id"].split("-")[-1])
        except ValueError:
            continue
        max_n = max(max_n, n)
    return f"SB-{max_n + 1:03d}"


def create_point(point_id: str, name: str, planogram_id: str = None, owner_client: str = None,
                 store_id: str = None, gondola_id: str = None, conn=None) -> None:
    with (nullcontext(conn) if conn is not None else get_conn()) as conn:
        conn.execute(
            "INSERT INTO points (id, name, created_at, planogram_id, owner_client, store_id, gondola_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (point_id, name, now_iso(), planogram_id, owner_client, store_id, gondola_id),
        )


# ---------------------------------------------------------------------------
# API v1: puntos y planogramas con dueño (client_id) y cola de jobs
# ---------------------------------------------------------------------------

def _point_meta(conn, p: sqlite3.Row) -> dict:
    keys = p.keys()
    planogram_id = p["planogram_id"] if "planogram_id" in keys else None
    stats = conn.execute(
        "SELECT COUNT(*) AS c, MAX(created_at) AS last, MAX(id) AS last_id FROM readings WHERE point_id = ?", (p["id"],)
    ).fetchone()
    return {
        "id": p["id"],
        "name": p["name"],
        "created_at": p["created_at"],
        "planogram_id": planogram_id,
        "planogram_name": _point_planogram_name(conn, planogram_id),
        "owner_client": p["owner_client"] if "owner_client" in keys else None,
        "store_id": p["store_id"] if "store_id" in keys else None,
        "gondola_id": p["gondola_id"] if "gondola_id" in keys else None,
        "readings_count": stats["c"],
        "last_reading_at": stats["last"],
        "last_reading_id": stats["last_id"],
    }


def get_point_meta(point_id: str):
    """Punto sin su historial (liviano, para la API)."""
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM points WHERE id = ?", (point_id,)).fetchone()
        return _point_meta(conn, p) if p else None


def find_point_by_store_gondola(owner_client: str, store_id: str, gondola_id: str):
    with get_conn() as conn:
        p = conn.execute(
            "SELECT * FROM points WHERE owner_client = ? AND store_id = ? AND gondola_id = ?",
            (owner_client, store_id, gondola_id),
        ).fetchone()
        return _point_meta(conn, p) if p else None


def list_points_for_client(owner_client: str) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM points WHERE owner_client = ? ORDER BY id", (owner_client,)).fetchall()
        return [_point_meta(conn, p) for p in rows]


def readings_for_point(point_id: str, limit: int = 10) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM readings WHERE point_id = ? ORDER BY id DESC LIMIT ?", (point_id, int(limit))
        ).fetchall()
    return [_reading_dict(r) for r in rows]


def planogram_owner(planogram_id: str):
    """(existe, owner_client) — owner_client None = planograma creado en la app (compartido)."""
    with get_conn() as conn:
        row = conn.execute("SELECT owner_client FROM planograms WHERE id = ?", (planogram_id,)).fetchone()
    if not row:
        return False, None
    return True, row["owner_client"]


def insert_job(conn, job_id: str, client_id: str, point_id: str, payload: dict):
    conn.execute(
        "INSERT INTO api_jobs (job_id, client_id, point_id, status, created_at, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, client_id, point_id, "queued", now_iso(), json.dumps(payload)),
    )


def create_job(job_id: str, client_id: str, point_id: str, payload: dict) -> dict:
    with get_conn() as conn:
        insert_job(conn, job_id, client_id, point_id, payload)
    return get_job(job_id)


def _job_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    return d


def get_job(job_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM api_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_dict(row) if row else None


def set_job_running(job_id: str, stale_after_s: int = 900) -> bool:
    """Marca el job como en curso; False si ya no estaba en cola (duplicado o cancelado). Un job 'running' con más de
    `stale_after_s` segundos (worker que se detuvo a mitad) se puede tomar de nuevo."""
    from datetime import timedelta

    stale = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_s)).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE api_jobs SET status = 'running', started_at = ? WHERE job_id = ? "
            "AND (status = 'queued' OR (status = 'running' AND started_at < ?))",
            (now_iso(), job_id, stale),
        )
        return cur.rowcount > 0


def add_shadow_run(job_id: str, reading_id, main_version: str, shadow_version: str, result: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO shadow_runs (job_id, reading_id, created_at, main_version, shadow_version, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, reading_id, now_iso(), main_version, shadow_version, json.dumps(result)),
        )


def shadow_runs(limit: int = 200) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM shadow_runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d.pop("result_json") or "{}")
        out.append(d)
    return out


def finish_job(job_id: str, status: str, reading_id: int = None, error: str = None, engine_ms: int = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_jobs SET status = ?, finished_at = ?, reading_id = ?, error = ?, engine_ms = ? WHERE job_id = ?",
            (status, now_iso(), reading_id, error, engine_ms, job_id),
        )


def queued_job_ids() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT job_id FROM api_jobs WHERE status = 'queued' ORDER BY created_at, job_id").fetchall()
    return [r["job_id"] for r in rows]


def requeue_running_jobs() -> int:
    """Al arrancar: jobs que quedaron 'running' por un reinicio vuelven a la cola."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE api_jobs SET status = 'queued', started_at = NULL WHERE status = 'running'")
        return cur.rowcount


def job_counts() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS c FROM api_jobs GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


def purge_old_jobs(days: int = 7) -> int:
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM api_jobs WHERE created_at < ?", (cutoff,))
        return cur.rowcount


def set_point_planogram(point_id: str, planogram_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE points SET planogram_id = ? WHERE id = ?", (planogram_id, point_id))


def add_reading(
    point_id: str,
    analysis: dict,
    image_paths: list,
    linear_meters: float = None,
    planogram_id: str = None,
    captured_by: str = None,
    capture_context: dict = None,
    plan_snapshot: dict = None,
) -> dict:
    products = analysis.get("products", [])
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO readings (point_id, created_at, total_facings, shelf_levels_detected, "
            "empty_space_pct, products_json, categories_json, notes, image_paths_json, linear_meters, "
            "planogram_id, engine_json, captured_by, capture_context_json, plan_snapshot_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                point_id,
                now_iso(),
                analysis.get("total_facings"),
                analysis.get("shelf_levels_detected"),
                analysis.get("empty_space_pct"),
                json.dumps(products),
                json.dumps(analysis.get("categories", [])),
                analysis.get("notes", ""),
                json.dumps(image_paths or []),
                linear_meters,
                planogram_id,
                json.dumps(analysis.get("engine")) if analysis.get("engine") else None,
                captured_by,
                json.dumps(capture_context) if capture_context else None,
                json.dumps(plan_snapshot) if plan_snapshot else None,
            ),
        )
        reading_id = cur.lastrowid
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()

    if planogram_id and (not plan_snapshot or get_planogram(planogram_id) == plan_snapshot):
        _autofill_prices_from_reading(planogram_id, products)

    return _reading_dict(row)


def reading_planogram_snapshot(reading_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT plan_snapshot_json FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return json.loads(row["plan_snapshot_json"]) if row and row["plan_snapshot_json"] else None


def _autofill_prices_from_reading(planogram_id: str, products: list) -> None:
    """Lee price_tag_value (OCR) de los productos detectados y completa el precio de las
    posiciones del planograma que aún no tienen un precio cargado a mano."""
    compliance = compute_planogram_compliance(planogram_id, products)
    if not compliance:
        return
    item_prices = {}
    for ann, p in zip(compliance["product_annotations"], products):
        item_id = ann.get("planogram_item_id")
        value = p.get("price_tag_value")
        if item_id is not None and value is not None:
            item_prices[item_id] = value
    if item_prices:
        autofill_prices_from_ocr(planogram_id, item_prices)


def update_reading_analysis(reading_id: int, analysis: dict) -> dict:
    """Reemplaza los datos de detección de una lectura ya existente (misma foto, mismo
    punto, mismo momento) con un nuevo resultado de la IA — para re-analizar con un
    prompt mejorado sin inventar una lectura nueva en el historial."""
    products = analysis.get("products", [])
    with get_conn() as conn:
        conn.execute(
            "UPDATE readings SET total_facings = ?, shelf_levels_detected = ?, empty_space_pct = ?, "
            "products_json = ?, categories_json = ?, notes = ? WHERE id = ?",
            (
                analysis.get("total_facings"),
                analysis.get("shelf_levels_detected"),
                analysis.get("empty_space_pct"),
                json.dumps(products),
                json.dumps(analysis.get("categories", [])),
                analysis.get("notes", ""),
                reading_id,
            ),
        )
        invalidate_measurement_review(conn, reading_id)
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return _reading_dict(row)


def all_readings_with_images() -> list:
    """Lecturas de todos los puntos que tienen al menos una foto guardada, con su
    point_id y planogram_id (usado para re-analizar en lote)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, point_id, planogram_id, image_paths_json FROM readings "
            "WHERE image_paths_json IS NOT NULL AND image_paths_json != '[]' ORDER BY id"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "point_id": r["point_id"],
            "planogram_id": r["planogram_id"],
            "image_paths": json.loads(r["image_paths_json"] or "[]"),
        }
        for r in rows
    ]


def _reading_dict(row: sqlite3.Row) -> dict:
    keys = row.keys()
    paths_json = row["image_paths_json"] if "image_paths_json" in keys else None
    if paths_json:
        paths = json.loads(paths_json)
    elif "image_path" in keys and row["image_path"]:
        paths = [row["image_path"]]
    else:
        paths = []

    products = json.loads(row["products_json"] or "[]")
    linear_meters = row["linear_meters"] if "linear_meters" in keys else None
    total_facings = row["total_facings"] or 0
    levels = row["shelf_levels_detected"] or 0

    vertical_meters = round(levels * LEVEL_HEIGHT_M, 2) if levels else None
    display_area_m2 = round(linear_meters * vertical_meters, 2) if linear_meters and vertical_meters else None
    total_units_estimate = sum(
        (p.get("facings") or 0) * (p.get("estimated_depth") or 1) for p in products
    ) if products else None

    planogram_id = row["planogram_id"] if "planogram_id" in keys else None
    compliance = None
    if planogram_id:
        # Se recalcula en cada lectura (no se persiste) para que los precios cargados
        # después de la foto se reflejen de inmediato en el impacto $ estimado.
        snapshot = json.loads(row["plan_snapshot_json"]) if "plan_snapshot_json" in keys and row["plan_snapshot_json"] else None
        compliance = compute_planogram_compliance(planogram_id, products, planogram=snapshot)
        if compliance:
            for p, ann in zip(products, compliance.get("product_annotations", [])):
                p["planogram_status"] = ann["planogram_status"]
                p["planogram_tag"] = ann["planogram_tag"]

    standards = compute_shelf_standards(products, row["empty_space_pct"] if "empty_space_pct" in keys else None)

    reading = {
        "id": row["id"],
        "point_id": row["point_id"],
        "created_at": row["created_at"],
        "total_facings": row["total_facings"],
        "captured_by": row["captured_by"] if "captured_by" in keys else None,
        "review": measurement_review(row["id"]),
        "infrastructure": json.loads(row["capture_context_json"]) if "capture_context_json" in keys and row["capture_context_json"] else None,
        "shelf_levels_detected": row["shelf_levels_detected"],
        "empty_space_pct": row["empty_space_pct"],
        "products": products,
        "categories": json.loads(row["categories_json"] or "[]"),
        "notes": row["notes"],
        "image_urls": [f"/uploads/{p}" for p in paths],
        "linear_meters": linear_meters,
        "facings_per_linear_meter": round(total_facings / linear_meters, 1) if linear_meters else None,
        "vertical_meters": vertical_meters,
        "display_area_m2": display_area_m2,
        "total_units_estimate": total_units_estimate,
        "planogram_id": planogram_id,
        "compliance": compliance,
        "standards": standards,
        "engine": json.loads(row["engine_json"]) if "engine_json" in keys and row["engine_json"] else None,
        "needs_review": sum(1 for p in products if p.get("needs_review")),
        "image_paths": paths,
    }
    from capacity import estimate
    reading['capacity'] = estimate(reading)
    return reading


def get_reading(reading_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return _reading_dict(row) if row else None


def reading_for_photo(rel_path):
    with get_conn() as conn:
        rows = conn.execute("SELECT id, image_path, image_paths_json FROM readings WHERE image_path = ? OR image_paths_json LIKE ?",
                            (rel_path, "%" + rel_path + "%")).fetchall()
    for row in rows:
        paths = json.loads(row["image_paths_json"] or "[]")
        if rel_path == row["image_path"] or rel_path in paths:
            return row["id"]
    return None


def measurement_review(reading_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM management_reading_reviews WHERE reading_id = ?", (reading_id,)).fetchone()
    return dict(row) if row else {"reading_id": reading_id, "status": "En revisión", "note": "", "version": 0,
                                 "updated_by": None, "updated_at": None}


def invalidate_measurement_review(conn, reading_id, invalidate_details=True):
    # Product corrections change the evidence used for approval, within the same transaction.
    conn.execute("INSERT INTO management_reading_reviews (reading_id, status, note, version, updated_at) VALUES (?, 'En revisión', '', 1, ?) "
                 "ON CONFLICT (reading_id) DO UPDATE SET status = 'En revisión', version = management_reading_reviews.version + 1, updated_at = excluded.updated_at",
                 (reading_id, now_iso()))
    if invalidate_details:
        stored = conn.execute('SELECT data_json FROM management_reading_details WHERE reading_id = ?', (reading_id,)).fetchone()
        if stored:
            data = json.loads(stored['data_json'])
            data.update(scopeConfirmed=False, expectedConfirmed=False, comparisonConfirmed=False)
            conn.execute('UPDATE management_reading_details SET data_json = ?, version = version + 1, '
                         'updated_by = ?, updated_at = ? WHERE reading_id = ?',
                         (json.dumps(data), 'system:evidence-change', now_iso(), reading_id))


def update_reading_products(reading_id: int, products: list) -> dict:
    """Guarda productos corregidos por una persona (confirmaciones de /revision)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE readings SET products_json = ?, total_facings = ? WHERE id = ?",
            (json.dumps(products), sum((p.get("facings") or 0) for p in products), reading_id),
        )
        invalidate_measurement_review(conn, reading_id)
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return _reading_dict(row)


def delete_reading(reading_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM management_reading_alerts WHERE reading_id = ?", (reading_id,))
        conn.execute("DELETE FROM management_reading_details WHERE reading_id = ?", (reading_id,))
        conn.execute("DELETE FROM management_reading_reviews WHERE reading_id = ?", (reading_id,))
        cur = conn.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
        return cur.rowcount > 0


def readings_needing_review(limit: int = 20, store_id: str = None) -> list:
    """store_id: solo lecturas de los puntos de ese local (rol tienda)."""
    with get_conn() as conn:
        where, params = _scope_where(store_id, "p.store_id")
        rows = conn.execute(
            f"SELECT r.* FROM readings r JOIN points p ON p.id = r.point_id WHERE {where} ORDER BY r.id DESC LIMIT ?", (*params, limit)
        ).fetchall()
    out = []
    for row in rows:
        r = _reading_dict(row)
        if r["needs_review"]:
            out.append(r)
    return out


def _point_planogram_name(conn, planogram_id):
    if not planogram_id:
        return None
    row = conn.execute("SELECT name FROM planograms WHERE id = ?", (planogram_id,)).fetchone()
    return row["name"] if row else None


def list_points_with_latest(store_id: str = None, captured_by=None) -> list:
    """store_id: solo los puntos de ese local (rol tienda); None = todos."""
    with get_conn() as conn:
        where, params = _scope_where(store_id)
        points = conn.execute(f"SELECT * FROM points WHERE {where} ORDER BY id", params).fetchall()
        result = []
        for p in points:
            where, params = _reading_where(p["id"], captured_by)
            latest_row = conn.execute(
                f"SELECT * FROM readings WHERE {where} ORDER BY id DESC LIMIT 1", params,
            ).fetchone()
            count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM readings WHERE {where}", params
            ).fetchone()
            recent_rows = conn.execute(
                f"SELECT total_facings FROM readings WHERE {where} ORDER BY id DESC LIMIT 8", params,
            ).fetchall()
            recent_facings = [r["total_facings"] for r in reversed(recent_rows)]
            planogram_id = p["planogram_id"] if "planogram_id" in p.keys() else None
            result.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "created_at": p["created_at"],
                    "store_id": p["store_id"] if "store_id" in p.keys() else None,
                    "gondola_id": p["gondola_id"] if "gondola_id" in p.keys() else None,
                    "readings_count": count_row["c"],
                    "latest": latest_row,
                    "recent_facings": recent_facings,
                    "planogram_id": planogram_id,
                    "planogram_name": _point_planogram_name(conn, planogram_id),
                }
            )
    # _reading_dict may open its own connection (planogram compliance), so it runs after this one is released.
    for item in result:
        item["latest"] = _reading_dict(item["latest"]) if item["latest"] else None
    return result


def get_point(point_id: str, captured_by=None):
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM points WHERE id = ?", (point_id,)).fetchone()
        if not p:
            return None
        where, params = _reading_where(point_id, captured_by)
        readings = conn.execute(f"SELECT * FROM readings WHERE {where} ORDER BY id DESC", params).fetchall()
        planogram_id = p["planogram_id"] if "planogram_id" in p.keys() else None
        planogram_name = _point_planogram_name(conn, planogram_id)
    return {
        "id": p["id"],
        "name": p["name"],
        "created_at": p["created_at"],
        "store_id": p["store_id"] if "store_id" in p.keys() else None,
        "gondola_id": p["gondola_id"] if "gondola_id" in p.keys() else None,
        "readings": [_reading_dict(r) for r in readings],
        "planogram_id": planogram_id,
        "planogram_name": planogram_name,
    }


def delete_point(point_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM management_reading_alerts WHERE reading_id IN (SELECT id FROM readings WHERE point_id = ?)", (point_id,))
        conn.execute("DELETE FROM management_reading_details WHERE reading_id IN (SELECT id FROM readings WHERE point_id = ?)", (point_id,))
        conn.execute("DELETE FROM management_reading_reviews WHERE reading_id IN (SELECT id FROM readings WHERE point_id = ?)", (point_id,))
        conn.execute("DELETE FROM readings WHERE point_id = ?", (point_id,))
        conn.execute("DELETE FROM stock_actions WHERE point_id = ?", (point_id,))
        conn.execute("DELETE FROM supplier_stockouts WHERE point_id = ?", (point_id,))
        conn.execute("DELETE FROM points WHERE id = ?", (point_id,))


def export_rows(point_id: str = None, store_id: str = None) -> list:
    """Una fila por producto por lectura, para exportar a Excel/Power BI/Looker. store_id: solo ese local."""
    with get_conn() as conn:
        if point_id:
            readings = conn.execute(
                "SELECT r.*, p.name AS point_name FROM readings r JOIN points p ON p.id = r.point_id "
                "WHERE r.point_id = ? ORDER BY r.id",
                (point_id,),
            ).fetchall()
        elif store_id is not None:
            where, params = _scope_where(store_id, "p.store_id")
            readings = conn.execute(
                "SELECT r.*, p.name AS point_name FROM readings r JOIN points p ON p.id = r.point_id "
                f"WHERE {where} ORDER BY r.id", params,
            ).fetchall()
        else:
            readings = conn.execute(
                "SELECT r.*, p.name AS point_name FROM readings r JOIN points p ON p.id = r.point_id ORDER BY r.id"
            ).fetchall()

    rows = []
    for r in readings:
        products = json.loads(r["products_json"] or "[]")
        if not products:
            continue
        for p in products:
            estimated_depth = p.get("estimated_depth") or 1
            rows.append(
                {
                    "point_id": r["point_id"],
                    "point_name": r["point_name"],
                    "reading_id": r["id"],
                    "created_at": r["created_at"],
                    "product": p.get("product"),
                    "laboratorio": p.get("brand"),
                    "category": p.get("category"),
                    "facings": p.get("facings"),
                    "shelf_level": p.get("shelf_level"),
                    "position_index": p.get("position_index"),
                    "out_of_stock": p.get("out_of_stock"),
                    "estimated_depth": estimated_depth,
                    "units_estimate": (p.get("facings") or 0) * estimated_depth,
                    "reading_total_facings": r["total_facings"],
                    "reading_empty_space_pct": r["empty_space_pct"],
                    "reading_shelf_levels": r["shelf_levels_detected"],
                    "reading_linear_meters": r["linear_meters"] if "linear_meters" in r.keys() else None,
                }
            )
    return rows


def daily_metrics(point_id: str) -> list:
    with get_conn() as conn:
        readings = conn.execute(
            "SELECT r.* FROM readings r JOIN management_reading_reviews v ON v.reading_id = r.id "
            "WHERE r.point_id = ? AND v.status = 'Aprobado' ORDER BY r.id", (point_id,)
        ).fetchall()

    by_day = {}
    for r in readings:
        day = r["created_at"][:10]
        bucket = by_day.setdefault(
            day, {"date": day, "readings": 0, "facings_sum": 0, "empty_space_sum": 0.0, "empty_space_n": 0}
        )
        bucket["readings"] += 1
        bucket["facings_sum"] += r["total_facings"] or 0
        if r["empty_space_pct"] is not None:
            bucket["empty_space_sum"] += r["empty_space_pct"]
            bucket["empty_space_n"] += 1

    result = []
    for day, b in sorted(by_day.items()):
        result.append(
            {
                "date": day,
                "readings": b["readings"],
                "avg_total_facings": round(b["facings_sum"] / b["readings"], 1) if b["readings"] else None,
                "avg_empty_space_pct": round(b["empty_space_sum"] / b["empty_space_n"], 1) if b["empty_space_n"] else None,
            }
        )
    return result


def replenishment_signals(point_id: str, lookback: int = 10) -> dict:
    with get_conn() as conn:
        readings = conn.execute(
            "SELECT r.* FROM readings r JOIN management_reading_reviews v ON v.reading_id = r.id "
            "WHERE r.point_id = ? AND v.status = 'Aprobado' ORDER BY r.id DESC LIMIT ?",
            (point_id, lookback),
        ).fetchall()
    readings = list(reversed(readings))

    empty_space_trend = [
        {"date": r["created_at"][:10], "created_at": r["created_at"], "empty_space_pct": r["empty_space_pct"]}
        for r in readings
    ]
    empty_vals = [r["empty_space_pct"] for r in readings if r["empty_space_pct"] is not None]
    avg_empty = round(sum(empty_vals) / len(empty_vals), 1) if empty_vals else None
    trend_delta = None
    if len(empty_vals) >= 2:
        trend_delta = round(empty_vals[-1] - empty_vals[0], 1)

    stockout_counts = {}
    seen_counts = {}
    product_meta = {}
    for r in readings:
        products = json.loads(r["products_json"] or "[]")
        for p in products:
            key = (p.get("brand") or "").strip().lower() + "|" + (p.get("product") or "").strip().lower()
            seen_counts[key] = seen_counts.get(key, 0) + 1
            product_meta[key] = p
            if p.get("out_of_stock"):
                stockout_counts[key] = stockout_counts.get(key, 0) + 1

    recurring = []
    for key, times_out in stockout_counts.items():
        times_seen = seen_counts.get(key, 1)
        meta = product_meta[key]
        recurring.append(
            {
                "product": meta.get("product"),
                "brand": meta.get("brand"),
                "category": meta.get("category"),
                "times_out_of_stock": times_out,
                "times_seen": times_seen,
                "urgency_pct": round(times_out / times_seen * 100, 0),
            }
        )
    recurring.sort(key=lambda x: (-x["urgency_pct"], -x["times_out_of_stock"]))

    return {
        "empty_space_trend": empty_space_trend,
        "avg_empty_space_pct": avg_empty,
        "empty_space_trend_delta": trend_delta,
        "recurring_stockouts": recurring,
    }


# ---------------------------------------------------------------------------
# Planogramas: catálogo, precios y algoritmo de cumplimiento
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    if not text:
        return set()
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", text.upper())
    cleaned = re.sub(r"(\d+)(ML|GR|G|LT|CM)\b", r"\1", cleaned)  # separa "200ML" -> "200"
    tokens = {t for t in cleaned.split() if len(t) > 1}
    return tokens


def _tokens_match(ta: str, tb: str) -> bool:
    """Los planogramas abrevian mucho (ESS=Essences, SH=Shampoo, AC=Acondicionador),
    así que además de la igualdad exacta se acepta que un token sea prefijo del otro
    (con un mínimo de 3 caracteres para no hacer match de abreviaturas ambiguas)."""
    if ta == tb:
        return True
    if len(ta) >= 3 and len(tb) >= 3 and (ta.startswith(tb) or tb.startswith(ta)):
        return True
    return False


def _jaccard(a: set, b: set) -> float:
    """Similitud de tokens tolerante a abreviaturas: cuenta como 'intersección'
    los pares de tokens iguales o donde uno es prefijo del otro (greedy, sin reusar)."""
    if not a or not b:
        return 0.0
    remaining_b = set(b)
    inter = 0
    for ta in a:
        match = next((tb for tb in remaining_b if _tokens_match(ta, tb)), None)
        if match is not None:
            remaining_b.discard(match)
            inter += 1
    if not inter:
        return 0.0
    return inter / len(a | b)


def _lis_indices(seq: list) -> set:
    """Índices que forman la subsecuencia creciente más larga (permite empates).
    Lo que NO queda en el resultado está fuera de secuencia respecto al resto."""
    n = len(seq)
    if n == 0:
        return set()
    lengths = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if seq[j] <= seq[i] and lengths[j] + 1 > lengths[i]:
                lengths[i] = lengths[j] + 1
                prev[i] = j
    best_end = max(range(n), key=lambda i: lengths[i])
    result = set()
    i = best_end
    while i != -1:
        result.add(i)
        i = prev[i]
    return result


def list_planograms(owner_client: str = None, include_shared: bool = True) -> list:
    """Sin argumentos: todos (app). Con owner_client: los de ese cliente y, si include_shared,
    también los creados en la app (owner_client NULL)."""
    query = "SELECT p.*, (SELECT COUNT(*) FROM planogram_items i WHERE i.planogram_id = p.id) AS item_count FROM planograms p"
    params = []
    if owner_client is not None:
        query += " WHERE p.owner_client = ?" + (" OR p.owner_client IS NULL" if include_shared else "")
        params.append(owner_client)
    query += " ORDER BY p.name"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "module_cm": r["module_cm"],
            "bands": r["bands"],
            "item_count": r["item_count"],
            "owner_client": r["owner_client"] if "owner_client" in r.keys() else None,
        }
        for r in rows
    ]


def _planogram_item_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "order_seq": row["order_seq"],
        "section_label": row["section_label"],
        "module": row["module"],
        "band": row["band"],
        "segment": row["segment"],
        "position_in_section": row["position_in_section"],
        "title": row["title"],
        "internal_code": row["internal_code"],
        "barcode": row["barcode"],
        "expected_facings": row["expected_facings"],
        "tag": row["tag"],
        "price_clp": row["price_clp"],
        "price_source": row["price_source"] if "price_source" in row.keys() else None,
    }


def get_planogram(planogram_id: str):
    with get_conn() as conn:
        pg = conn.execute("SELECT * FROM planograms WHERE id = ?", (planogram_id,)).fetchone()
        if not pg:
            return None
        items = conn.execute(
            "SELECT * FROM planogram_items WHERE planogram_id = ? ORDER BY order_seq",
            (planogram_id,),
        ).fetchall()
        metadata = conn.execute('SELECT data_json FROM management_planograms WHERE id=?', (planogram_id,)).fetchone()
        classification = json.loads(metadata['data_json']) if metadata else {}
    return {
        "category": classification.get('category', ''),
        "subcategories": classification.get('subcategories', []),
        "id": pg["id"],
        "name": pg["name"],
        "module_cm": pg["module_cm"],
        "bands": pg["bands"],
        "source_filename": pg["source_filename"],
        "owner_client": pg["owner_client"] if "owner_client" in pg.keys() else None,
        "items": [_planogram_item_dict(r) for r in items],
    }


def update_planogram_prices(planogram_id: str, prices: dict) -> int:
    """prices: {internal_code: price_clp}. Edición manual: marca price_source='manual' para
    que el auto-completado por OCR nunca vuelva a sobrescribir este precio."""
    updated = 0
    with get_conn() as conn:
        for code, price in prices.items():
            cur = conn.execute(
                "UPDATE planogram_items SET price_clp = ?, price_source = 'manual' WHERE planogram_id = ? AND internal_code = ?",
                (price, planogram_id, str(code)),
            )
            updated += cur.rowcount
    return updated


def autofill_prices_from_ocr(planogram_id: str, item_prices: dict) -> int:
    """item_prices: {planogram_item_id: price_clp} leídos por OCR de una lectura nueva.
    Solo actualiza posiciones sin precio manual cargado (price_source != 'manual')."""
    updated = 0
    with get_conn() as conn:
        for item_id, price in item_prices.items():
            cur = conn.execute(
                "UPDATE planogram_items SET price_clp = ?, price_source = 'ocr' "
                "WHERE id = ? AND planogram_id = ? AND (price_source IS NULL OR price_source != 'manual')",
                (price, item_id, planogram_id),
            )
            updated += cur.rowcount
    return updated


def planogram_context_for_vision(planogram_id: str, planogram: dict = None) -> dict:
    """Resumen liviano del planograma para incluir en el prompt de visión."""
    pg = planogram if planogram is not None else get_planogram(planogram_id)
    if not pg:
        return None
    by_band = {}
    for it in pg["items"]:
        by_band.setdefault(it["band"], []).append(it["title"])
    return {
        "name": pg["name"],
        "module_cm": pg["module_cm"],
        "bands": pg["bands"],
        "titles_by_band": {str(b): titles for b, titles in sorted(by_band.items())},
        # caras esperadas por título (prior de posición E2: expande la secuencia esperada por caras)
        "facings_by_title": {it["title"]: int(it.get("expected_facings") or 1) for it in pg["items"] if it.get("title")},
    }


STANDARDS_WEIGHTS = {"stock": 0.35, "space": 0.25, "price": 0.20, "organization": 0.20}
STANDARDS_GRADES = [
    (90, "Excelente", "#16a34a"),
    (75, "Bueno", "#65a30d"),
    (55, "Regular", "#d97706"),
    (0, "Crítico", "#dc2626"),
]


def _grade_for_score(score: float):
    for threshold, label, color in STANDARDS_GRADES:
        if score >= threshold:
            return label, color
    return STANDARDS_GRADES[-1][1], STANDARDS_GRADES[-1][2]


def compute_shelf_standards(products: list, empty_space_pct) -> dict:
    """
    Evalúa el rendimiento de la góndola contra estándares generales de ejecución
    en punto de venta (disponibilidad, exhibición, rotulado, organización),
    sin necesitar un planograma específico cargado.
    """
    total_products = len(products)
    out_of_stock_count = sum(1 for p in products if p.get("out_of_stock"))
    stock_score = round(100 * (1 - out_of_stock_count / total_products)) if total_products else None

    space_score = None
    if empty_space_pct is not None:
        space_score = max(0, min(100, round(100 - empty_space_pct * 2)))

    price_evaluated = [p for p in products if p.get("price_tag_visible") is not None]
    price_visible_count = sum(1 for p in price_evaluated if p.get("price_tag_visible"))
    price_score = round(100 * price_visible_count / len(price_evaluated)) if price_evaluated else None

    by_level = {}
    for p in products:
        level = p.get("shelf_level")
        if level is None:
            continue
        facings = p.get("facings") or 0
        cats = by_level.setdefault(level, {})
        cats[p.get("category") or "—"] = cats.get(p.get("category") or "—", 0) + facings

    organization_score = None
    if by_level:
        level_scores = []
        level_weights = []
        for level, cats in by_level.items():
            total = sum(cats.values())
            if not total:
                continue
            dominant = max(cats.values())
            level_scores.append(dominant / total)
            level_weights.append(total)
        if level_scores:
            weighted = sum(s * w for s, w in zip(level_scores, level_weights)) / sum(level_weights)
            organization_score = round(weighted * 100)

    sub_scores = {"stock": stock_score, "space": space_score, "price": price_score, "organization": organization_score}
    available = {k: v for k, v in sub_scores.items() if v is not None}
    if available:
        weight_sum = sum(STANDARDS_WEIGHTS[k] for k in available)
        overall_score = round(sum(v * STANDARDS_WEIGHTS[k] for k, v in available.items()) / weight_sum)
    else:
        overall_score = None

    findings = []
    if out_of_stock_count:
        findings.append(f"{out_of_stock_count} producto{'s' if out_of_stock_count != 1 else ''} con quiebre de stock detectado.")
    if empty_space_pct is not None and empty_space_pct >= 15:
        findings.append(f"Espacio vacío elevado en la góndola ({empty_space_pct:.0f}%).")
    if price_score is not None and price_score < 80:
        missing = len(price_evaluated) - price_visible_count
        findings.append(f"{missing} producto{'s' if missing != 1 else ''} sin rótulo de precio visible.")
    if organization_score is not None and organization_score < 70:
        findings.append("Categorías mezcladas entre niveles — considera agrupar por categoría.")
    if not findings and overall_score is not None:
        findings.append("Sin hallazgos relevantes — la góndola cumple los estándares generales de ejecución.")

    grade_label, grade_color = (None, None)
    if overall_score is not None:
        grade_label, grade_color = _grade_for_score(overall_score)
    from settings_service import score_band
    band = score_band(overall_score)
    if band:
        grade_color = {'bad': '#dc2626', 'warn': '#d97706', 'ok': '#16a34a'}[band]

    return {
        "overall_score": overall_score,
        "grade": grade_label,
        "grade_color": grade_color,
        "score_band": band,
        "stock_score": stock_score,
        "space_score": space_score,
        "price_score": price_score,
        "organization_score": organization_score,
        "out_of_stock_count": out_of_stock_count,
        "total_products": total_products,
        "price_tag_evaluated": len(price_evaluated),
        "price_tag_visible_count": price_visible_count,
        "findings": findings,
    }


def compute_planogram_compliance(planogram_id: str, products: list, planogram: dict = None) -> dict:
    """
    Compara los productos detectados por la IA contra las posiciones esperadas del
    planograma asignado a este punto. Algoritmo:

    1. Cada producto detectado se compara (similitud de tokens del nombre/marca) contra
       las posiciones del planograma, priorizando las de su mismo nivel/banda detectado.
    2. Se asigna en forma greedy (mayor puntaje primero) 1 producto <-> 1 posición.
    3. Cada posición asignada compara caras detectadas vs. esperadas -> ok / low / missing.
    4. Un "quiebre" (hueco vacío marcado por la IA) fuerza caras detectadas = 0 aunque
       la IA haya reportado un número, porque el hueco es evidencia directa de faltante.
    5. % de cumplimiento = caras cubiertas / caras esperadas totales (no solo presencia).
    6. Impacto en $ = unidades faltantes * precio (cuando el precio fue cargado).
    7. Los productos TOP / LANZAMIENTO en falta se marcan como prioridad.
    8. Productos detectados que no calzan con ninguna posición del planograma se listan
       como "fuera de planograma" (posible mal ubicado o ajeno a esta góndola).
    """
    pg = planogram if planogram is not None else get_planogram(planogram_id)
    if not pg or not pg["items"]:
        return None

    items = pg["items"]
    item_tokens = [_tokenize(it["title"]) for it in items]

    prod_tokens = []
    for p in products:
        name = f"{p.get('product') or ''} {p.get('brand') or ''}"
        prod_tokens.append(_tokenize(name))

    pairs = []
    for pi, p in enumerate(products):
        shelf_level = p.get("shelf_level")
        for ii, it in enumerate(items):
            score = _jaccard(prod_tokens[pi], item_tokens[ii])
            if score <= 0:
                continue
            same_band = shelf_level is not None and shelf_level == it["band"]
            combined = score if same_band else score * 0.7
            pairs.append((combined, score, pi, ii))

    pairs.sort(key=lambda x: -x[0])
    matched_item_for_product = {}
    matched_product_for_item = {}
    best_score_for_product = {}
    for combined, raw_score, pi, ii in pairs:
        best_score_for_product[pi] = max(best_score_for_product.get(pi, 0.0), raw_score)
        if combined < MATCH_THRESHOLD:
            continue
        if pi in matched_item_for_product or ii in matched_product_for_item:
            continue
        matched_item_for_product[pi] = ii
        matched_product_for_item[ii] = pi

    # Segunda pasada: productos detectados que NO calzaron con ninguna posición pueden ser
    # el MISMO producto ya asignado, detectado una segunda vez (aparece dos veces en la
    # percha, o quedó dividido entre fotos superpuestas). En vez de contarlos como "fuera de
    # planograma", se suman sus caras a la posición ya asignada.
    duplicate_of_item = {}
    extra_facings_for_item = {}
    extra_units_for_item = {}
    for pi in range(len(products)):
        if pi in matched_item_for_product:
            continue
        best_ii, best_dup_score = None, 0.0
        for ii, matched_pi in matched_product_for_item.items():
            score = _jaccard(prod_tokens[pi], prod_tokens[matched_pi])
            if score > best_dup_score:
                best_dup_score, best_ii = score, ii
        if best_ii is not None and best_dup_score >= DUPLICATE_THRESHOLD:
            duplicate_of_item[pi] = best_ii
            p = products[pi]
            facings = 0 if p.get("out_of_stock") else (p.get("facings") or 0)
            extra_facings_for_item[best_ii] = extra_facings_for_item.get(best_ii, 0) + facings
            extra_units_for_item[best_ii] = extra_units_for_item.get(best_ii, 0) + facings * (p.get("estimated_depth") or 1)

    item_results = []
    total_expected = 0
    total_filled = 0
    total_impact_clp = 0.0
    items_missing_price = 0
    price_tag_ok_count = 0
    price_tag_total_count = 0
    missing_price_tags = []
    total_inventory_value_clp = 0.0
    inventory_items_missing_price = 0
    product_annotations = {}
    for ii, it in enumerate(items):
        expected = it["expected_facings"] or 0
        total_expected += expected
        pi = matched_product_for_item.get(ii)
        primary_facings = 0
        primary_units = 0
        price_tag_visible = None
        price_tag_value = None
        uncertain = False
        if pi is not None:
            p = products[pi]
            primary_facings = 0 if p.get("out_of_stock") else (p.get("facings") or 0)
            primary_units = primary_facings * (p.get("estimated_depth") or 1)
            price_tag_visible = p.get("price_tag_visible")
            price_tag_value = p.get("price_tag_value")
            # el motor no da por seguro este conteo (recorte dudoso o vecino sin identificar): se confirma en /revision
            uncertain = bool(p.get("needs_review") or p.get("count_uncertain"))
        detected_facings = primary_facings + extra_facings_for_item.get(ii, 0)
        detected_units = primary_units + extra_units_for_item.get(ii, 0)
        filled = min(detected_facings, expected)
        total_filled += filled
        deficit = max(0, expected - detected_facings)
        if detected_facings >= expected and expected > 0:
            status = "ok"
        elif detected_facings > 0:
            status = "low"
        else:
            status = "missing"
        deficit_value = None
        if deficit > 0:
            if it["price_clp"] is not None:
                deficit_value = round(deficit * it["price_clp"], 0)
                total_impact_clp += deficit_value
            else:
                items_missing_price += 1
        if detected_units > 0:
            if it["price_clp"] is not None:
                total_inventory_value_clp += detected_units * it["price_clp"]
            else:
                inventory_items_missing_price += 1
        if price_tag_visible is not None:
            price_tag_total_count += 1
            if price_tag_visible:
                price_tag_ok_count += 1
            else:
                missing_price_tags.append({
                    "title": it["title"], "band": it["band"], "position_in_section": it["position_in_section"],
                    "tag": it["tag"],
                })
        item_results.append({
            "planogram_item_id": it["id"],
            "title": it["title"],
            "uncertain": uncertain,
            "section_label": it["section_label"],
            "band": it["band"],
            "position_in_section": it["position_in_section"],
            "tag": it["tag"],
            "price_tag_value": price_tag_value,
            "expected_facings": expected,
            "detected_facings": detected_facings,
            "status": status,
            "deficit": deficit,
            "price_clp": it["price_clp"],
            "deficit_value_clp": deficit_value,
            "orden_incorrecto": False,
            "price_tag_visible": price_tag_visible,
        })
        if pi is not None:
            product_annotations[pi] = {
                "planogram_status": status, "planogram_tag": it["tag"], "planogram_foreign": False,
                "planogram_item_id": it["id"],
            }
        for dup_pi, dup_ii in duplicate_of_item.items():
            if dup_ii == ii:
                product_annotations[dup_pi] = {
                    "planogram_status": status, "planogram_tag": it["tag"], "planogram_foreign": False,
                    "planogram_item_id": it["id"],
                }

    # Verificación de SECUENCIA dentro de cada nivel: el planograma manda un orden
    # izquierda->derecha específico. Un producto puede estar presente y con caras
    # suficientes (status "ok") pero en la posición equivocada del nivel — eso no lo
    # detecta el matching por nombre/nivel, así que se revisa aparte con la secuencia
    # de "position_index" (orden real detectado por la IA) contra "order_seq" del
    # planograma (orden real esperado), usando la subsecuencia creciente más larga:
    # todo lo que no forma parte de esa subsecuencia está fuera de secuencia.
    misplaced_items = []
    by_band = {}
    for ii, it in enumerate(items):
        pi = matched_product_for_item.get(ii)
        if pi is None:
            continue
        detected_pos = products[pi].get("position_index")
        if detected_pos is None:
            continue
        by_band.setdefault(it["band"], []).append((it["order_seq"], ii, detected_pos))

    for band, entries in by_band.items():
        entries.sort(key=lambda e: e[0])
        seq = [e[2] for e in entries]
        in_order = _lis_indices(seq)
        for idx, (_, ii, detected_pos) in enumerate(entries):
            if idx not in in_order:
                item_results[ii]["orden_incorrecto"] = True
                misplaced_items.append({
                    "title": items[ii]["title"],
                    "section_label": items[ii]["section_label"],
                    "band": items[ii]["band"],
                    "position_in_section": items[ii]["position_in_section"],
                    "tag": items[ii]["tag"],
                })

    foreign_products = []
    for pi, p in enumerate(products):
        if pi in matched_item_for_product or pi in duplicate_of_item:
            continue
        best = best_score_for_product.get(pi, 0.0)
        confidence = "alta" if best < FOREIGN_THRESHOLD else "media"
        foreign_products.append({
            "product": p.get("product"),
            "brand": p.get("brand"),
            "shelf_level": p.get("shelf_level"),
            "facings": p.get("facings"),
            "confidence_fuera_de_planograma": confidence,
        })
        product_annotations[pi] = {"planogram_status": "foreign", "planogram_tag": None, "planogram_foreign": True, "planogram_item_id": None}

    tag_rank = {"TOP": 0, "LANZAMIENTO": 0}
    replenishment = [r for r in item_results if r["status"] in ("missing", "low")]
    replenishment.sort(key=lambda r: (tag_rank.get(r["tag"], 1), -r["deficit"]))

    priority_breaches = [r for r in item_results if r["tag"] and r["status"] != "ok"]

    band_breakdown = {}
    for r in item_results:
        b = band_breakdown.setdefault(r["band"], {"expected": 0, "filled": 0})
        b["expected"] += r["expected_facings"]
        b["filled"] += min(r["detected_facings"], r["expected_facings"])
    band_summary = [
        {
            "band": b,
            "compliance_pct": round(v["filled"] / v["expected"] * 100, 1) if v["expected"] else None,
        }
        for b, v in sorted(band_breakdown.items())
    ]

    compliance_pct = round(total_filled / total_expected * 100, 1) if total_expected else None
    price_tag_compliance_pct = (
        round(price_tag_ok_count / price_tag_total_count * 100, 1) if price_tag_total_count else None
    )

    return {
        "planogram_id": planogram_id,
        "planogram_name": pg["name"],
        "compliance_pct": compliance_pct,
        "total_expected_facings": total_expected,
        "total_filled_facings": total_filled,
        "impact_clp": round(total_impact_clp, 0) if total_impact_clp else 0,
        "items_missing_price": items_missing_price,
        "items": item_results,
        "replenishment": replenishment,
        "priority_breaches": priority_breaches,
        "foreign_products": foreign_products,
        "band_summary": band_summary,
        "misplaced_items": misplaced_items,
        "price_tag_compliance_pct": price_tag_compliance_pct,
        "price_tag_target_pct": PRICE_TAG_TARGET_PCT,
        "price_tag_evaluated": price_tag_total_count,
        "missing_price_tags": missing_price_tags,
        "inventory_value_clp": round(total_inventory_value_clp, 0) if total_inventory_value_clp else 0,
        "inventory_items_missing_price": inventory_items_missing_price,
        "product_annotations": [product_annotations.get(pi, {"planogram_status": None, "planogram_tag": None, "planogram_foreign": False, "planogram_item_id": None}) for pi in range(len(products))],
    }


# ---------------------------------------------------------------------------
# Solicitudes de reposición / ajustes por robo, y quiebres de proveedor
# ---------------------------------------------------------------------------

def create_stock_action(
    point_id: str,
    planogram_item_id: int,
    product_title: str,
    action_type: str,
    quantity: int,
    note: str,
    created_by: str,
) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO stock_actions (point_id, planogram_item_id, product_title, action_type, "
            "quantity, note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (point_id, planogram_item_id, product_title, action_type, quantity, note, created_by, now_iso()),
        )
        action_id = cur.lastrowid
        row = conn.execute("SELECT * FROM stock_actions WHERE id = ?", (action_id,)).fetchone()
    return dict(row)


def list_stock_actions(point_id: str, include_resolved: bool = False) -> list:
    with get_conn() as conn:
        if include_resolved:
            rows = conn.execute(
                "SELECT * FROM stock_actions WHERE point_id = ? ORDER BY id DESC", (point_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM stock_actions WHERE point_id = ? AND resolved_at IS NULL ORDER BY id DESC",
                (point_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def resolve_stock_action(action_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE stock_actions SET resolved_at = ? WHERE id = ?", (now_iso(), action_id))


def delete_stock_action(action_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM stock_actions WHERE id = ?", (action_id,))


def create_supplier_stockout(
    point_id: str, planogram_item_id: int, product_title: str, note: str, created_by: str
) -> dict:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM supplier_stockouts WHERE point_id = ? AND planogram_item_id = ? AND resolved_at IS NULL",
            (point_id, planogram_item_id),
        ).fetchone()
        if existing:
            return dict(existing)
        cur = conn.execute(
            "INSERT INTO supplier_stockouts (point_id, planogram_item_id, product_title, note, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (point_id, planogram_item_id, product_title, note, created_by, now_iso()),
        )
        row = conn.execute("SELECT * FROM supplier_stockouts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_supplier_stockouts(point_id: str = None, include_resolved: bool = False, store_id: str = None) -> list:
    with get_conn() as conn:
        query = "SELECT s.*, p.name AS point_name FROM supplier_stockouts s JOIN points p ON p.id = s.point_id WHERE 1=1"
        params = []
        if point_id:
            query += " AND s.point_id = ?"
            params.append(point_id)
        if store_id is not None:
            where, scope_params = _scope_where(store_id, "p.store_id")
            query += " AND " + where
            params.extend(scope_params)
        if not include_resolved:
            query += " AND s.resolved_at IS NULL"
        query += " ORDER BY s.id DESC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def resolve_supplier_stockout(stockout_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE supplier_stockouts SET resolved_at = ? WHERE id = ?", (now_iso(), stockout_id))


# ---------------------------------------------------------------------------
# Panel de supervisión: resumen por góndola, tendencias por SKU y catálogo oficial
# ---------------------------------------------------------------------------

# Raíz de los catálogos reales (data/catalogo/<categoria>/{catalogo.json, images/}).
CATALOG_ROOT = Path(os.environ.get("CATALOG_ROOT", Path(__file__).resolve().parents[2] / "data" / "catalogo"))
_CATALOG_CACHE = {}
_CATEGORY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_STORE_SEP_RE = re.compile(r"\s+(?:·|-|—|–|/|\|)\s+")


def split_store_gondola(name: str, store_id: str = None, gondola_id: str = None) -> tuple:
    """(local, góndola) de un punto. Si el punto trae store_id/gondola_id (API v1 o usuario de tienda) se usan; si no,
    el nombre se parte en el primer separador ' · ', ' - ', ' / ' o ' | ' (p. ej. 'Local 123 Providencia · Salud sexual')."""
    name = (name or "").strip()
    if store_id:
        return store_id, (gondola_id or name)
    parts = _STORE_SEP_RE.split(name, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return name, (gondola_id or "")


def point_store_fields(name: str, store_id: str = None, gondola_id: str = None, names: dict = None) -> dict:
    """Local y góndola de un punto para el panel: store_id (clave real, puede ser None en puntos antiguos),
    store_name (nombre conocido por los usuarios del local, o el prefijo del nombre), store_key (clave de agrupación:
    store_id, o el prefijo si no hay store_id) y gondola (gondola_id o el resto del nombre)."""
    name = (name or "").strip()
    parts = _STORE_SEP_RE.split(name, maxsplit=1)
    prefix, rest = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, name)
    if store_id:
        store_name = (names or {}).get(store_id) or prefix or store_id
        store_key = store_id
    else:
        store_name = prefix
        store_key = prefix or ""
    gondola = rest if (prefix and rest) else (gondola_id or name)  # "Local · Góndola 2" -> "Góndola 2"; sin prefijo, el id de góndola
    return {"store_id": store_id, "store_name": store_name, "store": store_name or store_id or "",
            "store_key": store_key, "gondola": gondola}


def _reading_brief(r: dict) -> dict:
    """Resumen liviano de una lectura ya expandida por _reading_dict (para listas y series)."""
    c = r.get("compliance") or {}
    items = c.get("items") or []
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "date": r["created_at"][:10],
        "review_status": r["review"]["status"],
        "planogram_id": r.get("planogram_id"),
        "compliance_pct": c.get("compliance_pct"),
        "total_facings": r.get("total_facings") or 0,
        "needs_review": r.get("needs_review") or 0,
        "missing": sum(1 for it in items if it.get("status") == "missing"),
        "low": sum(1 for it in items if it.get("status") == "low"),
        "foreign": len(c.get("foreign_products") or []),
        "impact_clp": c.get("impact_clp") or 0,
        "empty_space_pct": r.get("empty_space_pct"),
        "image_url": (r.get("image_urls") or [None])[0],
    }


def panel_summary(days: int = 7, store_id: str = None, captured_by=None) -> dict:
    """Una fila por punto con su última lectura (cumplimiento, caras, por revisar, quiebres), totales del período y
    agrupación por local. store_id: solo los puntos de ese local (rol tienda)."""
    from datetime import timedelta

    days = max(1, min(int(days or 7), 365))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows_out = []
    names = store_names()
    with get_conn() as conn:
        where, params = _scope_where(store_id)
        points = conn.execute(f"SELECT * FROM points WHERE {where} ORDER BY id", params).fetchall()
        for p in points:
            keys = p.keys()
            where, params = _reading_where(p["id"], captured_by)
            latest_row = conn.execute(
                f"SELECT * FROM readings WHERE {where} ORDER BY id DESC LIMIT 1", params
            ).fetchone()
            n_total = conn.execute(f"SELECT COUNT(*) AS c FROM readings WHERE {where}", params).fetchone()["c"]
            n_period = conn.execute(
                f"SELECT COUNT(*) AS c FROM readings WHERE {where} AND created_at >= ?", (*params, cutoff)
            ).fetchone()["c"]
            approved_where = f"{where} AND r.created_at >= ? AND v.status = 'Aprobado'"
            performance = conn.execute(
                "SELECT r.* FROM readings r JOIN management_reading_reviews v ON v.reading_id = r.id "
                f"WHERE {approved_where} ORDER BY r.id DESC LIMIT 1", (*params, cutoff)
            ).fetchone()
            n_approved = conn.execute(
                "SELECT COUNT(*) AS c FROM readings r JOIN management_reading_reviews v ON v.reading_id = r.id "
                f"WHERE {approved_where}", (*params, cutoff)
            ).fetchone()["c"]
            p_store_id = p["store_id"] if "store_id" in keys else None
            gondola_id = p["gondola_id"] if "gondola_id" in keys else None
            sf = point_store_fields(p["name"], p_store_id, gondola_id, names)
            planogram_id = p["planogram_id"] if "planogram_id" in keys else None
            rows_out.append({
                "id": p["id"],
                "name": p["name"],
                "store": sf["store"],
                "store_name": sf["store_name"],
                "store_key": sf["store_key"],
                "gondola": sf["gondola"],
                "store_id": p_store_id,
                "gondola_id": gondola_id,
                "planogram_id": planogram_id,
                "planogram_name": _point_planogram_name(conn, planogram_id),
                "readings_count": n_total,
                "readings_in_period": n_period,
                "approved_readings_in_period": n_approved,
                "measured_in_period": n_approved > 0,
                "last": latest_row,
                "performance": performance,
            })
    # _reading_dict may open its own connection (planogram compliance), so it runs after this one is released.
    for r in rows_out:
        r["last"] = _reading_brief(_reading_dict(r["last"])) if r["last"] else None
        r["performance"] = _reading_brief(_reading_dict(r["performance"])) if r["performance"] else None

    with_last = [r for r in rows_out if r["last"]]
    performance_rows = [r["performance"] for r in rows_out if r["performance"]]
    period_pct = [r["compliance_pct"] for r in performance_rows if r["compliance_pct"] is not None]
    totals = {
        "points": len(rows_out),
        "points_with_planogram": sum(1 for r in rows_out if r["planogram_id"]),
        "points_measured_in_period": sum(1 for r in rows_out if r["measured_in_period"]),
        "readings_in_period": sum(r["readings_in_period"] for r in rows_out),
        "approved_readings_in_period": sum(r["approved_readings_in_period"] for r in rows_out),
        "avg_compliance_pct": round(sum(period_pct) / len(period_pct), 1) if period_pct else None,
        "avg_compliance_pct_period": round(sum(period_pct) / len(period_pct), 1) if period_pct else None,
        "total_needs_review": sum(r["last"]["needs_review"] for r in with_last if r["last"]["review_status"] == "En revisión"),
        "total_missing": sum(r["missing"] for r in performance_rows),
        "total_low": sum(r["low"] for r in performance_rows),
        "impact_clp": round(sum(r["impact_clp"] for r in performance_rows), 0),
    }
    groups = {}
    for r in rows_out:
        g = groups.setdefault(r["store_key"], {
            "store_id": r["store_id"], "store_name": r["store_name"], "label": r["store"] or "(sin local)",
            "key": r["store_key"], "points": 0, "points_with_planogram": 0, "points_measured_in_period": 0,
            "readings_in_period": 0, "_pcts": [], "total_missing": 0, "total_low": 0, "total_needs_review": 0,
            "last_reading_at": None,
        })
        g["points"] += 1
        g["points_with_planogram"] += 1 if r["planogram_id"] else 0
        g["points_measured_in_period"] += 1 if r["measured_in_period"] else 0
        g["readings_in_period"] += r["readings_in_period"]
        if r["performance"]:
            if r["performance"]["compliance_pct"] is not None:
                g["_pcts"].append(r["performance"]["compliance_pct"])
            g["total_missing"] += r["performance"]["missing"]
            g["total_low"] += r["performance"]["low"]
        if r["last"]:
            if r["last"]["review_status"] == "En revisión":
                g["total_needs_review"] += r["last"]["needs_review"]
            if not g["last_reading_at"] or r["last"]["created_at"] > g["last_reading_at"]:
                g["last_reading_at"] = r["last"]["created_at"]
    stores = []
    for g in groups.values():
        pcts = g.pop("_pcts")
        g["avg_compliance_pct"] = round(sum(pcts) / len(pcts), 1) if pcts else None
        stores.append(g)
    stores.sort(key=lambda g: (g["avg_compliance_pct"] is None, g["avg_compliance_pct"] if g["avg_compliance_pct"] is not None else 0, g["label"]))
    from settings_service import display_parameters, indicator
    kpis = display_parameters()['kpiParameters']
    coverage = round(100 * totals['points_measured_in_period'] / totals['points'], 1) if totals['points'] else None
    return {
        "indicators": {'coverage': indicator('coverage', coverage, kpis),
                       'cp': indicator('cp', totals['avg_compliance_pct'], kpis)},
        "days": days,
        "generated_at": now_iso(),
        "store_id": store_id,
        "stores": stores,
        "totals": totals,
        "points": rows_out,
    }


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _trend_flag(values: list, dates: list, expected: int) -> dict:
    """Bandera simple de tendencia de una serie de caras por lectura (None = sin dato en esa lectura):
    'quiebre' (última = 0), 'baja N semanas|lecturas' (N caídas consecutivas al final), 'bajo esperado',
    'sube', 'estable' o 'sin datos'."""
    known = [(d, v) for d, v in zip(dates, values) if v is not None]
    if not known:
        return {"flag": "sin datos", "flag_kind": "none", "last": None, "delta": None}
    last = known[-1][1]
    delta = (last - known[-2][1]) if len(known) >= 2 else None
    if last == 0:
        n0 = 0
        for _d, v in reversed(known):
            if v == 0:
                n0 += 1
            else:
                break
        label = "quiebre" if n0 <= 1 else f"quiebre ({n0} lecturas)"
        return {"flag": label, "flag_kind": "quiebre", "last": last, "delta": delta}
    steps = 0
    for i in range(len(known) - 1, 0, -1):
        if known[i][1] < known[i - 1][1]:
            steps += 1
        else:
            break
    if steps >= 1 and (steps >= 2 or last < (expected or 0)):
        d_first, d_last = _parse_iso(known[-1 - steps][0]), _parse_iso(known[-1][0])
        span_days = (d_last - d_first).days if d_first and d_last else 0
        unit = "semanas" if span_days >= 5 * steps else "lecturas"
        return {"flag": f"baja {steps} {unit}", "flag_kind": "baja", "last": last, "delta": delta}
    if expected and last < expected:
        return {"flag": "bajo esperado", "flag_kind": "bajo", "last": last, "delta": delta}
    if delta is not None and delta > 0:
        return {"flag": "sube", "flag_kind": "sube", "last": last, "delta": delta}
    return {"flag": "estable", "flag_kind": "estable", "last": last, "delta": delta}


def point_trends(point_id: str, limit: int = 12) -> dict:
    """Serie de las últimas `limit` lecturas del punto (cumplimiento, caras, por revisar, quiebres) y, por cada
    posición del planograma asignado, las caras detectadas en cada lectura con su bandera de tendencia."""
    limit = max(1, min(int(limit or 12), 100))
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM points WHERE id = ?", (point_id,)).fetchone()
        if not p:
            return None
        rows = conn.execute(
            "SELECT r.* FROM readings r JOIN management_reading_reviews v ON v.reading_id = r.id "
            "WHERE r.point_id = ? AND v.status = 'Aprobado' ORDER BY r.id DESC LIMIT ?", (point_id, limit)
        ).fetchall()
        planogram_id = p["planogram_id"] if "planogram_id" in p.keys() else None
        planogram_name = _point_planogram_name(conn, planogram_id)
    readings = [_reading_dict(r) for r in reversed(rows)]
    series = [_reading_brief(r) for r in readings]
    dates = [r["created_at"] for r in readings]
    per_reading = []
    for r in readings:
        c = r.get("compliance")
        if c and c.get("planogram_id") == planogram_id:
            per_reading.append({it["planogram_item_id"]: it for it in c.get("items") or []})
        else:
            per_reading.append(None)
    skus = []
    pg = get_planogram(planogram_id) if planogram_id else None
    for it in (pg["items"] if pg else []):
        vals = []
        for m in per_reading:
            hit = m.get(it["id"]) if m else None
            vals.append(hit["detected_facings"] if hit else None)
        flag = _trend_flag(vals, dates, it["expected_facings"] or 0)
        skus.append({
            "planogram_item_id": it["id"],
            "title": it["title"],
            "band": it["band"],
            "position_in_section": it["position_in_section"],
            "section_label": it["section_label"],
            "tag": it["tag"],
            "expected_facings": it["expected_facings"],
            "price_clp": it["price_clp"],
            "series": vals,
            **flag,
        })
    flag_counts = {}
    for s in skus:
        flag_counts[s["flag_kind"]] = flag_counts.get(s["flag_kind"], 0) + 1
    return {
        "point_id": p["id"],
        "point_name": p["name"],
        "planogram_id": planogram_id,
        "planogram_name": planogram_name,
        "limit": limit,
        "readings": series,
        "skus": skus,
        "flag_counts": flag_counts,
    }


def catalog_image_dirs() -> list:
    """[(categoria, ruta de images/)] de los catálogos reales presentes en disco (solo carpetas existentes)."""
    out = []
    if not CATALOG_ROOT.is_dir():
        return out
    for d in sorted(CATALOG_ROOT.iterdir()):
        if d.is_dir() and _CATEGORY_RE.match(d.name) and (d / "catalogo.json").exists() and (d / "images").is_dir():
            out.append((d.name, d / "images"))
    return out


def load_catalogs() -> list:
    """[(categoria, [entradas de catalogo.json])], releído cuando cambia el archivo."""
    out = []
    if not CATALOG_ROOT.is_dir():
        return out
    for d in sorted(CATALOG_ROOT.iterdir()):
        f = d / "catalogo.json"
        if not (d.is_dir() and _CATEGORY_RE.match(d.name) and f.exists()):
            continue
        try:
            mtime = f.stat().st_mtime
            cached = _CATALOG_CACHE.get(d.name)
            if not cached or cached[0] != mtime:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = data.get("items") or data.get("products") or []
                _CATALOG_CACHE[d.name] = (mtime, [e for e in data if isinstance(e, dict)])
            out.append((d.name, _CATALOG_CACHE[d.name][1]))
        except Exception as exc:
            print(f"[catalogo] no se pudo leer {f}: {exc}", flush=True)
    return out


def _catalog_entry_public(category: str, e: dict) -> dict:
    urls = []
    for rel in e.get("images_local") or []:
        rel = str(rel)
        if rel.startswith("images/") and "/" not in rel[len("images/"):] and ".." not in rel:
            urls.append(f"/catalog-images/{category}/{rel[len('images/'):]}")
    return {
        "category": category,
        "sku_web": e.get("sku_web"),
        "title_web": e.get("title_web"),
        "brand": e.get("brand"),
        "price_clp": e.get("price_clp"),
        "price_normal_clp": e.get("price_normal_clp"),
        "url": e.get("url"),
        "formato": e.get("formato"),
        "gtin": e.get("gtin"),
        "availability": e.get("availability"),
        "match_method": e.get("match_method"),
        "images": urls,
        "image": urls[0] if urls else None,
    }


def catalog_for_planogram(planogram_id: str, point_id: str = None) -> dict:
    """Posiciones del planograma cruzadas con el catálogo real (internal_code == sku_web, o título del planograma)
    y, si se indica un punto, lo último observado por la cámara en ese punto (caras, estado, recortes)."""
    pg = get_planogram(planogram_id)
    if not pg:
        return None
    titles = {it["title"] for it in pg["items"]}
    by_code, by_title, categories = {}, {}, []
    for category, entries in load_catalogs():
        if not any(e.get("planogram_title") in titles for e in entries):
            continue
        categories.append(category)
        for e in entries:
            if e.get("sku_web") is not None:
                by_code.setdefault(str(e["sku_web"]), (category, e))
            if e.get("planogram_title"):
                by_title.setdefault(e["planogram_title"], (category, e))

    observed_by_item, point_info = {}, None
    if point_id:
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM points WHERE id = ?", (point_id,)).fetchone()
            latest_row = conn.execute(
                "SELECT * FROM readings WHERE point_id = ? ORDER BY id DESC LIMIT 1", (point_id,)
            ).fetchone() if p else None
        if p:
            point_info = {"id": p["id"], "name": p["name"], "reading_id": None, "created_at": None, "planogram_id": None}
        if latest_row:
            r = _reading_dict(latest_row)
            c = r.get("compliance") or {}
            point_info.update({"reading_id": r["id"], "created_at": r["created_at"], "planogram_id": r.get("planogram_id")})
            if c.get("planogram_id") == planogram_id:
                for it in c.get("items") or []:
                    observed_by_item[it["planogram_item_id"]] = {
                        "reading_id": r["id"], "detected_facings": it["detected_facings"], "status": it["status"],
                        "deficit": it["deficit"], "uncertain": it["uncertain"], "orden_incorrecto": it.get("orden_incorrecto"),
                        "price_tag_value": it.get("price_tag_value"), "crops": [],
                    }
                for prod, ann in zip(r.get("products") or [], c.get("product_annotations") or []):
                    iid = ann.get("planogram_item_id")
                    if iid in observed_by_item and prod.get("item_index") is not None and prod.get("image_index") is not None:
                        observed_by_item[iid]["crops"].append({
                            "reading_id": r["id"], "image_index": prod["image_index"], "item_index": prod["item_index"],
                            "crop_url": f"/api/readings/{r['id']}/crops/{prod['image_index']}/{prod['item_index']}.jpg",
                            "confidence": prod.get("confidence"), "source": prod.get("source"),
                            "needs_review": bool(prod.get("needs_review")), "facings": prod.get("facings"),
                            "ocr_text": (prod.get("ocr_text") or "")[:80],
                        })

    items = []
    n_catalog = n_image = 0
    for it in pg["items"]:
        hit = by_code.get(str(it["internal_code"])) if it.get("internal_code") else None
        if hit is None:
            hit = by_title.get(it["title"])
        cat = _catalog_entry_public(hit[0], hit[1]) if hit else None
        if cat:
            n_catalog += 1
            if cat["image"]:
                n_image += 1
        items.append({
            "planogram_item_id": it["id"],
            "title": it["title"],
            "internal_code": it["internal_code"],
            "barcode": it["barcode"],
            "band": it["band"],
            "position_in_section": it["position_in_section"],
            "section_label": it["section_label"],
            "order_seq": it["order_seq"],
            "tag": it["tag"],
            "expected_facings": it["expected_facings"],
            "price_clp": it["price_clp"] if it["price_clp"] is not None else (cat["price_clp"] if cat else None),
            "price_source": it["price_source"] if it["price_clp"] is not None else ("catalogo" if cat and cat["price_clp"] is not None else None),
            "catalog": cat,
            "observed": observed_by_item.get(it["id"]),
        })
    return {
        "planogram": {"id": pg["id"], "name": pg["name"], "bands": pg["bands"], "module_cm": pg["module_cm"]},
        "point": point_info,
        "catalog_categories": categories,
        "coverage": {"items": len(items), "with_catalog": n_catalog, "with_image": n_image,
                     "observed": len(observed_by_item)},
        "items": items,
    }
