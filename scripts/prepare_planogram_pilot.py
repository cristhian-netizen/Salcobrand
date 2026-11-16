"""Prepare the user's real reference files in the isolated local capture database."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".local" / "planogram-pilot"
DOWNLOADS = Path.home() / "Downloads"
PLAN_ID = "pilot-desodorantes-pdv001"


def checked(response):
    response.raise_for_status()
    return response.json()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    backup = OUTPUT / "before-pilot.sqlite3"
    if not backup.exists():
        with sqlite3.connect((ROOT / ".local/capture-dev/data.db").as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
    reference = json.loads((OUTPUT / "source-plan.json").read_text(encoding="utf-8"))
    excel = DOWNLOADS / "Plantilla_Productos_Completada.xlsx"
    pdf = next(DOWNLOADS.glob("DESODORANTES_MASCULINOS_GB1_BRICK_*.pdf"))
    with httpx.Client(base_url="http://localhost:3001", timeout=120) as client:
        checked(client.post("/api/auth/login", json={"username": "local-admin", "password": "Isolated-local-password-2026!"}))
        source_db = ROOT.parents[1] / "backend" / "db.sqlite3"
        inherited_store = False
        if source_db.exists():
            with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as legacy:
                stores = []
                for row in legacy.execute("SELECT state FROM api_portalworkspace"):
                    stores.extend(s for s in json.loads(row[0]).get("stores", []) if s.get("code") == "PDV-001")
            current = next(s for s in checked(client.get("/api/admin/stores")) if s["code"] == "PDV-001")
            if len(stores) == 1 and current["name"] == current["code"] and not current["region"]:
                original = stores[0]
                checked(client.patch("/api/admin/stores/PDV-001", json={"version": current["version"],
                    "name": original["name"], "store_type": original["type"], "region": original["region"],
                    "commune": original["comuna"], "address": original["address"], "manager": original["manager"],
                    "status": original["status"], "description": original.get("description", "")}))
                inherited_store = True
        catalog = checked(client.get("/api/admin/catalog"))
        products = {p["sku"]: p for p in catalog["products"]}
        if not products:
            content = excel.read_bytes()
            files = {"file": (excel.name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            preview = checked(client.post("/api/admin/catalog/products/import", files=files))
            if preview["errors"]:
                raise ValueError("El Excel requiere corregir su vista previa: " + json.dumps(preview["errors"][:3]))
            checked(client.post("/api/admin/catalog/products/import", files=files,
                                data={"commit": "true", "version": str(preview["version"])}))
            products = {p["sku"]: p for p in checked(client.get("/api/admin/catalog"))["products"]}
        fields = ("sku", "name", "subBrand", "category", "subcategory", "description", "barcode", "quantity",
                  "height", "thickness", "width", "price", "saleUnit", "productType", "photo")
        for item in reference["items"]:
            product = products.get(item["internal_code"])
            if not product:
                continue
            if item.get("barcode") and product.get("barcode") != item["barcode"]:
                if product.get("barcode"):
                    raise ValueError("Conflicto de código de barras para " + product["sku"])
                full = checked(client.get("/api/admin/catalog/products/" + product["id"]))
                body = {key: full[key] for key in fields}
                body.update(barcode=item["barcode"], version=full["version"])
                products[product["sku"]] = checked(client.patch("/api/admin/catalog/products/" + product["id"], json=body))
        if not any(p["id"] == PLAN_ID for p in checked(client.get("/api/admin/catalog"))["planograms"]):
            checked(client.post("/api/admin/planograms/import-json",
                                files={"file": ("source-plan.json", json.dumps(reference).encode(), "application/json")},
                                data={"planogram_id": PLAN_ID, "name": reference["name"]}))
        plan = checked(client.get("/api/admin/catalog/planograms/" + PLAN_ID))
        if not plan["managed"]:
            body = {"name": reference["name"], "store_code": "PDV-001", "status": "Activo", "photo": "",
                    "description": "Piloto local con el planograma real de Salcobrand dev. El Excel de productos conserva dimensiones simuladas declaradas por su fuente.",
                    "document": "data:application/pdf;base64," + base64.b64encode(pdf.read_bytes()).decode(),
                    "document_name": pdf.name, "document_page": 1, "position_mode": "products", "version": plan["version"],
                    "positionRows": plan["positionRows"]}
            plan = checked(client.patch("/api/admin/catalog/planograms/" + PLAN_ID, json=body))
        identity = lambda i: (i["band"], i["position_in_section"], i["title"], i["internal_code"], i["barcode"], i["expected_facings"])
        if [identity(i) for i in reference["items"]] != [identity(i) for i in plan["items"]]:
            raise ValueError("La referencia local debe conservar exactamente los niveles, posiciones, identidades y caras originales.")
        checked(client.put("/api/points/pdv-001/planogram", json={"planogram_id": PLAN_ID}))
        target = OUTPUT / "proof.json"
        proof = json.loads(target.read_text()) if target.exists() else {}
        proof.update({"inherited_store": inherited_store or proof.get("inherited_store", False),
                      "source_url": "https://salcobrand-dev.neuramorphic.ai", "source_plan_id": reference["id"],
                      "source_plan_sha256": hashlib.sha256((OUTPUT / "source-plan.json").read_bytes()).hexdigest(),
                      "document_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "document_pages": plan["document_pages"],
                      "products_file": excel.name, "dimensions_source": "Simuladas, declaradas en la descripción del Excel original",
                      "local_plan_id": PLAN_ID, "point_id": "pdv-001", "position_mode": plan["position_mode"],
                      "positions": len(plan["items"]), "expected_facings": sum(i["expected_facings"] for i in plan["items"]),
                      "missing_master_skus": [i["internal_code"] for i in reference["items"] if i["internal_code"] not in products],
                      "source_positions_preserved": True})
        target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: proof[key] for key in ("local_plan_id", "positions", "expected_facings", "document_pages", "source_positions_preserved")}))


if __name__ == "__main__":
    main()
