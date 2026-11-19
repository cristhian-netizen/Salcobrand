"""Dataset sweep (local-neura): original phone photos stored verbatim, zero analysis, zero processing.

The upload path must never decode-and-re-encode: sha256(stored file) == sha256(uploaded bytes) for
HEIC and JPEG alike, dimensions are read without rejecting unreadable HEIC, and the files live on
the service disk (DATA_DIR/dataset), outside the readings/S3 pipeline and outside the wipe."""
import hashlib
import io
import shutil
import types
from pathlib import Path
from unittest.mock import patch

import httpx

CATALOGS = [{"slug": "salud-sexual", "name": "Salud sexual", "products": 10},
            {"slug": "desodorantes", "name": "Desodorantes", "products": 5}]


def image_bytes(fmt, size=(640, 420), color=(200, 30, 60)):
    from PIL import Image
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except Exception:
        pass
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


class DatasetCases:
    def dataset_env(self, calls=None):
        """Kilby answering the catalogs listing, a saved key, and an empty dataset folder."""
        def handler(request):
            if calls is not None:
                calls.append(request.url.path)
            if request.url.path == "/v1/neuravision/catalogs":
                return httpx.Response(200, json={"object": "list", "data": CATALOGS})
            return httpx.Response(404, json={"error": {"type": "invalid_request_error", "message": "not found"}})
        self.kilby(handler)
        self.save_key()
        shutil.rmtree(Path(self.db.DATA_DIR) / "dataset", ignore_errors=True)

    def dataset_upload(self, client, files, category="salud-sexual", **fields):
        return client.post("/api/admin/dataset/images", data={"category": category, **fields}, files=files)

    def stored_dataset_file(self, image_id):
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM management_dataset_images WHERE id = ?", (image_id,)).fetchone()
        self.assertIsNotNone(row)
        return dict(row), Path(self.db.DATA_DIR) / row["path"]

    def test_dataset_categories_list_active_catalogs_with_totals_and_sixty_second_cache(self):
        calls = []
        self.dataset_env(calls)
        trainer = self.trainer()
        first = trainer.get("/api/admin/dataset/categories")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        payload = first.json()
        self.assertIsNone(payload["warning"])
        self.assertEqual([(c["slug"], c["name"], c["active"], c["count"], c["bytes"]) for c in payload["categories"]],
                         [("salud-sexual", "Salud sexual", True, 0, 0), ("desodorantes", "Desodorantes", True, 0, 0)])
        jpeg = image_bytes("JPEG")
        created = self.dataset_upload(trainer, [("files", ("IMG_0001.jpg", jpeg, "image/jpeg"))])
        self.assertEqual(created.status_code, 201, created.text)
        again = trainer.get("/api/admin/dataset/categories").json()
        by_slug = {c["slug"]: c for c in again["categories"]}
        self.assertEqual((by_slug["salud-sexual"]["count"], by_slug["salud-sexual"]["bytes"]), (1, len(jpeg)))
        # Two listings and one upload resolved the catalogs, but Kilby was asked once (60 s cache).
        self.assertEqual(calls.count("/v1/neuravision/catalogs"), 1)

    def test_dataset_upload_stores_bytes_verbatim_for_heic_and_jpeg(self):
        self.dataset_env()
        trainer = self.trainer()
        heic, jpeg = image_bytes("HEIF", size=(320, 240)), image_bytes("JPEG")
        response = self.dataset_upload(trainer, [
            ("files", ("IMG_0001.HEIC", heic, "image/heic")),
            # A lying filename/content type must not matter: the bytes are sniffed, stored untouched.
            ("files", ("renamed.png", jpeg, "image/png")),
        ])
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()["created"]
        self.assertEqual(len(created), 2)
        for item, uploaded, mimes, extension, size in ((created[0], heic, ("image/heic", "image/heif"), ("heic", "heif"), (320, 240)),
                                                       (created[1], jpeg, ("image/jpeg",), ("jpg",), (640, 420))):
            row, path = self.stored_dataset_file(item["id"])
            self.assertIn(row["mime"], mimes)
            self.assertIn(path.suffix.lstrip("."), extension)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(uploaded).hexdigest())
            self.assertEqual((row["bytes"], row["width"], row["height"]), (len(uploaded), *size))
            self.assertEqual(row["created_by"], "local-neura")
            self.assertTrue(str(Path(row["path"])).startswith("dataset/salud-sexual/"))
        # Verbatim also means outside the readings pipeline: nothing went through storage/S3.
        self.storage.put.assert_not_called()
        with self.db.get_conn() as conn:
            audited = conn.execute("SELECT COUNT(*) AS n FROM management_events WHERE action = 'dataset.upload'").fetchone()["n"]
        self.assertEqual(audited, 2)

    def test_dataset_heic_with_unreadable_dimensions_is_stored_not_rejected(self):
        self.dataset_env()
        trainer = self.trainer()
        fake_heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"not-a-decodable-image" * 50
        response = self.dataset_upload(trainer, [("files", ("IMG_0002.heic", fake_heic, "image/heic"))])
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()["created"][0]
        self.assertEqual((item["width"], item["height"]), (None, None))
        row, path = self.stored_dataset_file(item["id"])
        self.assertEqual((row["width"], row["height"], row["mime"]), (None, None, "image/heic"))
        self.assertEqual(path.read_bytes(), fake_heic)

    def test_dataset_upload_rejects_bad_category_size_format_and_store(self):
        import dataset_api
        self.dataset_env()
        trainer = self.trainer()
        jpeg = image_bytes("JPEG")
        bad_category = self.dataset_upload(trainer, [("files", ("a.jpg", jpeg, "image/jpeg"))], category="perfumes")
        self.assertEqual(bad_category.status_code, 400)
        self.assertIn("categoría", bad_category.json()["detail"])
        too_many = self.dataset_upload(trainer, [("files", (f"a{i}.jpg", jpeg, "image/jpeg")) for i in range(13)])
        self.assertEqual(too_many.status_code, 400)
        not_an_image = self.dataset_upload(trainer, [("files", ("a.jpg", jpeg, "image/jpeg")),
                                                     ("files", ("notes.txt", b"plain text, not a photo", "image/jpeg"))])
        self.assertEqual(not_an_image.status_code, 400)
        self.assertIn("JPEG, PNG, WebP o HEIC", not_an_image.json()["detail"])
        with patch.object(dataset_api, "MAX_BYTES_EACH", 2048):
            oversized = self.dataset_upload(trainer, [("files", ("big.jpg", jpeg, "image/jpeg"))])
        self.assertEqual(oversized.status_code, 413)
        unknown_store = self.dataset_upload(trainer, [("files", ("a.jpg", jpeg, "image/jpeg"))], store_id="L999")
        self.assertEqual(unknown_store.status_code, 400)
        self.assertIn("PDV", unknown_store.json()["detail"])
        # Every rejected request is all-or-nothing: no rows and no files left behind.
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM management_dataset_images").fetchone()["n"], 0)
        dataset = Path(self.db.DATA_DIR) / "dataset"
        self.assertEqual([p for p in dataset.rglob("*") if p.is_file()] if dataset.exists() else [], [])
        with self.db.get_conn() as conn:
            conn.execute("INSERT INTO management_stores (code,name,created_at,updated_at) VALUES ('L128','Local 128',?,?)",
                         (self.db.now_iso(), self.db.now_iso()))
        provenance = self.dataset_upload(trainer, [("files", ("a.jpg", jpeg, "image/jpeg"))], store_id="L128")
        self.assertEqual(provenance.status_code, 201, provenance.text)
        self.assertEqual(provenance.json()["created"][0]["store_id"], "L128")

    def test_dataset_endpoints_are_training_only(self):
        self.dataset_env()
        trainer = self.trainer()
        jpeg = image_bytes("JPEG")
        kept = self.dataset_upload(trainer, [("files", ("keep.jpg", jpeg, "image/jpeg"))]).json()["created"][0]
        for role in (None, "admin", "analyst", "replenisher", "viewer"):
            client = self.client(role)
            expected = 401 if role is None else 403
            self.assertEqual(client.get("/api/admin/dataset/categories").status_code, expected, role)
            self.assertEqual(client.get("/api/admin/dataset/images?category=salud-sexual").status_code, expected, role)
            self.assertEqual(client.get(kept["url"]).status_code, expected, role)
            self.assertEqual(self.dataset_upload(client, [("files", ("x.jpg", jpeg, "image/jpeg"))]).status_code, expected, role)
            self.assertEqual(client.delete("/api/admin/dataset/images/" + kept["id"]).status_code, expected, role)
        self.assertEqual(trainer.get(kept["url"]).status_code, 200)
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM management_dataset_images").fetchone()["n"], 1)

    def test_dataset_list_original_file_thumbnail_and_delete(self):
        self.dataset_env()
        trainer = self.trainer()
        first, second = image_bytes("JPEG", color=(10, 90, 170)), image_bytes("PNG", size=(300, 200))
        one = self.dataset_upload(trainer, [("files", ("one.jpg", first, "image/jpeg"))]).json()["created"][0]
        two = self.dataset_upload(trainer, [("files", ("two.png", second, "image/png"))]).json()["created"][0]
        listed = trainer.get("/api/admin/dataset/images?category=salud-sexual")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([i["id"] for i in listed.json()["images"]], [two["id"], one["id"]])
        self.assertEqual(trainer.get("/api/admin/dataset/images?category=desodorantes").json()["images"], [])
        original = trainer.get(one["url"])
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.content, first)  # the grid may shrink; the file endpoint never does
        self.assertEqual(original.headers["content-type"], "image/jpeg")
        self.assertIn("private", original.headers["cache-control"])
        self.assertIn("immutable", original.headers["cache-control"])
        self.assertEqual(trainer.get(one["url"], headers={"If-None-Match": original.headers["etag"]}).status_code, 304)
        thumb = trainer.get(one["url"] + "?w=128")
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["content-type"], "image/jpeg")
        self.assertLess(len(thumb.content), len(first))
        _row, path = self.stored_dataset_file(one["id"])
        self.assertEqual(trainer.delete("/api/admin/dataset/images/" + one["id"]).json()["deleted"], one["id"])
        self.assertFalse(path.exists())
        self.assertEqual(trainer.delete("/api/admin/dataset/images/" + one["id"]).status_code, 404)
        self.assertEqual(trainer.get(one["url"]).status_code, 404)
        self.assertEqual([i["id"] for i in trainer.get("/api/admin/dataset/images?category=salud-sexual").json()["images"]],
                         [two["id"]])

    def test_dataset_low_disk_refuses_with_507_before_writing(self):
        self.dataset_env()
        trainer = self.trainer()
        usage = types.SimpleNamespace(total=10 ** 12, used=10 ** 12 - 100 * 1024 * 1024, free=100 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=usage):
            response = self.dataset_upload(trainer, [("files", ("a.jpg", image_bytes("JPEG"), "image/jpeg"))])
        self.assertEqual(response.status_code, 507, response.text)
        self.assertEqual(response.json()["detail"], "Espacio insuficiente en el disco del servicio; amplíalo en Kilby")
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM management_dataset_images").fetchone()["n"], 0)
        dataset = Path(self.db.DATA_DIR) / "dataset"
        self.assertEqual([p for p in dataset.rglob("*") if p.is_file()] if dataset.exists() else [], [])

    def test_dataset_categories_fall_back_to_configured_catalog_when_kilby_is_unreachable(self):
        import kilby_catalog
        kilby_catalog.forget_catalogs()
        shutil.rmtree(Path(self.db.DATA_DIR) / "dataset", ignore_errors=True)
        trainer = self.trainer()
        bare = trainer.get("/api/admin/dataset/categories").json()  # no key, no configured catalog
        self.assertEqual(bare["categories"], [])
        self.assertIn("Kilby", bare["warning"])
        blocked = self.dataset_upload(trainer, [("files", ("a.jpg", image_bytes("JPEG"), "image/jpeg"))])
        self.assertEqual(blocked.status_code, 400)
        admin = self.client("admin")
        version = admin.get("/api/admin/integrations").json()["integrations"][0]["version"]
        saved = admin.put("/api/admin/integrations/neuravision", json={"version": version, "values": {"catalog": "salud-sexual"}})
        self.assertEqual(saved.status_code, 200, saved.text)
        fallback = trainer.get("/api/admin/dataset/categories").json()
        self.assertEqual([(c["slug"], c["active"]) for c in fallback["categories"]], [("salud-sexual", True)])
        self.assertIn("catálogo configurado", fallback["warning"])
        allowed = self.dataset_upload(trainer, [("files", ("a.jpg", image_bytes("JPEG"), "image/jpeg"))])
        self.assertEqual(allowed.status_code, 201, allowed.text)

    def test_dataset_file_loads_when_any_browser_session_can_train(self):
        """El navegador real guarda una sesión por pestaña: la legacy puede ser de un perfil sin
        entrenamiento y la de otra pestaña de local-neura. La foto carga si ALGUNA puede entrenar;
        con sesiones pero ninguna entrenadora es el rechazo de perfil, no un 401."""
        self.dataset_env()
        up = self.dataset_upload(self.trainer(), [("files", ("a.jpg", image_bytes("JPEG"), "image/jpeg"))])
        self.assertEqual(up.status_code, 201, up.text)
        image_id = up.json()["created"][0]["id"]
        url = f"/api/admin/dataset/images/{image_id}/file"

        mixed = self.client(None)
        mixed.cookies.set(self.auth.SESSION_COOKIE, self.auth.create_session_token("admin"))
        mixed.cookies.set(self.auth.SESSION_COOKIE + "_" + "ab" * 16,
                          self.auth.create_session_token("local-neura"))
        self.assertEqual(mixed.get(url).status_code, 200)

        admin_only = self.client("admin")
        self.assertEqual(admin_only.get(url).status_code, 403)
