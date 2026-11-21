"""HTTP authorization tests: real routes/auth/SQLite, engine and external services isolated.

Run: python -m unittest discover -s app/backend/tests -v
No cloud credentials, remote database or model execution is used.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from infrastructure_cases import InfrastructureCases
from catalog_cases import CatalogCases
from capture_cases import CaptureCases
from report_cases import ReportCases
from settings_cases import SettingsCases
from home_cases import HomeCases
from detail_cases import DetailCases
from dashboard_cases import DashboardCases
from alert_cases import AlertCases
from store_excel_cases import StoreExcelCases
from people_cases import PeopleCases
from usage_cases import UsageCases
from console_cases import ConsoleCases
from session_cases import SessionCases
from portal_improvements_cases import PortalImprovementsCases
from brand_settings_cases import BrandSettingsCases
from shared_plan_cases import SharedPlanCases
from email_access_cases import EmailAccessCases
from kilby_cases import KilbyCases
from gemini_cases import GeminiCases
from image_cache_cases import ImageCacheCases
from maintenance_cases import MaintenanceCases
from dataset_cases import DatasetCases
from dataset_link_cases import DatasetLinkCases
from gondola_cases import GondolaCases

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class ProfileHTTPTests(GondolaCases, DatasetLinkCases, DatasetCases, MaintenanceCases, GeminiCases, ImageCacheCases, KilbyCases, EmailAccessCases, SharedPlanCases, BrandSettingsCases, PortalImprovementsCases, SessionCases, ConsoleCases, UsageCases, PeopleCases, StoreExcelCases, AlertCases, DashboardCases, DetailCases, HomeCases, SettingsCases, ReportCases, CaptureCases, CatalogCases, InfrastructureCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="salcobrand-profile-tests-")
        cls.env = patch.dict(os.environ, {"DATA_DIR": cls.temp.name, "CATALOG_ROOT": cls.temp.name,
                                         "SESSION_SECRET": "isolated-profile-test-secret", "ROLE": "api",
                                         "REGISTRATION_CODE": "isolated-test-invite", "DATABASE_URL": "", "DB_HOST": ""})
        cls.env.start()
        import db
        cls.db = db
        db.PLANOGRAM_SEED_PATH = Path(cls.temp.name) / "no-seed.json"
        core = types.ModuleType("core")
        core.UPLOADS_DIR, core.ENGINE_STATE = Path(cls.temp.name), {}
        core.read_image_uploads = AsyncMock(return_value=[(b"synthetic", "image/jpeg")])
        core.save_upload = Mock(return_value="point-a/synthetic.jpg")
        core.review_items_for_reading = lambda r, **kwargs: {"reading_id": r["id"], "items": []}
        core.confirm_reading_item = Mock(return_value={"ok": True})
        core.crop_jpeg = Mock(return_value=b"synthetic-crop")
        core.delete_uploads = Mock()
        core.MAX_IMAGES = 6
        core.remote_enabled = lambda: False
        core.engine_health = Mock(return_value={"engine_ready": False, "engine_error": "Motor deshabilitado en QA", "components": {"mode": "isolated"}})
        jobs = types.ModuleType("api_jobs")
        jobs.APP_CLIENT = "app"
        jobs.enqueue = Mock(return_value={"job_id": "isolated-job"})
        import uuid
        jobs.new_job_id = lambda: "j_" + uuid.uuid4().hex[:16]
        jobs._dispatch = Mock()
        key_api = types.ModuleType("api_v1")
        key_api.app = FastAPI()
        def isolated_api_identity(request):
            if request.headers.get("x-api-key") != "isolated-client-key":
                raise HTTPException(401, "Invalid test API identity")
            return {"client": {"client_id": "test-client"}}
        key_api.require_api_key = isolated_api_identity
        storage = types.ModuleType("storage")
        storage.get = Mock(return_value=b"synthetic-photo")
        storage.put = Mock()
        storage.delete_many = Mock()
        storage.content_type_for = lambda path: "image/jpeg"
        storage.delete_prefix = Mock()
        captures, vivo = types.ModuleType("captures"), types.ModuleType("vivo")
        captures.router, vivo.router = APIRouter(), APIRouter()
        cls.modules = patch.dict(sys.modules, {"core": core, "api_jobs": jobs, "api_v1": key_api,
                                               "storage": storage, "captures": captures, "vivo": vivo,
                                               "shadow": types.ModuleType("shadow")})
        cls.modules.start()
        cls.dotenv = patch("dotenv.load_dotenv", return_value=False)
        cls.dotenv.start()
        cls.main = importlib.import_module("main")
        cls.auth = importlib.import_module("auth")
        cls.core, cls.jobs, cls.storage = core, jobs, storage

    @classmethod
    def tearDownClass(cls):
        cls.dotenv.stop()
        cls.modules.stop()
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        with self.db.get_conn() as conn:
            for table in ("management_integrations", "management_kilby_products", "management_kilby_trainings", "management_dataset_images", "management_dataset_links", "management_plan_scopes", "management_plan_scope_state", "management_training_labels", "management_training_suggestions", "management_clients", "management_people", "management_reading_alerts", "management_reading_details", "management_settings", "management_reading_reviews", "management_capture_requests", "management_products", "management_planograms", "management_events", "management_instances", "management_assignments", "management_shelf_types", "management_stores", "users", "readings", "points", "api_jobs", "stock_actions", "supplier_stockouts", "planograms", "planogram_items"):
                conn.execute(f"DELETE FROM {table}")
        for name, role, stores in [("admin", "admin", []), ("analyst", "analyst", ["L128", "L129"]),
                                   ("replenisher", "replenisher", ["L128", "L129"]), ("viewer", "viewer", []),
                                   ("legacy-supervisor", "supervisor", ["L128", "L129"]), ("legacy-tienda", "tienda", ["L128"])]:
            hashed, salt = self.auth.hash_password("Isolated-local-password-2026!")
            self.db.create_user(name, hashed, salt, role=role, store_id=stores[0] if len(stores) == 1 else None,
                                store_ids=None if role == "tienda" else stores)
        for pid, store in [("point-a", "L128"), ("point-b", "L129"), ("point-c", "L130")]:
            self.db.create_point(pid, pid, store_id=store, owner_client="test-client")
        self.analysis = {"products": [{"product": "Synthetic product", "facings": 2, "needs_review": True}],
                         "total_facings": 2, "shelf_levels_detected": 1, "empty_space_pct": 5}
        self.own = self.db.add_reading("point-a", self.analysis, ["point-a/own.jpg"], captured_by="replenisher")
        self.other = self.db.add_reading("point-a", self.analysis, ["point-a/other.jpg"], captured_by="analyst")
        self.foreign = self.db.add_reading("point-c", self.analysis, ["point-c/foreign.jpg"], captured_by="analyst")
        self.core.confirm_reading_item.reset_mock()
        self.jobs.enqueue.reset_mock()
        self.jobs._dispatch.reset_mock()
        self.core.delete_uploads.reset_mock()
        self.core.read_image_uploads.return_value = [(b"synthetic", "image/jpeg")]
        self.storage.delete_prefix.reset_mock()
        self.storage.put.reset_mock()
        self.storage.delete_many.reset_mock()

    def client(self, username):
        client = TestClient(self.main.app)
        if username:
            client.cookies.set(self.auth.SESSION_COOKIE, self.auth.create_session_token(username))
        self.addCleanup(client.close)
        return client

    def test_session_profiles_preserve_legacy_roles(self):
        for role in ("admin", "analyst", "replenisher", "viewer"):
            data = self.client(role).get("/api/auth/me").json()
            self.assertEqual(data["profile"], role)
        for name, stored_role, profile in [("legacy-supervisor", "supervisor", "analyst"), ("legacy-tienda", "tienda", "replenisher")]:
            data = self.client(name).get("/api/auth/me").json()
            self.assertEqual((data["role"], data["profile"]), (stored_role, profile))
            self.assertEqual(self.db.get_user(name)["role"], stored_role)
        self.assertEqual(self.client(None).get("/api/auth/me").status_code, 401)

    def test_reports_and_review_matrix(self):
        for role in ("admin", "analyst", "replenisher", "viewer", "legacy-supervisor", "legacy-tienda"):
            client = self.client(role)
            profile = self.main.profiles.profile_of(role.replace("legacy-", ""))
            self.assertEqual(client.get("/api/admin/users").status_code, 200 if profile == "admin" else 403, role)
            self.assertEqual(client.get("/api/export.csv").status_code, 403 if profile == "replenisher" else 200, role)
            self.assertEqual(client.get("/api/review/pending").status_code, 403, role)
            response = client.post(f'/api/readings/{self.other["id"]}/confirm', json={"image_index": 0, "item_index": 0})
            self.assertEqual(response.status_code, 403, role)

    def test_scanning_is_only_analyst_or_replenisher(self):
        for role in ("admin", "analyst", "replenisher", "viewer"):
            reading = self.own if role == "replenisher" else self.other
            with patch.object(self.db, "get_job", return_value={"status": "done", "reading_id": reading["id"]}):
                response = self.client(role).post("/api/points/point-a/analyze", files={"images": ("test.jpg", b"synthetic", "image/jpeg")})
            self.assertEqual(response.status_code, 200 if role in ("analyst", "replenisher") else 403, role)
        self.assertEqual(self.jobs.enqueue.call_count, 2)
        self.assertEqual(self.jobs.enqueue.call_args.args[2]["user"], "replenisher")

    def test_own_readings_and_multiple_pdv_scope(self):
        client = self.client("replenisher")
        self.assertEqual(client.get(f'/api/readings/{self.own["id"]}').status_code, 200)
        self.assertEqual(client.get(f'/api/readings/{self.other["id"]}').status_code, 403)
        self.assertEqual(client.get("/api/points/point-c").status_code, 403)
        detail = client.get("/api/points/point-a").json()
        self.assertEqual([r["id"] for r in detail["readings"]], [self.own["id"]])
        summary = client.get("/api/summary").json()
        self.assertEqual({p["store_id"] for p in summary["points"]}, {"L128", "L129"})
        self.assertEqual(summary["totals"]["readings_in_period"], 1)
        points = client.get("/api/points").json()
        self.assertEqual(sum(p["readings_count"] for p in points), 1)
        analyst = self.client("analyst")
        self.assertEqual(analyst.get("/api/points/point-b").status_code, 200)
        self.assertEqual(analyst.get("/api/points/point-c").status_code, 403)
        self.assertNotIn("point-c", analyst.get("/api/export.csv").text)
        self.assertEqual(analyst.get("/api/points/point-c/export.csv").status_code, 403)

    def test_direct_photos_and_crops_enforce_owner_and_scope(self):
        own = self.client("replenisher")
        self.assertEqual(own.get("/uploads/point-a/own.jpg").status_code, 200)
        self.assertEqual(own.get("/uploads/point-a/other.jpg").status_code, 403)
        self.assertEqual(self.client(None).get("/uploads/point-a/own.jpg").status_code, 401)
        self.assertEqual(self.client("analyst").get("/uploads/point-c/foreign.jpg").status_code, 403)
        self.assertEqual(own.get(f'/api/readings/{self.other["id"]}/crops/0/0.jpg').status_code, 403)
        response = own.get(f'/api/readings/{self.own["id"]}/crops/0/0.jpg')
        self.assertEqual(response.status_code, 200)
        # Crops of a stored reading never change: the browser may keep them (private; auth still runs here).
        self.assertIn("private", response.headers["cache-control"])
        self.assertIn("immutable", response.headers["cache-control"])
        self.assertTrue(response.headers["etag"])
        external = self.client(None)
        self.assertEqual(external.get("/uploads/point-a/own.jpg", headers={"X-API-Key": "isolated-client-key"}).status_code, 200)
        self.assertEqual(external.get("/uploads/point-a/own.jpg", headers={"X-API-Key": "wrong"}).status_code, 401)

    def test_non_admin_cannot_manage_or_delete(self):
        for role in ("analyst", "replenisher", "viewer"):
            client = self.client(role)
            self.assertEqual(client.post("/api/points", data={"name": "Forbidden"}).status_code, 403)
            self.assertEqual(client.delete("/api/points/point-a").status_code, 403)
            self.assertEqual(client.delete(f'/api/readings/{self.own["id"]}').status_code, 403)
            self.assertEqual(client.put("/api/points/point-a/planogram", json={"planogram_id": None}).status_code, 403)
            self.assertEqual(client.post("/api/admin/capture-links", json={"store_id": "L128"}).status_code, 403)
            self.assertEqual(client.delete("/api/admin/planograms/example").status_code, 403)
        self.storage.delete_prefix.assert_not_called()
        self.assertIsNotNone(self.db.get_reading(self.own["id"]))
        admin = self.client("admin")
        self.assertEqual(admin.post("/api/points", data={"name": "New local test", "point_id": "new-point"}).status_code, 200)
        self.assertEqual(admin.delete(f'/api/readings/{self.own["id"]}').status_code, 200)

    def test_resolving_alerts_is_only_analyst(self):
        body = {"product_title": "Synthetic", "action_type": "solicitud", "quantity": 1}
        for role in ("admin", "analyst", "replenisher", "viewer"):
            response = self.client(role).post("/api/points/point-a/stock-actions", json=body)
            self.assertEqual(response.status_code, 200 if role == "analyst" else 403)
        action_id = self.db.list_stock_actions("point-a")[0]["id"]
        self.assertEqual(self.client("viewer").post(f"/api/stock-actions/{action_id}/resolve").status_code, 403)
        self.assertEqual(self.client("analyst").post(f"/api/stock-actions/{action_id}/resolve").status_code, 200)

    def test_admin_creates_profiles_and_multi_pdv_assignments(self):
        admin = self.client("admin")
        for role in ("admin", "analyst", "replenisher", "viewer"):
            response = admin.post("/api/admin/users", json={"username": "new-" + role, "password": "Isolated-new-account-2026!",
                                                           "role": role, "store_ids": ["l128", "L129", "L128"]})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["store_ids"], ["L128", "L129"] if role in ("analyst", "replenisher") else [])
        self.assertEqual(admin.post("/api/admin/users", json={"username": "no-store", "password": "Isolated-new-account-2026!", "role": "replenisher"}).status_code, 400)
        self.assertEqual(admin.patch("/api/admin/users/admin", json={"role": "viewer"}).status_code, 400)
        self.assertEqual(admin.patch("/api/admin/users/analyst", json={"store_ids": []}).status_code, 200)
        self.assertEqual(self.client("analyst").get("/api/points/point-c").status_code, 403)

    def test_invalid_profiles_fail_closed_and_empty_replenisher_sees_nothing(self):
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET role = ? WHERE username = ?", ("unknown-role", "viewer"))
            conn.execute("UPDATE users SET store_ids_json = ?, store_id = NULL WHERE username = ?", ("[]", "replenisher"))
        self.assertEqual(self.client("viewer").get("/api/summary").status_code, 403)
        client = self.client("replenisher")
        self.assertEqual(client.get("/api/summary").json()["points"], [])
        self.assertEqual(client.get("/api/points/point-a").status_code, 403)

    def test_recorded_historical_authors_are_recovered_without_guessing(self):
        unknown = self.db.add_reading("point-a", self.analysis, [])
        job = self.db.create_job("legacy-job", "app", "point-a", {"user": "replenisher"})
        self.db.finish_job(job["job_id"], "done", reading_id=unknown["id"])
        self.db._backfill_authors()
        self.db._backfill_authors()
        self.assertEqual(self.db.get_reading(unknown["id"])["captured_by"], "replenisher")
        no_author = self.db.add_reading("point-a", self.analysis, [])
        self.assertEqual(self.client("replenisher").get(f'/api/readings/{no_author["id"]}').status_code, 403)

    def test_registration_does_not_grant_analyst_permissions(self):
        response = self.client(None).post("/api/auth/register", json={"username": "invited", "password": "Isolated-invited-2026!", "code": "isolated-test-invite"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "viewer")

    def test_reanalysis_cannot_bypass_the_analysts_store_scope(self):
        for role in ("admin", "replenisher", "viewer"):
            self.assertEqual(self.client(role).post("/api/admin/reanalyze").status_code, 403)
        self.assertEqual(self.client("analyst").post("/api/admin/reanalyze").status_code, 409)
        with patch.object(self.main, "ROLE", "all"), \
             patch.object(self.core, "load_images_from_disk", return_value=[], create=True), \
             patch.object(self.core, "analyze_shelf", return_value=self.analysis, create=True):
            response = self.client("analyst").post("/api/admin/reanalyze")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({r["reading_id"] for r in response.json()["updated"]}, {self.own["id"], self.other["id"]})


if __name__ == "__main__":
    unittest.main()
