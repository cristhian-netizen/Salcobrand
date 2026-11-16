"""Exercise migration coverage and atomicity without a running PostgreSQL server."""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pgcompat


class MigrationConnection:
    def __init__(self, database):
        self.database = database
        self.raw = self

    def cursor(self):
        return self.database.cursor()

    def execute(self, sql, params=()):
        if "pg_advisory_xact_lock" in sql or "setval(" in sql:
            return self.database.execute("SELECT 1")
        if "information_schema.columns" in sql:
            return self.database.execute("SELECT name AS column_name FROM pragma_table_info(?)", params)
        return self.database.execute(sql, params)


class PostgresMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source_path = Path(self.temp.name) / "source.db"
        # Both databases use the application table definitions. PG-only schema
        # operations are covered separately when the Kilby service is reachable.
        from db import SCHEMA
        from management_schema import SCHEMA as management_schema
        self.source = sqlite3.connect(self.source_path)
        self.addCleanup(self.source.close)
        self.target = sqlite3.connect(":memory:")
        self.addCleanup(self.target.close)
        self.target.row_factory = sqlite3.Row
        for database in (self.source, self.target):
            database.executescript(SCHEMA + management_schema)
        self.target.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        self.tables = [row[0] for row in self.source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        # Give every source table one row so an omitted module cannot pass silently.
        for table in self.tables:
            if self.source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                continue
            columns = self.source.execute(f'PRAGMA table_info("{table}")').fetchall()
            values = {column[1]: (1 if "INT" in column[2] or "REAL" in column[2] or "DOUBLE" in column[2] else "fixture")
                      for column in columns if (column[3] and column[4] is None) or column[5]}
            self.source.execute(f'INSERT INTO "{table}" ({",".join(values)}) VALUES ({",".join("?" for _ in values)})',
                                tuple(values.values()))
        self.source.commit()

    @contextmanager
    def connection(self):
        with self.target:
            yield MigrationConnection(self.target)

    def batch(self, cursor, sql, rows, **kwargs):
        cursor.executemany(sql.replace("%s", "?"), rows)

    def test_every_populated_module_is_copied_and_retry_preserves_data(self):
        self.assertEqual(set(self.tables), set(pgcompat.TABLE_ORDER))
        with patch.object(pgcompat, "connection", self.connection), \
                patch.object(pgcompat.psycopg2.extras, "execute_batch", self.batch):
            counts = pgcompat.migrate_from_sqlite(self.source_path)
            self.assertEqual(counts, {table: 1 for table in self.tables})
            for table in self.tables:
                actual = [tuple(row) for row in self.target.execute(f'SELECT * FROM "{table}"')]
                expected = self.source.execute(f'SELECT * FROM "{table}"').fetchall()
                self.assertEqual(actual, expected, table)
            self.assertEqual(pgcompat.migrate_from_sqlite(self.source_path), {"skipped": "ya migrada"})

    def test_partial_failure_rolls_back_import_and_completion_marker(self):
        def fail_on_users(cursor, sql, rows, **kwargs):
            if re.match(r"INSERT INTO users\b", sql):
                raise RuntimeError("Interrupted transfer")
            self.batch(cursor, sql, rows)

        with patch.object(pgcompat, "connection", self.connection), \
                patch.object(pgcompat.psycopg2.extras, "execute_batch", fail_on_users):
            with self.assertRaisesRegex(RuntimeError, "Interrupted transfer"):
                pgcompat.migrate_from_sqlite(self.source_path)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM points").fetchone()[0], 0)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM meta").fetchone()[0], 0)

    def test_existing_management_data_prevents_import(self):
        self.target.execute("INSERT INTO management_settings (id,data_json) VALUES (1,'existing')")
        self.target.commit()
        with patch.object(pgcompat, "connection", self.connection), \
                patch.object(pgcompat.psycopg2.extras, "execute_batch", self.batch):
            self.assertEqual(pgcompat.migrate_from_sqlite(self.source_path), {"skipped": "postgres ya tenía datos"})
        self.assertEqual(self.target.execute("SELECT data_json FROM management_settings").fetchone()[0], "existing")
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM points").fetchone()[0], 0)

    def test_unknown_source_column_rolls_back_instead_of_losing_values(self):
        self.source.execute("ALTER TABLE management_products ADD COLUMN extra_value TEXT")
        self.source.execute("UPDATE management_products SET extra_value='preserve me'")
        self.source.commit()
        with patch.object(pgcompat, "connection", self.connection), \
                patch.object(pgcompat.psycopg2.extras, "execute_batch", self.batch):
            with self.assertRaisesRegex(ValueError, "extra_value"):
                pgcompat.migrate_from_sqlite(self.source_path)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM points").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
