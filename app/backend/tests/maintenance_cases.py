"""One-shot operational wipe (MAINTENANCE_WIPE_OPERATIONAL): the pilot's test measurements leave once,
master data stays, files only under DATA_DIR, and the recorded token makes restarts a no-op."""
import io
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch


def fresh(prefix):
    """A token never recorded before: under `discover` the class shares one database file across
    runs (meta and capture_links are not reset by setUp), so every test wipes with its own value."""
    return prefix + "-" + uuid.uuid4().hex[:8]


class MaintenanceCases:
    def seed_for_wipe(self):
        """One row in every operational table (beyond setUp's readings) plus master rows that must survive."""
        now = self.db.now_iso()
        reading_id = self.own["id"]
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM capture_links WHERE token = 'L128-keep'")  # kept by design, so earlier runs leave it
            conn.execute("INSERT INTO management_reading_alerts (reading_id,kind,fingerprint,status,version) VALUES (?,?,?,?,1)",
                         (reading_id, "faltante", "fp-alert", "open"))
            conn.execute("INSERT INTO management_reading_reviews (reading_id,status,version) VALUES (?, 'approved', 1)", (reading_id,))
            conn.execute("INSERT INTO management_reading_details (reading_id,data_json,version) VALUES (?, '{}', 1)", (reading_id,))
            conn.execute("INSERT INTO management_training_suggestions (reading_id,image_index,item_index,model,created_by,created_at) "
                         "VALUES (?,0,0,'gemini-test','analyst',?)", (reading_id, now))
            conn.execute("INSERT INTO management_training_labels (id,reading_id,image_index,item_index,data_json,crop_path,created_by,created_at) "
                         "VALUES ('lab-1',?,0,0,'{}','_training/lab-1.jpg','analyst',?)", (reading_id, now))
            conn.execute("INSERT INTO management_kilby_trainings (id,catalog,status,data_json,started_by,started_at,updated_at) "
                         "VALUES ('tr-1','salcobrand','done','{}','admin',?,?)", (now, now))
            conn.execute("INSERT INTO shadow_runs (job_id,reading_id,created_at) VALUES ('job-1',?,?)", (reading_id, now))
            conn.execute("INSERT INTO management_capture_requests (request_key,submitted_by,point_id,fingerprint,job_id,created_at) "
                         "VALUES ('rq-1','analyst','point-a','fp-rq','job-1',?)", (now,))
            conn.execute("INSERT INTO api_jobs (job_id,client_id,point_id,status,created_at) VALUES ('job-1','app','point-a','done',?)", (now,))
            conn.execute("INSERT INTO stock_actions (point_id,product_title,action_type,quantity,created_at) "
                         "VALUES ('point-a','Producto A','solicitud',2,?)", (now,))
            conn.execute("INSERT INTO supplier_stockouts (point_id,planogram_item_id,product_title,created_at) "
                         "VALUES ('point-a',1,'Producto A',?)", (now,))
            conn.execute("INSERT INTO capture_links (token,store_id,created_at) VALUES ('L128-keep','L128',?)", (now,))
            conn.execute("INSERT INTO captures (token,store_id,created_at,rel_path) VALUES ('L128-keep','L128',?,?)",
                         (now, "capturas/L128/2026-11-19/a.jpg"))
            # Master data: every kept table holds at least one row the wipe must not touch.
            conn.execute("INSERT INTO planograms (id,name,created_at) VALUES ('pg-keep','Dermo',?)", (now,))
            conn.execute("INSERT INTO planogram_items (planogram_id,title) VALUES ('pg-keep','Producto A')")
            conn.execute("INSERT INTO management_products (id,sku,name,data_json,created_at,updated_at) "
                         "VALUES ('prod-keep','000111','Paracetamol','{\"photo\":\"data:image/jpeg;base64,x\"}',?,?)", (now, now))
            conn.execute("INSERT INTO management_kilby_products (sku,product_id,pending,catalog,synced_fingerprint,updated_at) "
                         "VALUES ('000111','prod-keep',NULL,'salcobrand','fp-synced',?)", (now,))
            conn.execute("INSERT INTO management_integrations (id,values_json,secrets_json,version,updated_at) "
                         "VALUES ('kilby','{}','{\"api_key\":\"encrypted\"}',3,?)", (now,))
            conn.execute("INSERT INTO management_settings (id,data_json,version) VALUES (1,'{\"weights\":{}}',2)")
            conn.execute("INSERT INTO management_stores (code,name,created_at,updated_at) VALUES ('L128','Local 128',?,?)", (now, now))
            conn.execute("INSERT INTO management_shelf_types (id,name,width_cm,depths_json,created_at,updated_at) "
                         "VALUES ('st-1','Góndola',90,'[]',?,?)", (now, now))
            conn.execute("INSERT INTO management_assignments (store_code,type_id,quantity,updated_at) VALUES ('L128','st-1',2,?)", (now,))
            conn.execute("INSERT INTO management_instances (id,store_code,type_id,number,point_id,created_at) "
                         "VALUES ('in-1','L128','st-1',1,'point-a',?)", (now,))
            conn.execute("INSERT INTO management_events (id,actor,action,resource_id,created_at) VALUES ('ev-1','admin','training.label','lab-1',?)", (now,))
            conn.execute("INSERT INTO management_plan_scope_state (plan_id,initialized_at) VALUES ('pg-keep',?)", (now,))
            conn.execute("INSERT INTO management_plan_scopes (plan_id,store_code,category,subcategory,assigned_by,assigned_at) "
                         "VALUES ('pg-keep','L128','Dermo','Facial','admin',?)", (now,))
            conn.execute("INSERT INTO management_people (id,username,data_json,updated_at) VALUES ('pe-1','admin','{}',?)", (now,))
            conn.execute("INSERT INTO management_clients (id,slug,name,tenant_json,model_json,updated_at) "
                         "VALUES ('cl-1','salcobrand','Salcobrand','{}','{}',?)", (now,))
            conn.execute("INSERT INTO management_planograms (id,data_json,updated_at) VALUES ('mp-1','{}',?)", (now,))

    def table_counts(self, tables):
        with self.db.get_conn() as conn:
            return {table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] for table in tables}

    def meta_value(self, key):
        with self.db.get_conn() as conn:
            try:
                row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            except sqlite3.OperationalError:  # the one-shot wipe never ran: no meta table in SQLite yet
                return None
        return row["value"] if row else None

    def test_startup_wipe_runs_once_per_token_and_keeps_master_data(self):
        import maintenance
        first, second = fresh("pilot-real-photos"), fresh("pilot-second")
        self.seed_for_wipe()
        kept_before = self.table_counts(maintenance.KEEP_TABLES)
        self.assertTrue(all(kept_before.values()), kept_before)  # the survival check is about real rows
        self.assertTrue(all(self.table_counts(maintenance.WIPE_TABLES).values()))  # and every wiped table starts full
        output = io.StringIO()
        with patch.dict(os.environ, {maintenance.ENV_VAR: first}), redirect_stdout(output):
            self.db.init_db()  # the check lives in the startup path
        self.assertEqual(self.table_counts(maintenance.WIPE_TABLES), {table: 0 for table in maintenance.WIPE_TABLES})
        self.assertEqual(self.table_counts(maintenance.KEEP_TABLES), kept_before)
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT synced_fingerprint FROM management_kilby_products WHERE sku='000111'")
                             .fetchone()["synced_fingerprint"], "fp-synced")
            self.assertEqual(conn.execute("SELECT secrets_json FROM management_integrations WHERE id='kilby'")
                             .fetchone()["secrets_json"], '{"api_key":"encrypted"}')
            self.assertEqual(conn.execute("SELECT active FROM capture_links WHERE token='L128-keep'").fetchone()["active"], 1)
        self.assertEqual(self.meta_value(maintenance.TOKEN_KEY), first)
        self.assertIn("[maintenance] operational wipe: ", output.getvalue())
        self.assertIn("readings=3", output.getvalue())  # the counts per table are logged
        self.assertIn("management_training_labels=1", output.getvalue())
        # Autoincrement restarts: the pilot's first real reading is reading 1.
        survivor = self.db.add_reading("point-a", self.analysis, ["point-a/real.jpg"], captured_by="analyst")
        self.assertEqual(survivor["id"], 1)
        # A pod restart / redeploy with the SAME value never wipes again.
        with patch.dict(os.environ, {maintenance.ENV_VAR: first}):
            self.db.init_db()
        self.assertEqual(self.table_counts(("readings",))["readings"], 1)
        # Only a NEW token wipes once more.
        with patch.dict(os.environ, {maintenance.ENV_VAR: second}):
            self.db.init_db()
        self.assertEqual(self.table_counts(("readings",))["readings"], 0)
        self.assertEqual(self.meta_value(maintenance.TOKEN_KEY), second)

    def test_wipe_without_token_or_outside_api_startup_is_a_noop(self):
        import maintenance
        with patch.dict(os.environ):
            os.environ.pop(maintenance.ENV_VAR, None)
            self.assertIsNone(maintenance.wipe_if_requested())  # variable not set: nothing happens
        with patch.dict(os.environ, {maintenance.ENV_VAR: fresh("worker-must-not-wipe")}):
            self.db.init_db("worker")  # only the API startup wipes
            self.assertEqual(self.table_counts(("readings",))["readings"], 3)
            self.db.init_db("api")  # proves the worker neither wiped nor recorded the token
            self.assertEqual(self.table_counts(("readings",))["readings"], 0)

    def test_wipe_clears_photo_and_cache_folders_only_inside_data_dir(self):
        import maintenance
        import shutil
        data_dir = Path(self.db.DATA_DIR)
        for name in ("uploads", "kilby-crops"):  # a known starting point: exactly the files below
            shutil.rmtree(data_dir / name, ignore_errors=True)
        inside = [data_dir / "uploads" / "point-a" / "own.jpg", data_dir / "uploads" / "_training" / "lab-1.jpg",
                  data_dir / "uploads" / "capturas" / "L128" / "2026-11-19" / "a.jpg",
                  data_dir / "kilby-crops" / "job-1" / "0-0.jpg"]
        for path in inside:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test-bytes")
        keeper = data_dir / "registration_code"
        keeper.write_text("INVITE")
        self.addCleanup(keeper.unlink)
        outside = tempfile.TemporaryDirectory(prefix="salcobrand-outside-")
        self.addCleanup(outside.cleanup)
        protected = Path(outside.name) / "real-photo.jpg"
        protected.write_bytes(b"outside-data-dir")
        thumbs = data_dir / "thumbs"
        shutil.rmtree(thumbs, ignore_errors=True)
        thumbs.symlink_to(outside.name)  # a redirected folder must be skipped, never followed
        self.addCleanup(thumbs.unlink)
        with patch.dict(os.environ, {maintenance.ENV_VAR: fresh("files-guard")}):
            result = maintenance.wipe_if_requested()
        self.assertEqual(result["files"], {"uploads": 3, "kilby-crops": 1, "thumbs": 0})
        for path in inside:
            self.assertFalse(path.exists(), path)
        self.assertTrue((data_dir / "uploads").is_dir())  # the folders stay, only their contents leave
        self.assertTrue((data_dir / "kilby-crops").is_dir())
        self.assertEqual(protected.read_bytes(), b"outside-data-dir")
        self.assertEqual(keeper.read_text(), "INVITE")
        self.assertTrue((data_dir / "data.db").exists())
        # Missing folders are fine: a second wipe with everything already gone counts zero.
        shutil.rmtree(data_dir / "kilby-crops")
        with patch.dict(os.environ, {maintenance.ENV_VAR: fresh("files-guard-empty")}):
            self.assertEqual(maintenance.wipe_if_requested()["files"], {"uploads": 0, "kilby-crops": 0, "thumbs": 0})

    def test_every_table_is_classified_and_serial_resets_match_pgcompat(self):
        import maintenance
        import pgcompat
        self.assertEqual(set(maintenance.WIPE_TABLES) | set(maintenance.KEEP_TABLES), set(pgcompat.TABLE_ORDER))
        self.assertEqual(set(maintenance.WIPE_TABLES) & set(maintenance.KEEP_TABLES), set())
        self.assertEqual(set(maintenance.RESET_SEQUENCES), set(pgcompat.SERIAL_TABLES) & set(maintenance.WIPE_TABLES))

    def test_wipe_runs_the_postgres_statements_in_one_transaction(self):
        """The Postgres layer gets the advisory lock, the sequence resets and the meta upsert in
        the same transaction, like test_pg_migration drives migrate_from_sqlite."""
        import maintenance
        import management_schema
        target = sqlite3.connect(":memory:")
        self.addCleanup(target.close)
        target.row_factory = sqlite3.Row
        target.executescript(self.db.SCHEMA + management_schema.SCHEMA)
        target.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        target.execute("INSERT INTO readings (point_id, created_at) VALUES ('point-a', 'now')")
        target.commit()
        statements = []

        class PGShim:
            def __init__(self, database):
                self.database = database

            def execute(self, sql, params=()):
                statements.append(sql)
                if "pg_advisory_xact_lock" in sql or "setval(" in sql:
                    return self.database.execute("SELECT 1")
                return self.database.execute(sql, params)

        def connected(shim):
            @contextmanager
            def fake_get_conn():
                try:
                    yield shim
                    target.commit()
                except Exception:
                    target.rollback()
                    raise
            return fake_get_conn

        with patch.object(self.db, "USE_PG", True), patch.object(self.db, "get_conn", connected(PGShim(target))):
            counts = maintenance._wipe_tables("pg-token-1")
            self.assertIsNone(maintenance._wipe_tables("pg-token-1"))  # second replica: recorded token, no-op
        self.assertEqual(counts["readings"], 1)
        self.assertEqual(sum("pg_advisory_xact_lock" in sql for sql in statements), 2)
        self.assertEqual(sum("setval(" in sql for sql in statements), len(maintenance.RESET_SEQUENCES))
        self.assertNotIn("CREATE TABLE IF NOT EXISTS meta", " ".join(statements))  # Postgres already has meta in SCHEMA
        self.assertEqual(target.execute("SELECT value FROM meta WHERE key = ?", (maintenance.TOKEN_KEY,)).fetchone()["value"],
                         "pg-token-1")
        # A failure mid-wipe rolls the whole transaction back: nothing half-deleted, no token recorded.
        target.execute("INSERT INTO readings (point_id, created_at) VALUES ('point-a', 'again')")
        target.commit()

        class FailingShim(PGShim):
            def execute(self, sql, params=()):
                if sql.startswith("DELETE FROM captures"):
                    raise RuntimeError("interrupted wipe")
                return super().execute(sql, params)

        with patch.object(self.db, "USE_PG", True), patch.object(self.db, "get_conn", connected(FailingShim(target))):
            with self.assertRaisesRegex(RuntimeError, "interrupted wipe"):
                maintenance._wipe_tables("pg-token-2")
        self.assertEqual(target.execute("SELECT COUNT(*) AS n FROM readings").fetchone()["n"], 1)
        self.assertEqual(target.execute("SELECT value FROM meta WHERE key = ?", (maintenance.TOKEN_KEY,)).fetchone()["value"],
                         "pg-token-1")
