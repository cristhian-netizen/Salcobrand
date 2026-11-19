"""One-shot wipe of operational (test) data so the pilot restarts with real photos.

Trigger: MAINTENANCE_WIPE_OPERATIONAL=<token> in the environment, checked once at API startup
(db.init_db, roles 'api'/'all'; the worker never wipes). When the token differs from the one
recorded in meta.operational_wipe_token, every measurement and everything derived from it is
deleted in ONE transaction, the counts per table are logged with a [maintenance] prefix and the
token is recorded, so restarts and redeploys with the same value never wipe again. Then the
photo/cache folders under DATA_DIR are emptied. Master data is untouched: accounts and people,
stores and points, infrastructure, the product master (photos are data URIs inside data_json),
planograms, settings, integrations, capture links, the Kilby product-sync state, plan scopes
and the activity log. No endpoint and no UI: only the environment variable.
"""
import os
import shutil
import sqlite3

import db

ENV_VAR = "MAINTENANCE_WIPE_OPERATIONAL"
TOKEN_KEY = "operational_wipe_token"
REPORT_KEY = "operational_wipe_report"

# Operational data, children before parents: the tables hanging off readings first, then the
# job/photo-session tables, then readings and captures themselves. Together with KEEP_TABLES
# this covers every table in pgcompat.TABLE_ORDER (the tests assert the partition), so a new
# table cannot ship without being classified here.
WIPE_TABLES = (
    "management_reading_alerts",
    "management_reading_reviews",
    "management_reading_details",
    "management_training_suggestions",
    "management_training_labels",    # their crops (uploads/_training) go with the files below
    "management_kilby_trainings",    # trainings started from test labels; models stay in Kilby
    "shadow_runs",
    "management_capture_requests",   # photo-session dedupe; the capture LINKS are kept
    "api_jobs",
    "stock_actions",
    "supplier_stockouts",
    "readings",
    "captures",
)
# Master data that must survive, including management_kilby_products: the synced-state of the
# product outbox keeps this system consistent with what Kilby already received.
KEEP_TABLES = (
    "points", "users", "planograms", "planogram_items", "capture_links",
    "management_clients", "management_people", "management_settings", "management_catalog_state",
    "management_products", "management_planograms", "management_stores", "management_shelf_types",
    "management_assignments", "management_instances", "management_events",
    "management_plan_scope_state", "management_plan_scopes", "management_integrations",
    "management_kilby_products",
    # Dataset sweeps are valuable raw data (original nationwide photos): rows and files survive.
    "management_dataset_images",
)
# pgcompat.SERIAL_TABLES minus planogram_items (kept): the ids of wiped tables restart from 1,
# the same way migrate_from_sqlite leaves the sequences of the rows it copies.
RESET_SEQUENCES = ("readings", "stock_actions", "supplier_stockouts", "shadow_runs", "captures")
# DATA_DIR folders holding only operational files: uploads (storage.LOCAL_DIR: reading photos,
# capturas/, vivo/ and the _training/ crops), kilby-crops (kilby_model) and thumbs (image_cache).
# The folders themselves stay; data.db, secret.key and registration_code are never touched.
# dataset/ (dataset_api originals) must NEVER be listed here: it mirrors KEEP_TABLES above.
WIPE_DIRS = ("uploads", "kilby-crops", "thumbs")


def wipe_if_requested():
    """Run the one-shot wipe when MAINTENANCE_WIPE_OPERATIONAL carries a token not yet applied."""
    token = os.environ.get(ENV_VAR, "").strip()
    if not token:
        return None
    counts = _wipe_tables(token)
    if counts is None:
        print(f"[maintenance] operational wipe already applied for this {ENV_VAR} value; nothing to do", flush=True)
        return None
    files = _clear_directories()
    print("[maintenance] operational wipe: " + " ".join(f"{table}={counts[table]}" for table in WIPE_TABLES), flush=True)
    print("[maintenance] files removed: " + " ".join(f"{name}={files[name]}" for name in WIPE_DIRS), flush=True)
    print(f"[maintenance] token recorded in meta.{TOKEN_KEY}: restarts with the same value never wipe again", flush=True)
    return {"tables": counts, "files": files}


def _wipe_tables(token: str):
    """Delete the operational rows and record the token, all in one transaction.
    Returns the counts per table, or None when this token was already applied."""
    with db.get_conn() as conn:
        if db.USE_PG:
            conn.execute("SELECT pg_advisory_xact_lock(424244)")  # one replica wipes; the rest wait and see the token
        else:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")  # Postgres has it in SCHEMA
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (TOKEN_KEY,)).fetchone()
        if row and row["value"] == token:
            return None
        counts = {table: conn.execute(f"DELETE FROM {table}").rowcount for table in WIPE_TABLES}
        for table in RESET_SEQUENCES:
            if db.USE_PG:
                conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), 1, false)")
            else:
                try:
                    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                except sqlite3.OperationalError:  # the database never wrote an AUTOINCREMENT row
                    pass
        for key, value in ((TOKEN_KEY, token), (REPORT_KEY, db.now_iso() + " " + str(counts))):
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                         (key, value))
    return counts


def _clear_directories() -> dict:
    """Empty the WIPE_DIRS folders. Only real folders directly inside DATA_DIR are touched
    (a symlink is skipped: it could point outside); missing folders count zero files."""
    data_dir = db.DATA_DIR.resolve()
    removed = {}
    for name in WIPE_DIRS:
        removed[name] = 0
        folder = db.DATA_DIR / name
        if folder.is_symlink() or not folder.is_dir() or data_dir not in folder.resolve().parents:
            continue
        for entry in folder.iterdir():
            try:
                if entry.is_dir() and not entry.is_symlink():
                    removed[name] += sum(1 for inner in entry.rglob("*") if inner.is_file())
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                    removed[name] += 1
            except OSError as exc:
                print(f"[maintenance] could not remove {entry}: {exc}", flush=True)
    return removed
