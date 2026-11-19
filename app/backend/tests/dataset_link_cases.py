"""Anonymous dataset capture links: a URL (no account) that feeds the same verbatim sweep store.

What matters here: the token is never persisted or listed (only its sha256), the public surface
exposes nothing beyond the link's own label and remaining count, uploads are byte-identical and
attributable (created_by = "link:<id-prefix>"), the caps (expiry, max photos, rate) really close
the door, and a rejected batch leaves no rows and no files behind."""
import hashlib
import json
import types
from pathlib import Path
from unittest.mock import patch

from dataset_cases import image_bytes


class DatasetLinkCases:
    def links_env(self, calls=None):
        """dataset_env plus a clean per-token rate limiter (module state survives between tests)."""
        import dataset_links
        self.dataset_env(calls)
        dataset_links._hits.clear()

    def create_dataset_link(self, client=None, **payload):
        body = {"category": "salud-sexual", **payload}
        return (client or self.trainer()).post("/api/admin/dataset/links", json=body)

    def link_token(self, response):
        """The token exists ONLY inside the one-time URL fragment of the creation response."""
        return response.json()["url"].split("#", 1)[1]

    def bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def public_get(self, token):
        return self.client(None).get("/api/public/dataset/link", headers=self.bearer(token))

    def public_upload(self, token, files):
        return self.client(None).post("/api/public/dataset/images", files=files, headers=self.bearer(token))

    def test_dataset_links_create_stores_only_the_hash_and_shows_the_url_once(self):
        import dataset_links
        self.links_env()
        trainer = self.trainer()
        created = self.create_dataset_link(trainer)
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        self.assertRegex(payload["url"], r"^https://testserver/captura#[A-Za-z0-9_-]{32,}$")
        token = self.link_token(created)
        self.assertGreaterEqual(len(token), 32)
        self.assertNotIn("token", payload)  # only the URL carries it, and only this once
        self.assertEqual((payload["category"], payload["category_name"]), ("salud-sexual", "Salud sexual"))
        self.assertEqual((payload["max_photos"], payload["photos"], payload["revoked_at"]), (500, 0, None))
        with self.db.get_conn() as conn:
            row = dict(conn.execute("SELECT * FROM management_dataset_links WHERE id = ?", (payload["id"],)).fetchone())
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(row))  # the database never holds a usable URL
        self.assertEqual(row["created_by"], "local-neura")
        listed = trainer.get("/api/admin/dataset/links")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.headers["cache-control"], "no-store")
        self.assertNotIn(token, listed.text)
        self.assertNotIn("url", listed.json()["links"][0])
        with self.db.get_conn() as conn:
            audited = conn.execute("SELECT COUNT(*) AS n FROM management_events WHERE action = 'dataset.link_create'").fetchone()["n"]
        self.assertEqual(audited, 1)

    def test_dataset_links_management_is_training_only(self):
        self.links_env()
        link_id = self.create_dataset_link().json()["id"]
        for role in (None, "admin", "analyst", "replenisher", "viewer"):
            client = self.client(role)
            expected = 401 if role is None else 403
            self.assertEqual(self.create_dataset_link(client).status_code, expected, role)
            self.assertEqual(client.get("/api/admin/dataset/links").status_code, expected, role)
            self.assertEqual(client.post(f"/api/admin/dataset/links/{link_id}/revocar").status_code, expected, role)

    def test_dataset_link_create_validates_category_days_cap_and_store(self):
        self.links_env()
        trainer = self.trainer()
        self.assertIn("categoría", self.create_dataset_link(trainer, category="perfumes").json()["detail"])
        self.assertEqual(self.create_dataset_link(trainer, category="perfumes").status_code, 400)
        for days in (0, 61):
            response = self.create_dataset_link(trainer, days=days)
            self.assertEqual(response.status_code, 400, days)
            self.assertIn("60 días", response.json()["detail"])
        for max_photos in (0, 5001):
            self.assertEqual(self.create_dataset_link(trainer, max_photos=max_photos).status_code, 400, max_photos)
        unknown_store = self.create_dataset_link(trainer, store_id="L999")
        self.assertEqual(unknown_store.status_code, 400)
        self.assertIn("PDV", unknown_store.json()["detail"])
        with self.db.get_conn() as conn:
            conn.execute("INSERT INTO management_stores (code,name,created_at,updated_at) VALUES ('L128','Local 128',?,?)",
                         (self.db.now_iso(), self.db.now_iso()))
        bounds = self.create_dataset_link(trainer, store_id="L128", days=60, max_photos=5000)
        self.assertEqual(bounds.status_code, 201, bounds.text)
        self.assertEqual((bounds.json()["store_id"], bounds.json()["max_photos"]), ("L128", 5000))
        # Defaults: 14 days and 500 photos, so a forgotten link dies on its own.
        from datetime import datetime, timedelta, timezone
        default = self.create_dataset_link(trainer).json()
        expires = datetime.fromisoformat(default["expires_at"])
        self.assertAlmostEqual((expires - datetime.now(timezone.utc)) / timedelta(days=1), 14, delta=0.1)

    def test_public_link_info_returns_only_label_and_remaining_count(self):
        calls = []
        self.links_env(calls)
        token = self.link_token(self.create_dataset_link(max_photos=3))
        kilby_calls = calls.count("/v1/neuravision/catalogs")  # creation resolved the active list
        info = self.public_get(token)
        self.assertEqual(info.status_code, 200, info.text)
        self.assertEqual(info.headers["cache-control"], "no-store")
        # EXACT shape: the public surface must never grow extra fields by accident.
        self.assertEqual(info.json(), {"category": "Salud sexual", "photos_left": 3})
        self.public_upload(token, [("files", ("a.jpg", image_bytes("JPEG"), "image/jpeg"))])
        self.assertEqual(self.public_get(token).json(), {"category": "Salud sexual", "photos_left": 2})
        # The public routes never call Kilby: the sweep works in the field even with Kilby down.
        self.assertEqual(calls.count("/v1/neuravision/catalogs"), kilby_calls)
        self.assertEqual(self.client(None).get("/api/public/dataset/link").status_code, 401)
        self.assertEqual(self.public_get("short").status_code, 401)
        self.assertEqual(self.public_get("A" * 43).status_code, 401)

    def test_public_upload_stores_bytes_verbatim_and_attributable(self):
        self.links_env()
        with self.db.get_conn() as conn:
            conn.execute("INSERT INTO management_stores (code,name,created_at,updated_at) VALUES ('L128','Local 128',?,?)",
                         (self.db.now_iso(), self.db.now_iso()))
        created = self.create_dataset_link(store_id="L128")
        link_id, token = created.json()["id"], self.link_token(created)
        heic, jpeg = image_bytes("HEIF", size=(320, 240)), image_bytes("JPEG")
        response = self.public_upload(token, [
            ("files", ("IMG_0001.HEIC", heic, "image/heic")),
            # A lying filename/content type must not matter: the bytes are sniffed, stored untouched.
            ("files", ("renamed.png", jpeg, "image/png")),
        ])
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json(), {"ok": True, "created": 2, "photos_left": 498})
        with self.db.get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM management_dataset_images ORDER BY mime").fetchall()]
        self.assertEqual(len(rows), 2)
        for row, uploaded in zip(rows, (heic, jpeg)):  # heic/heif sorts before jpeg
            path = Path(self.db.DATA_DIR) / row["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(uploaded).hexdigest())
            self.assertEqual((row["category"], row["store_id"], row["created_by"]),
                             ("salud-sexual", "L128", "link:" + link_id[:8]))
        self.storage.put.assert_not_called()  # verbatim also means outside the readings/S3 pipeline
        with self.db.get_conn() as conn:
            events = conn.execute("SELECT after_json FROM management_events WHERE action = 'dataset.link_upload'").fetchall()
        self.assertEqual(len(events), 1)  # ONE event per batch, not per photo
        self.assertEqual(json.loads(events[0]["after_json"])["count"], 2)
        # The swept photos surface in the existing Dataset images screen and in the links listing.
        trainer = self.trainer()
        listed = trainer.get("/api/admin/dataset/images?category=salud-sexual").json()["images"]
        self.assertEqual({i["created_by"] for i in listed}, {"link:" + link_id[:8]})
        self.assertEqual(trainer.get("/api/admin/dataset/links").json()["links"][0]["photos"], 2)

    def test_public_upload_rejects_expired_revoked_full_and_bad_files(self):
        import dataset_api
        self.links_env()
        trainer = self.trainer()
        jpeg = image_bytes("JPEG")
        one = lambda name="a.jpg": [("files", (name, jpeg, "image/jpeg"))]
        # Revoked: the management screen turned it off; the phone gets a polite 410.
        revoked = self.create_dataset_link(trainer)
        self.assertIsNotNone(trainer.post(f"/api/admin/dataset/links/{revoked.json()['id']}/revocar").json()["revoked_at"])
        self.assertEqual(self.public_get(self.link_token(revoked)).status_code, 410)
        self.assertEqual(self.public_upload(self.link_token(revoked), one()).status_code, 410)
        self.assertEqual(trainer.post("/api/admin/dataset/links/no-such-link/revocar").status_code, 404)
        # Expired: the stored timestamp is the truth, no cron needed.
        expired = self.create_dataset_link(trainer)
        with self.db.get_conn() as conn:
            conn.execute("UPDATE management_dataset_links SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
                         (expired.json()["id"],))
        response = self.public_upload(self.link_token(expired), one())
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"], "Este enlace ya no está activo.")
        # max_photos holds ACROSS batches, not per request.
        capped = self.create_dataset_link(trainer, max_photos=3)
        token = self.link_token(capped)
        self.assertEqual(self.public_upload(token, one() + one("b.jpg")).status_code, 201)
        blocked = self.public_upload(token, one() + one("b.jpg"))
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("1 foto", blocked.json()["detail"])
        self.assertEqual(self.public_upload(token, one()).json()["photos_left"], 0)
        full = self.public_upload(token, one())
        self.assertEqual(full.status_code, 409)
        self.assertIn("máximo", full.json()["detail"])
        self.assertEqual(self.public_get(token).json()["photos_left"], 0)  # the page can still explain itself
        # Same file rules as the private endpoint: sniffed bytes, 40 MB, 1-12 files, free disk.
        fresh_created = self.create_dataset_link(trainer)
        fresh = self.link_token(fresh_created)
        self.assertEqual(self.public_upload(fresh, [("files", (f"a{i}.jpg", jpeg, "image/jpeg")) for i in range(13)]).status_code, 400)
        not_an_image = self.public_upload(fresh, one() + [("files", ("notes.txt", b"plain text, not a photo", "image/jpeg"))])
        self.assertEqual(not_an_image.status_code, 400)
        self.assertIn("JPEG, PNG, WebP o HEIC", not_an_image.json()["detail"])
        with patch.object(dataset_api, "MAX_BYTES_EACH", 2048):
            self.assertEqual(self.public_upload(fresh, one()).status_code, 413)
        usage = types.SimpleNamespace(total=10 ** 12, used=10 ** 12 - 100 * 1024 * 1024, free=100 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=usage):
            self.assertEqual(self.public_upload(fresh, one()).status_code, 507)
        # Every rejected batch is all-or-nothing: no rows and no files for this link.
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM management_dataset_images WHERE created_by = ?",
                                          ("link:" + fresh_created.json()["id"][:8],)).fetchone()["n"], 0)
        stored = [p for p in (Path(self.db.DATA_DIR) / "dataset").rglob("*") if p.is_file()]
        self.assertEqual(len(stored), 3)  # only the capped link's three photos ever reached the disk

    def test_public_rate_limit_counts_per_token(self):
        import dataset_links
        self.links_env()
        trainer = self.trainer()
        first = self.link_token(self.create_dataset_link(trainer))
        second = self.link_token(self.create_dataset_link(trainer))
        with patch.object(dataset_links, "RATE_PER_MINUTE", 3):
            for _ in range(3):
                self.assertEqual(self.public_get(first).status_code, 200)
            throttled = self.public_get(first)
            self.assertEqual(throttled.status_code, 429)
            self.assertEqual(throttled.headers["retry-after"], "30")
            self.assertIn("Espera un minuto", throttled.json()["detail"])
            # Another link keeps working: the limiter is per token, not global.
            self.assertEqual(self.public_get(second).status_code, 200)
            # Unknown tokens burn their own budget too: no cheap brute force of the 401 path.
            for _ in range(3):
                self.assertEqual(self.public_get("B" * 43).status_code, 401)
            self.assertEqual(self.public_get("B" * 43).status_code, 429)
