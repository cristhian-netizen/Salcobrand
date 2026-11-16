"""Receive one authenticated data snapshot before the application starts."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import secrets
import tempfile
import tarfile
from pathlib import Path

from data_bundle import restore_data

MAX_BYTES = 1024 * 1024 * 1024


def receive_snapshot(destination, port):
    token = os.environ.get("SALCOBRAND_BOOTSTRAP_TOKEN", "")
    expected = os.environ.get("SALCOBRAND_DATA_ARCHIVE_SHA256", "")
    if len(token) < 32 or len(expected) != 64:
        raise RuntimeError("Configure SALCOBRAND_BOOTSTRAP_TOKEN and SALCOBRAND_DATA_ARCHIVE_SHA256 for the initial transfer.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "awaiting_initial_data"})
                return
            self.reply(503, {"detail": "Initial data transfer pending."})

        def do_POST(self):
            self.close_connection = True
            if self.path != "/api/bootstrap" or not secrets.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(403, {"detail": "Unauthorized."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BYTES:
                self.reply(413, {"detail": "Invalid snapshot size."})
                return
            self.connection.settimeout(120)
            try:
                with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
                    archive = Path(folder) / "snapshot.tar.gz"
                    remaining, checksum = length, hashlib.sha256()
                    with archive.open("wb") as output:
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise ValueError("Incomplete snapshot.")
                            output.write(chunk)
                            checksum.update(chunk)
                            remaining -= len(chunk)
                    if not secrets.compare_digest(checksum.hexdigest(), expected):
                        raise ValueError("Snapshot checksum mismatch.")
                    result = restore_data(archive, destination)
            except (ValueError, OSError, EOFError, tarfile.TarError):
                self.reply(400, {"detail": "Snapshot validation failed."})
                return
            self.reply(200, {"restored_files": result["restored_files"]})
            self.server.completed = True

    # The application replaces this receiver as soon as the snapshot is restored.
    with HTTPServer(("0.0.0.0", port), Handler) as server:
        server.completed = False
        print("[bootstrap] Waiting for the authenticated initial snapshot.", flush=True)
        while not server.completed:
            server.handle_request()
