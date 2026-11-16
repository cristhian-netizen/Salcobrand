"""Run the actual local application with the remote development analysis API."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "backend"))


def document_credentials(path):
    from pypdf import PdfReader
    for page in PdfReader(path).pages:
        text = page.extract_text(extraction_mode="layout") or ""
        for line in text.splitlines():
            if re.match(r"\s*dev-admin\s", line):
                cells = re.split(r"\s{2,}", line.strip())
                if len(cells) >= 3:
                    return cells[0], cells[2]
    raise ValueError("No se encontró el acceso de la aplicación de desarrollo en el documento.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--access-document", type=Path)
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    data = ROOT / ".local" / "capture-dev"
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update({"DATA_DIR": str(data), "DATABASE_URL": "", "DB_HOST": "", "PHOTOS_BUCKET": "", "JOBS_QUEUE_URL": "",
                       "APIS_STORE": "memory", "APIS_CW_METRICS": "0", "ROLE": "all", "NEURAVISION_WARMUP": "0",
                       "NEURAVISION_ANALYSIS_BACKEND": "remote", "NEURAVISION_ENVIRONMENT": "capture-dev"})
    os.environ.setdefault("NEURAVISION_REMOTE_URL", "https://salcobrand-dev.neuramorphic.ai")
    namespace = hashlib.sha256(str(data.resolve()).encode()).hexdigest()[:8]
    os.environ.setdefault("NEURAVISION_REMOTE_POINT_PREFIX", "MIGLOCAL-" + namespace + "-")
    if args.access_document:
        username, password = document_credentials(args.access_document)
        os.environ["NEURAVISION_REMOTE_USERNAME"] = username
        os.environ["NEURAVISION_REMOTE_PASSWORD"] = password
    if not os.environ.get("NEURAVISION_REMOTE_USERNAME") or not os.environ.get("NEURAVISION_REMOTE_PASSWORD"):
        parser.error("Configura el acceso de servidor o proporciona --access-document.")
    import db
    db.PLANOGRAM_SEED_PATH = data / "no-default-planograms.json"
    import main as application
    import auth
    import infrastructure
    for username, role, stores in (("local-admin", "admin", []), ("local-analyst", "analyst", ["L128", "L129", "PDV-001"]),
                                    ("local-replenisher", "replenisher", ["L128", "L129", "PDV-001"]), ("local-viewer", "viewer", [])):
        if not db.user_exists(username):
            hashed, salt = auth.hash_password("Isolated-local-password-2026!")
            db.create_user(username, hashed, salt, role=role, store_ids=stores)
    if not any(s["code"] == "PDV-001" for s in infrastructure.list_stores(include_deleted=True)):
        infrastructure.save_store({"code": "PDV-001", "name": "PDV-001 · Captura de desarrollo", "store_type": "Farmacia",
            "region": "Metropolitana de Santiago", "commune": "Santiago", "address": "Prueba local de migración",
            "manager": "Prueba de desarrollo", "status": "Activo"}, "local-admin")
    if not db.point_exists("pdv-001"):
        db.create_point("pdv-001", "PDV-001 · Góndola de prueba", store_id="PDV-001", gondola_id="G1")
    import client_identity
    client_identity.seed_local_operator()
    import api_jobs
    api_jobs.start_worker()
    import uvicorn
    print(f"Captura local con API real de desarrollo: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(application.app, host="127.0.0.1", port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
