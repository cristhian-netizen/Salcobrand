"""Neuravision on Kilby client against a fake Kilby gateway (real HTTP on 127.0.0.1, no network, no cloud).

Run: python -m unittest discover -s app/backend/tests -v   (or: pytest app/backend/tests/test_kilby_neuravision.py)
The fake follows Kilby's documented contract (https://kilby.neuramorphic.ai/docs/neuravision): plan check before the
form is read, 202 job / 200 finished job, error bodies {"error": {"message", "type", "code", "param"}}.
"""
import email.parser
import email.policy
import json
import logging
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kilby_neuravision as kn  # noqa: E402

KEY = "kai_" + "T3stOnlyKey" * 4
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000


class FakeKilby:
    """Scripted gateway. `analyze_script`: list of (status, body, headers) answered in order, then a 202 job."""

    def __init__(self):
        self.plan_active = True
        self.analyze_script = []
        self.polls_until_done = 2
        self.final = {"status": "done"}
        self.post_delay = 0.0
        self.requests = []
        self.jobs = {}
        self.lock = threading.Lock()
        # dataset API (contract 2026-11-18)
        self.dataset_allowed = True
        self.trainings_left = 1
        self.catalogs = {"salud-sexual": {"slug": "salud-sexual", "name": "Salud sexual", "products": {}, "labels": [],
                                          "trainings": {}, "versions": [{"version": "v1-202611180000", "top1": 0.81, "top3": 0.93,
                                                                         "products": 84, "seeded": True, "published": True}]}}
        self.page_size = 2
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Kilby-Request-Id", "req-test")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                header = self.headers.get("Authorization", "")
                if not header.startswith("Bearer "):
                    self._send(401, {"error": {"message": "send your Kilby AI key", "type": "authentication_error", "code": "missing_key"}})
                    return False
                if header != "Bearer " + KEY:
                    self._send(401, {"error": {"message": "unknown or revoked key", "type": "authentication_error", "code": "invalid_key"}})
                    return False
                return True

            def _form(self, raw):
                ctype = self.headers.get("Content-Type", "")
                fields, files = {}, []
                if ctype.startswith("multipart/form-data"):
                    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        payload = part.get_payload(decode=True) or b""
                        if part.get_filename() is not None:
                            files.append((name, payload))
                        else:
                            fields[name] = payload.decode()
                elif ctype.startswith("application/json") and raw:
                    fields = json.loads(raw)
                return fields, files

            def _dataset(self, method, raw):
                from urllib.parse import parse_qs, unquote, urlsplit
                url = urlsplit(self.path)
                parts = [unquote(p) for p in url.path.split("/")[4:]]  # after /v1/neuravision/catalogs
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if not fake.dataset_allowed:
                    return self._send(403, {"error": {"type": "permission_error", "code": "dataset_not_allowed", "message": "this key may not manage catalogs"}})
                with fake.lock:
                    if not parts and method == "GET":
                        return self._send(200, {"object": "list", "data": [
                            {"slug": c["slug"], "name": c["name"], "products": len(c["products"]),
                             "photos": sum(p["photos"] for p in c["products"].values()), "trainings_left": fake.trainings_left,
                             "published_version": next(({k: v[k] for k in ("version", "top1", "top3", "products", "seeded")}
                                                        for v in c["versions"] if v["published"]), None)}
                            for c in fake.catalogs.values()]})
                    if not parts and method == "POST":
                        body = json.loads(raw)
                        if body["slug"] in fake.catalogs:
                            return self._send(409, {"error": {"type": "invalid_request_error", "code": "catalog_exists", "message": "exists"}})
                        fake.catalogs[body["slug"]] = {"slug": body["slug"], "name": body["name"], "products": {}, "labels": [], "trainings": {}, "versions": []}
                        return self._send(201, {"slug": body["slug"], "name": body["name"]})
                    cat = fake.catalogs.get(parts[0])
                    if cat is None:
                        return self._send(404, {"error": {"type": "invalid_request_error", "code": "catalog_not_found", "message": "no catalog"}})
                    rest = parts[1:]
                    if rest == ["products"] and method == "GET":
                        skus = sorted(cat["products"])
                        start = int(query.get("cursor") or 0)
                        page = skus[start:start + fake.page_size]
                        following = str(start + fake.page_size) if start + fake.page_size < len(skus) else None
                        return self._send(200, {"object": "list", "data": [cat["products"][k] for k in page], "next_cursor": following})
                    if len(rest) == 2 and rest[0] == "products" and method == "PUT":
                        fields, files = self._form(raw)
                        product = cat["products"].get(rest[1])
                        created = product is None
                        photos = len(files) if files else (product or {}).get("photos", 0)
                        cat["products"][rest[1]] = {"sku": rest[1], "name": fields["name"], "brand": fields.get("brand"),
                                                    "category": fields.get("category"), "photos": photos, "updated_at": "2026-11-19T02:00:00Z",
                                                    "photo_bytes": [f[1] for f in files] if files else (product or {}).get("photo_bytes", [])}
                        return self._send(201 if created else 200, {k: v for k, v in cat["products"][rest[1]].items() if k != "photo_bytes"})
                    if len(rest) == 2 and rest[0] == "products" and method == "DELETE":
                        if cat["products"].pop(rest[1], None) is None:
                            return self._send(404, {"error": {"type": "invalid_request_error", "code": "not_found", "message": "no product"}})
                        self.send_response(204)
                        self.end_headers()
                        return
                    if rest == ["labels"] and method == "POST":
                        lines = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
                        good = [l for l in lines if l["job_id"] in fake.jobs and l["sku"] in cat["products"]]
                        cat["labels"] = good
                        return self._send(200, {"accepted": len(good), "skipped": len(lines) - len(good)})
                    if rest == ["trainings"] and method == "POST":
                        if fake.trainings_left <= 0:
                            return self._send(429, {"error": {"type": "rate_limit_error", "code": "training_quota", "message": "no trainings left", "retry_after": 86400}})
                        fake.trainings_left -= 1
                        tid = "tr_%04d" % (len(cat["trainings"]) + 1)
                        cat["trainings"][tid] = {"id": tid, "status": "queued", "polls": 0}
                        return self._send(202, {"id": tid, "status": "queued"})
                    if len(rest) == 2 and rest[0] == "trainings" and method == "GET":
                        tr = cat["trainings"].get(rest[1])
                        if tr is None:
                            return self._send(404, {"error": {"type": "invalid_request_error", "code": "not_found", "message": "no training"}})
                        tr["polls"] += 1
                        body = {"id": tr["id"], "status": "running" if tr["polls"] < 2 else "done"}
                        if body["status"] == "done":
                            body.update({"metrics": {"top1": 0.84, "top3": 0.95, "skus": len(cat["products"])},
                                         "baseline": {"top1": 0.81, "top3": 0.93}, "version": "v2-202611190300", "published": True, "error": None})
                        return self._send(200, body)
                    if rest == ["versions"] and method == "GET":
                        return self._send(200, {"object": "list", "data": cat["versions"]})
                    if len(rest) == 3 and rest[0] == "versions" and rest[2] == "publish" and method == "POST":
                        found = [v for v in cat["versions"] if v["version"] == rest[1]]
                        if not found:
                            return self._send(404, {"error": {"type": "invalid_request_error", "code": "not_found", "message": "no version"}})
                        for v in cat["versions"]:
                            v["published"] = v["version"] == rest[1]
                        return self._send(200, {"version": rest[1], "published": True})
                self._send(404, {"error": {"type": "invalid_request_error", "message": "not found"}})

            def _body_and_auth(self, method):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                with fake.lock:
                    fake.requests.append((method, self.path, dict(self.headers), raw))
                return raw if self._auth() else None

            def do_PUT(self):
                raw = self._body_and_auth("PUT")
                if raw is not None:
                    self._dataset("PUT", raw)

            def do_DELETE(self):
                raw = self._body_and_auth("DELETE")
                if raw is not None:
                    self._dataset("DELETE", raw)

            def do_GET(self):
                with fake.lock:
                    fake.requests.append(("GET", self.path, dict(self.headers), None))
                if not self._auth():
                    return
                if self.path.startswith("/v1/neuravision/catalogs"):
                    return self._dataset("GET", b"")
                if "/crops/" in self.path and self.path.startswith("/v1/neuravision/jobs/"):
                    parts = self.path.split("/")  # /v1/neuravision/jobs/<id>/crops/<image>/<item>.jpg
                    with fake.lock:
                        job = fake.jobs.get(parts[4])
                    if job is None:
                        return self._send(404, {"error": {"message": "no job with this id", "type": "invalid_request_error", "code": "not_found"}})
                    if job["body"].get("status") != "done":
                        return self._send(409, {"error": {"message": "the job has not finished", "type": "invalid_request_error", "code": "job_not_done"}})
                    image, item = int(parts[6]), int(parts[7].split(".")[0])
                    if image >= job["body"].get("photos", 0) or item >= 50:
                        return self._send(404, {"error": {"message": "no crop at this index", "type": "invalid_request_error", "code": "not_found"}})
                    data = b"\xff\xd8\xffcrop-%d-%d" % (image, item)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "private, max-age=86400")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if self.path.startswith("/v1/neuravision/jobs/"):
                    job_id = self.path.rsplit("/", 1)[1]
                    with fake.lock:
                        job = fake.jobs.get(job_id)
                        if job is None:
                            return self._send(404, {"error": {"message": "no job with this id", "type": "invalid_request_error", "code": "not_found"}})
                        job["polls"] += 1
                        if job["polls"] >= fake.polls_until_done:
                            job["body"].update(fake.final)
                        elif job["polls"] >= 1:
                            job["body"]["status"] = "running"
                        body = dict(job["body"])
                    return self._send(200, body)
                if self.path.startswith("/v1/neuravision/jobs"):
                    return self._send(200, {"object": "list", "data": []})
                self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

            def do_POST(self):
                if self.path.startswith("/v1/neuravision/catalogs"):
                    raw = self._body_and_auth("POST")
                    if raw is not None:
                        self._dataset("POST", raw)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                ctype = self.headers.get("Content-Type", "")
                fields, images = {}, []
                if ctype.startswith("multipart/form-data"):
                    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        payload = part.get_payload(decode=True) or b""
                        if name == "images":
                            images.append(payload)
                        else:
                            fields[name] = payload.decode()
                with fake.lock:
                    fake.requests.append(("POST", self.path, dict(self.headers), {"fields": fields, "images": images}))
                if not self._auth():
                    return
                if not fake.plan_active:
                    return self._send(403, {"error": {"message": "Neuravision is not active for this workspace", "type": "permission_error", "code": "vision_not_enabled"}})
                if fake.post_delay:
                    time.sleep(fake.post_delay)
                with fake.lock:
                    scripted = fake.analyze_script.pop(0) if fake.analyze_script else None
                if scripted:
                    return self._send(*scripted)
                if not ctype.startswith("multipart/form-data"):
                    return self._send(400, {"error": {"message": "send the photos as multipart/form-data", "type": "invalid_request_error", "code": "invalid_request"}})
                if not images:
                    return self._send(400, {"error": {"message": "send 1 to 6 photos", "type": "invalid_request_error", "code": "invalid_request", "param": "images"}})
                with fake.lock:
                    job_id = "vjob_%04d" % (len(fake.jobs) + 1)
                    body = {"id": job_id, "object": "neuravision.job", "status": "queued", "photos": len(images),
                            "catalog": fields.get("catalog") or "salud-sexual", "created_at": "2026-11-19T01:00:00Z",
                            "finished_at": None, "billed": False, "poll": "/v1/neuravision/jobs/" + job_id}
                    fake.jobs[job_id] = {"body": body, "polls": 0}
                if fields.get("wait"):
                    body = {**body, **fake.final, "finished_at": "2026-11-19T01:00:09Z"}
                    if body["status"] == "done":
                        body.update({"billed": True, "engine_ms": 6100, "result_available": True, "result": RESULT})
                    return self._send(200, body)
                self._send(202, body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def posts(self):
        return [r for r in self.requests if r[0] == "POST" and r[1].startswith("/v1/neuravision/analyze")]


RESULT = {"total_facings": 12, "shelf_levels_detected": 2, "empty_space_pct": 4.5, "needs_review": 1, "categories": ["Salud sexual"],
          "products": [{"product": "Producto A", "brand": "Marca", "sku": "780000000001", "facings": 3, "shelf_level": 1,
                        "position_index": 1, "match_status": "match", "confidence": 0.91, "needs_review": False,
                        "image_index": 0, "item_index": 2}]}


class KilbyNeuravisionClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKilby()
        self.addCleanup(self.fake.close)
        self.sleeps = []
        self.client = kn.KilbyNeuravision(KEY, self.fake.url, sleep=self.sleeps.append)
        self.addCleanup(self.client.close)

    def test_analyze_then_poll_until_done(self):
        self.fake.final = {"status": "done", "billed": True, "engine_ms": 7000, "result_available": True, "result": RESULT}
        job = self.client.analyze([kn.Photo(JPEG, filename="a.jpg"), JPEG], "PDV-001", "SB-INF-3F05DC9DAFCC4199",
                                  catalog="salud-sexual", name="Góndola 1", linear_meters=1.2)
        self.assertEqual((job.status, job.photos), ("queued", 2))
        done = self.client.wait_for(job)
        self.assertEqual(done.status, "done")
        self.assertTrue(done.billed)
        self.assertEqual(done.result["products"][0]["sku"], "780000000001")
        _, path, headers, body = self.fake.posts()[0]
        self.assertEqual(path, "/v1/neuravision/analyze")
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertEqual(body["fields"], {"store_id": "PDV-001", "gondola_id": "SB-INF-3F05DC9DAFCC4199",
                                          "catalog": "salud-sexual", "name": "Góndola 1", "linear_meters": "1.2"})
        self.assertEqual(len(body["images"]), 2)
        self.assertEqual(body["images"][0], JPEG)
        self.assertGreaterEqual(len(self.sleeps), 1)  # polled with a pause, never in a tight loop

    def test_wait_answers_finished_job_in_one_request(self):
        self.fake.final = {"status": "done"}
        job = self.client.analyze([JPEG], "PDV-001", "G1", wait=99)  # capped at 25
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result["total_facings"], 12)
        self.assertEqual(self.fake.posts()[0][3]["fields"]["wait"], "25")
        self.assertEqual(len(self.fake.requests), 1)

    def test_rate_limit_is_retried_respecting_retry_after(self):
        self.fake.analyze_script = [(429, {"error": {"message": "this key may make 60 requests a minute", "type": "rate_limit_error", "code": "rate_limit"}}, {"Retry-After": "2"})]
        job = self.client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(job.status, "queued")
        self.assertEqual(len(self.fake.posts()), 2)
        self.assertEqual(self.sleeps, [2.0])

    def test_photo_caps_are_not_retried(self):
        self.fake.analyze_script = [(429, {"error": {"message": "the workspace reached its monthly photo cap", "type": "rate_limit_error", "code": "workspace_monthly_photos"}}, {})]
        with self.assertRaises(kn.RateLimitError) as caught:
            self.client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "workspace_monthly_photos")
        self.assertIn("tope mensual", caught.exception.message_es)
        self.assertEqual(len(self.fake.posts()), 1)

    def test_busy_is_retried_then_reported(self):
        busy = (503, {"error": {"message": "Neuravision is receiving many photos right now", "type": "api_error", "code": "busy"}}, {"Retry-After": "1"})
        self.fake.analyze_script = [busy] * 10
        with self.assertRaises(kn.UnavailableError) as caught:
            self.client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "busy")
        self.assertEqual(len(self.fake.posts()), self.client.max_retries + 1)
        self.assertIn("No se cobró", caught.exception.message_es)

    def test_broken_connection_after_sending_is_ambiguous_and_never_resent(self):
        self.fake.post_delay = 1.0
        http = httpx.Client(timeout=httpx.Timeout(0.3), trust_env=False)
        self.addCleanup(http.close)
        client = kn.KilbyNeuravision(KEY, self.fake.url, client=http, sleep=self.sleeps.append)
        with self.assertRaises(kn.AmbiguousSubmitError) as caught:
            client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "ambiguous_submit")
        time.sleep(1.2)
        self.assertEqual(len(self.fake.posts()), 1)

    def test_unreachable_kilby_is_retried_because_nothing_was_sent(self):
        client = kn.KilbyNeuravision(KEY, "http://127.0.0.1:9/v1", sleep=self.sleeps.append, max_retries=2)
        self.addCleanup(client.close)
        with self.assertRaises(kn.UnavailableError) as caught:
            client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "network")
        self.assertEqual(len(self.sleeps), 2)

    def test_key_errors_are_typed_and_the_key_never_leaks(self):
        other = "kai_" + "Wr0ngKeyValue" * 3
        client = kn.KilbyNeuravision(other, self.fake.url, sleep=self.sleeps.append)
        self.addCleanup(client.close)
        with self.assertLogs("kilby_neuravision", level="DEBUG") as logs:
            logging.getLogger("kilby_neuravision").debug("marker")
            with self.assertRaises(kn.AuthError) as caught:
                client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "invalid_key")
        for text in (str(caught.exception), repr(caught.exception), repr(client), caught.exception.message_es, "\n".join(logs.output)):
            self.assertNotIn(other, text)
            self.assertNotIn(other[4:], text)
        self.assertEqual(len(self.fake.posts()), 1)  # auth errors are never retried
        with self.assertRaises(kn.AuthError):
            kn.KilbyNeuravision("sk-not-kilby", self.fake.url)

    def test_inactive_plan_is_its_own_error(self):
        self.fake.plan_active = False
        with self.assertRaises(kn.NotEnabledError) as caught:
            self.client.analyze([JPEG], "PDV-001", "G1")
        self.assertEqual(caught.exception.code, "vision_not_enabled")
        self.assertIn("plan activo", caught.exception.message_es)

    def test_failed_job_carries_spanish_reason(self):
        self.fake.final = {"status": "failed", "error": {"code": "analysis_rejected", "message": "the engine found no shelf"}}
        job = self.client.wait_for(self.client.analyze([JPEG], "PDV-001", "G1"))
        self.assertEqual((job.status, job.error_code, job.billed), ("failed", "analysis_rejected", False))
        self.assertIn("No se cobró", job.error_es)

    def test_wait_for_gives_up_at_deadline_with_last_state(self):
        self.fake.polls_until_done = 10_000
        now = [0.0]
        client = kn.KilbyNeuravision(KEY, self.fake.url, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        self.addCleanup(client.close)
        job = client.analyze([JPEG], "PDV-001", "G1")
        with self.assertRaises(kn.JobTimeoutError) as caught:
            client.wait_for(job, timeout=30)
        self.assertEqual(caught.exception.job.status, "running")
        self.assertEqual(caught.exception.job.id, job.id)
        self.assertLessEqual(len([r for r in self.fake.requests if r[0] == "GET"]), 12)  # backoff, not a tight loop

    def test_crops_of_a_finished_job_are_served_with_the_key(self):
        self.fake.final = {"status": "done", "billed": True, "result_available": True, "result": RESULT}
        job = self.client.wait_for(self.client.analyze([kn.Photo(JPEG), kn.Photo(JPEG)], "PDV-001", "G1"))
        self.assertEqual(self.client.crop(job.id, 1, 3), b"\xff\xd8\xffcrop-1-3")
        with self.assertRaises(kn.InvalidRequestError) as caught:
            self.client.crop(job.id, 5, 0)  # index out of range
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(kn.InvalidRequestError) as caught:
            self.client.crop("vjob_missing", 0, 0)
        self.assertEqual(caught.exception.code, "not_found")
        running = self.client.analyze([JPEG], "PDV-001", "G1")  # queued: crops only exist when the job is done
        with self.assertRaises(kn.InvalidRequestError) as caught:
            self.client.crop(running.id, 0, 0)
        self.assertEqual(caught.exception.code, "job_not_done")
        self.assertIn("proceso", caught.exception.message_es)
        requests_before = len(self.fake.requests)
        with self.assertRaises(kn.InvalidRequestError):
            self.client.crop(job.id, -1, 0)  # refused client-side
        self.assertEqual(len(self.fake.requests), requests_before)

    def test_connection_check_sends_no_photo(self):
        result = self.client.check()
        self.assertTrue(result.ok and result.key_valid and result.plan_active, result)
        self.assertEqual([body["images"] for *_, body in self.fake.posts()], [[]])
        self.assertEqual(self.fake.jobs, {})
        self.fake.plan_active = False
        result = self.client.check()
        self.assertEqual((result.ok, result.key_valid, result.plan_active, result.code), (False, True, False, "vision_not_enabled"))
        bad = kn.KilbyNeuravision("kai_" + "Wr0ngKeyValue" * 3, self.fake.url, sleep=self.sleeps.append)
        self.addCleanup(bad.close)
        result = bad.check()
        self.assertEqual((result.ok, result.key_valid, result.code), (False, False, "invalid_key"))

    def test_client_side_limits_send_nothing(self):
        cases = [([], "PDV-001", "G1", {}), ([JPEG] * 7, "PDV-001", "G1", {}),
                 ([b"\xff\xd8\xff" + b"0" * (kn.MAX_TOTAL_BYTES + 1)], "PDV-001", "G1", {}),
                 ([JPEG], "PDV 001", "G1", {}), ([JPEG], "PDV-001", "x" * 41, {}),
                 ([JPEG], "PDV-001", "G1", {"catalog": "Salud Sexual"})]
        for photos, store, gondola, kwargs in cases:
            with self.assertRaises(kn.InvalidRequestError):
                self.client.analyze(photos, store, gondola, **kwargs)
        self.assertEqual(self.fake.requests, [])

    def test_url_must_be_https_outside_localhost(self):
        with self.assertRaises(ValueError):
            kn.KilbyNeuravision(KEY, "http://ai.kilby.neuramorphic.ai/v1")
        with self.assertRaises(ValueError):
            kn.KilbyNeuravision(KEY, "https://user:pass@ai.kilby.neuramorphic.ai/v1")



class KilbyDatasetClientTests(unittest.TestCase):
    """Dataset API: depends on Kilby's Neuravision dataset API (contract 2026-11-18, not deployed yet)."""

    def setUp(self):
        self.fake = FakeKilby()
        self.addCleanup(self.fake.close)
        self.sleeps = []
        self.client = kn.KilbyNeuravision(KEY, self.fake.url, sleep=self.sleeps.append)
        self.addCleanup(self.client.close)

    def test_catalogs_and_create(self):
        catalogs = self.client.catalogs()
        self.assertEqual(catalogs[0]["slug"], "salud-sexual")
        self.assertEqual(catalogs[0]["published_version"]["version"], "v1-202611180000")
        self.client.create_catalog("cuidado-personal", "Cuidado personal")
        self.assertEqual({c["slug"] for c in self.client.catalogs()}, {"salud-sexual", "cuidado-personal"})
        with self.assertRaises(kn.InvalidRequestError):
            self.client.create_catalog("Cuidado Personal", "x")

    def test_product_upsert_json_keeps_photos_and_multipart_replaces_them(self):
        photo = kn.Photo(JPEG, "image/jpeg", "front.jpg")
        created = self.client.put_product("salud-sexual", "7801/A 20", "Gel 50 ml", brand="Marca", category="Salud sexual", photos=[photo])
        self.assertEqual((created["sku"], created["photos"]), ("7801/A 20", 1))
        method, path, headers, _ = self.fake.requests[-1]
        self.assertEqual((method, path), ("PUT", "/v1/neuravision/catalogs/salud-sexual/products/7801%2FA%2020"))
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data"))
        self.assertEqual(self.fake.catalogs["salud-sexual"]["products"]["7801/A 20"]["photo_bytes"], [JPEG])
        renamed = self.client.put_product("salud-sexual", "7801/A 20", "Gel 50 ml nuevo")
        self.assertEqual((renamed["name"], renamed["photos"]), ("Gel 50 ml nuevo", 1))
        self.assertEqual(self.fake.requests[-1][2]["Content-Type"], "application/json")
        with self.assertRaises(kn.InvalidRequestError):
            self.client.put_product("salud-sexual", "x" * 65, "Too long")
        with self.assertRaises(kn.InvalidRequestError):
            self.client.put_product("salud-sexual", "A1", "Six photos", photos=[photo] * 6)

    def test_delete_is_idempotent_and_listing_pages(self):
        for sku in ("A1", "A2", "A3"):
            self.client.put_product("salud-sexual", sku, "Producto " + sku)
        self.assertEqual([p["sku"] for p in self.client.iter_products("salud-sexual", limit=2)], ["A1", "A2", "A3"])
        self.assertTrue(self.client.delete_product("salud-sexual", "A2"))
        self.assertFalse(self.client.delete_product("salud-sexual", "A2"))
        self.assertEqual([p["sku"] for p in self.client.iter_products("salud-sexual")], ["A1", "A3"])

    def test_labels_are_json_lines_with_vjob_ids(self):
        self.client.put_product("salud-sexual", "A1", "Producto A1")
        job = self.client.analyze([JPEG], "PDV-001", "G1")
        result = self.client.upload_labels("salud-sexual", [
            {"job_id": job.id, "image_index": 0, "item_index": 3, "sku": "A1"},
            {"job_id": "vjob_unknown", "image_index": 0, "item_index": 1, "sku": "A1"}])
        self.assertEqual(result, {"accepted": 1, "skipped": 1})
        method, path, headers, raw = self.fake.requests[-1]
        self.assertEqual(headers["Content-Type"], "application/x-ndjson")
        self.assertEqual([json.loads(line)["job_id"] for line in raw.decode().splitlines()], [job.id, "vjob_unknown"])

    def test_training_runs_once_reports_metrics_and_quota_is_not_retried(self):
        started = self.client.start_training("salud-sexual")
        self.assertEqual(started["status"], "queued")
        first = self.client.training("salud-sexual", started["id"])
        self.assertEqual(first["status"], "running")
        done = self.client.training("salud-sexual", started["id"])
        self.assertEqual((done["status"], done["metrics"]["top1"], done["baseline"]["top1"]), ("done", 0.84, 0.81))
        with self.assertRaises(kn.RateLimitError) as caught:
            self.client.start_training("salud-sexual")
        self.assertEqual((caught.exception.code, caught.exception.retry_after), ("training_quota", 86400.0))
        self.assertIn("entrenamientos", caught.exception.message_es)
        posts = [r for r in self.fake.requests if r[0] == "POST" and r[1].endswith("/trainings")]
        self.assertEqual(len(posts), 2)
        self.assertEqual(self.sleeps, [])

    def test_versions_and_publish(self):
        self.fake.catalogs["salud-sexual"]["versions"].append({"version": "v2-202611190300", "top1": 0.79, "top3": 0.92,
                                                               "products": 84, "seeded": False, "published": False})
        self.client.publish("salud-sexual", "v2-202611190300")
        published = [v["version"] for v in self.client.versions("salud-sexual") if v["published"]]
        self.assertEqual(published, ["v2-202611190300"])

    def test_key_without_dataset_permission(self):
        self.fake.dataset_allowed = False
        with self.assertRaises(kn.AuthError) as caught:
            self.client.catalogs()
        self.assertEqual(caught.exception.code, "dataset_not_allowed")
        self.assertIn("Manage catalogs and trainings", caught.exception.message_es)


if __name__ == "__main__":
    unittest.main()
