"""Verify the real pilot without submitting another photo or training the remote model."""
import io
import json
import base64
import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3

import httpx
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".local" / "planogram-pilot"


def checked(response):
    response.raise_for_status()
    return response.json()


@contextmanager
def session(username):
    with httpx.Client(base_url="http://localhost:3001", timeout=120) as client:
        checked(client.post("/api/auth/login", json={"username": username, "password": "Isolated-local-password-2026!"}))
        yield client


def main():
    target = OUTPUT / "proof.json"
    proof = json.loads(target.read_text(encoding="utf-8"))
    reading_id = proof["reading_id"]
    with session("local-replenisher") as replenisher, session("local-analyst") as analyst:
        original = checked(analyst.get(f"/api/readings/{reading_id}"))
        assert original["planogram_id"] == proof["local_plan_id"]
        assert original["compliance"]["total_expected_facings"] == 90
        assert len(original["compliance"]["items"]) == 82
        assert original["captured_by"] == "local-replenisher"
        own_history = checked(replenisher.get("/api/measurements?point=pdv-001"))
        assert any(r["id"] == reading_id for r in own_history["rows"])
        assert all(r["captured_by"] == "local-replenisher" for r in own_history["rows"])
        # This crop was visually inspected against the user's photograph before confirmation.
        title = "REXONA DEO AER ANTI TRANSPIRANTE 2X"
        item = next(p for p in original["products"] if p.get("image_index") == 0 and p.get("item_index") == 37)
        assert item["product"] == title
        crop = analyst.get(f"/api/readings/{reading_id}/crops/0/37.jpg")
        crop.raise_for_status()
        (OUTPUT / "confirmed-crop.jpg").write_bytes(crop.content)
        if not proof.get("review_workflow_verified"):
            assert original["review"]["status"] == "En revisión"
            assert not original["review"]["note"], "Preserve any review already written by the user"
            confirmed = checked(analyst.post(f"/api/readings/{reading_id}/confirm", json={"image_index": 0,
                "item_index": 37, "title": title, "facings": item["facings"]}))
            assert confirmed["needs_review"] == original["needs_review"] - int(bool(item["needs_review"]))
            assert confirmed["reading"]["review"]["status"] == "En revisión"
            review = confirmed["reading"]["review"]
            rejected_attempt = replenisher.patch(f"/api/readings/{reading_id}/review",
                json={"status": "Aprobado", "note": "", "version": review["version"]})
            assert rejected_attempt.status_code == 403
            before = checked(analyst.get("/api/reports/measurements?point=pdv-001"))["totals"]
            approved = checked(analyst.patch(f"/api/readings/{reading_id}/review", json={"status": "Aprobado",
                "note": "Validación técnica temporal del circuito de estados.", "version": review["version"]}))
            try:
                report = checked(analyst.get("/api/reports/measurements?point=pdv-001"))
                assert report["totals"]["approved"] == before["approved"] + 1
                assert next(r for r in report["rows"] if r["id"] == reading_id)["performance"] == "Sí"
                rejected = checked(analyst.patch(f"/api/readings/{reading_id}/review", json={"status": "Rechazado",
                    "note": "Validación técnica temporal del rechazo y su exclusión de métricas.", "version": approved["version"]}))
                report = checked(analyst.get("/api/reports/measurements?point=pdv-001"))
                assert report["totals"]["approved"] == before["approved"]
                assert next(r for r in report["rows"] if r["id"] == reading_id)["performance"] == "No"
            finally:
                current = checked(analyst.get(f"/api/readings/{reading_id}"))["review"]
                checked(analyst.patch(f"/api/readings/{reading_id}/review", json={"status": "En revisión",
                    "note": "Piloto técnico con planograma real. Un recorte Rexona 2X fue confirmado visualmente. El resto de las identificaciones requiere revisión del Analista antes de aprobar. Las dimensiones del Excel son simuladas.",
                    "version": current["version"]}))
            proof["review_workflow_verified"] = True
        result = checked(analyst.get(f"/api/readings/{reading_id}"))
        assert result["review"]["status"] == "En revisión"
        report = checked(analyst.get("/api/reports/measurements?point=pdv-001"))
        row = next(r for r in report["rows"] if r["id"] == reading_id)
        assert row["performance"] == "No" and row["captured_by"] == "local-replenisher"
        assert row["store_name"] != row["store_id"] and row["region"] and row["commune"] and row["manager"]
        excel = analyst.get("/api/reports/measurements.xlsx?point=pdv-001")
        excel.raise_for_status()
        (OUTPUT / "pilot-measurements.xlsx").write_bytes(excel.content)
        sheet = load_workbook(io.BytesIO(excel.content)).active
        headers = [c.value for c in sheet[1]]
        assert headers == ["ID", "PDV", "Nombre PDV", "Región", "Comuna", "Fecha", "Hora", "Puntaje", "Estado",
                           "Observación", "Considerar en desempeño", "Medición hecha por", "Encargado de Local"]
        cells = next(cells for cells in sheet.iter_rows(min_row=2) if cells[0].value == reading_id)
        assert cells[6].number_format == 'hh:mm "hrs."'
        assert cells[8].value == "En revisión" and cells[10].value == "No"
        assert replenisher.get("/api/reports/measurements.xlsx").status_code == 403
        with sqlite3.connect((ROOT / ".local/capture-dev/data.db").as_uri() + "?mode=ro", uri=True) as conn:
            snapshot = json.loads(conn.execute("SELECT plan_snapshot_json FROM readings WHERE id = ?", (reading_id,)).fetchone()[0])
            assert snapshot["id"] == proof["local_plan_id"] and len(snapshot["items"]) == 82
            assert sum(i["expected_facings"] for i in snapshot["items"]) == 90
        with session("local-admin") as admin:
            plan = checked(admin.get("/api/admin/catalog/planograms/" + proof["local_plan_id"]))
            document = base64.b64decode(plan["document"].split(",", 1)[1])
            assert hashlib.sha256(document).hexdigest() == proof["document_sha256"]
            assert plan["document_pages"] == 6 and plan["document_page"] == 1
        proof.update({"document_original_verified": True,
                      "final_status": result["review"]["status"], "needs_review_after_confirmation": result["needs_review"],
                      "confirmed_item": {"image_index": 0, "item_index": 37, "title": title},
                      "exports_verified": True, "own_scope_verified": True, "frozen_reference_verified": True})
        target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: proof[key] for key in ("reading_id", "final_status", "needs_review_after_confirmation",
            "exports_verified", "own_scope_verified", "frozen_reference_verified")}))


if __name__ == "__main__":
    main()
