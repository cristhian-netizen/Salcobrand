"""Start the existing application on Kilby's persistent volume."""
import os
import hashlib
from pathlib import Path
import tempfile
import urllib.request
from urllib.parse import urlsplit

from data_bundle import restore_data
from bootstrap import receive_snapshot


def restore_snapshot():
    data = Path(os.environ.get("DATA_DIR", "/data/app"))
    if (data / "data.db").exists():
        return
    url = os.environ.get("SALCOBRAND_DATA_ARCHIVE_URL", "")
    expected = os.environ.get("SALCOBRAND_DATA_ARCHIVE_SHA256", "")
    if not url:
        receive_snapshot(data, int(os.environ.get("PORT", "8080")))
        return
    if urlsplit(url).scheme != "https" or len(expected) != 64:
        raise RuntimeError("Configure the private HTTPS snapshot URL and SHA-256 for the initial import.")
    data.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data.parent) as folder:
        archive = Path(folder) / "snapshot.tar.gz"
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 1024 * 1024 * 1024:
                    raise RuntimeError("The snapshot exceeds the 1 GB initial-transfer limit.")
                output.write(chunk)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise RuntimeError("The snapshot SHA-256 does not match.")
        restore_data(archive, data)


def main():
    required = ("DATABASE_URL", "SESSION_SECRET", "REGISTRATION_CODE", "NEURAVISION_REMOTE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing deployment variables: " + ", ".join(missing))
    if not os.environ["DATABASE_URL"].startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must point to the Kilby PostgreSQL database.")
    if len(os.environ["SESSION_SECRET"]) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters.")
    restore_snapshot()
    import db

    # Local data is imported by the existing transactional SQLite-to-Postgres
    # migration. An empty deployment must not receive the original demo seed.
    db.PLANOGRAM_SEED_PATH = Path(db.DATA_DIR) / "no-default-planograms.json"
    import main as application
    import uvicorn

    uvicorn.run(application.app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                workers=1, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
