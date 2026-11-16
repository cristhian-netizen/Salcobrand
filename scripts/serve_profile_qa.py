"""Local-only profile preview using the real routes and a temporary synthetic DB.

Model, cloud storage and capture-link services are intentionally disabled.
Run with the QA virtualenv: python scripts/serve_profile_qa.py
"""
from pathlib import Path
import sys
import io
import os

import uvicorn
from fastapi import HTTPException, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend" / "tests"))
from test_profiles import ProfileHTTPTests


def main():
    os.environ['NEURAVISION_ENVIRONMENT'] = 'profile-qa'
    ProfileHTTPTests.setUpClass()
    fixture = ProfileHTTPTests()
    try:
        fixture.setUp()
        with fixture.db.get_conn() as conn:
            conn.execute("UPDATE users SET username = 'local-' || username")
            conn.execute("UPDATE readings SET captured_by = 'local-' || captured_by WHERE captured_by IS NOT NULL")
        import client_identity
        client_identity.seed_local_operator()
        import infrastructure
        infrastructure.bootstrap_legacy_stores()
        infrastructure.save_store({"name": "PDV de demostración", "store_type": "Farmacia",
                                   "region": "Metropolitana de Santiago", "commune": "Santiago",
                                   "address": "Dirección ficticia 123", "manager": "Encargado ficticio",
                                   "status": "Activo", "description": "Datos exclusivos del QA local", "version": 1},
                                  "local-admin", code="L128")
        shelf = infrastructure.save_type({"name": "Góndola de demostración", "width_cm": 120,
                                          "depths": [35, 40], "status": "Activo"}, "local-admin")
        infrastructure.link_existing("L128", shelf["id"], "point-a", 0, "local-admin")
        from PIL import Image, ImageDraw
        placeholder = Image.new("RGB", (320, 160), "#e6f2f2")
        ImageDraw.Draw(placeholder).text((60, 72), "QA - DATOS FICTICIOS", fill="#17364b")
        buffer = io.BytesIO()
        placeholder.save(buffer, format="JPEG")
        fixture.storage.get.return_value = buffer.getvalue()
        import base64
        import catalog_service
        demo_products = []
        for sku, name in (("QA-ALFA", "Alfa de demostración"), ("QA-ZETA", "Zeta de demostración")):
            demo_products.append(catalog_service.save_product({"sku": sku, "name": name, "subBrand": "Marca de demostración",
                "category": "Cuidado personal", "subcategory": "Desodorantes", "saleUnit": "ml", "productType": "Envasado",
                "quantity": 150, "height": 15, "width": 4, "thickness": 3, "price": 4990}, "local-admin"))
        demo_plan = catalog_service.save_plan({"name": "Planograma de demostración", "store_code": "L128", "status": "Activo",
            "photo": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
            "positionRows": [{"level": index + 1, "position": 1, "faces": 2, "productId": p["id"], "sku": p["sku"]}
                             for index, p in enumerate(demo_products)]}, "local-admin")
        fixture.db.set_point_planogram("point-a", demo_plan["id"])
        app_module = fixture.main
        @app_module.app.get("/api/profile-qa", include_in_schema=False)
        def qa_marker():
            return {"environment": "profile-qa", "synthetic": True}
        async def disabled_analysis(*args, **kwargs):
            raise HTTPException(503, "El motor está deshabilitado en este QA local de perfiles")
        fixture.core.read_image_uploads = disabled_analysis
        def disabled_service(*args, **kwargs):
            raise HTTPException(503, "Servicio externo deshabilitado en QA local de perfiles")
        import captures
        for name in ("list_links", "list_captures", "create_link", "set_active", "set_local"):
            setattr(captures, name, disabled_service)
        fixture.main.shadow.summary = disabled_service
        def qa_user(request: Request):
            return {**app_module.require_user(request), "environment": "profile-qa"}
        app_module.app.dependency_overrides[app_module.require_user] = qa_user
        print("QA de perfiles: http://127.0.0.1:8011 — solo datos ficticios; ninguna conexión al modelo", flush=True)
        uvicorn.run(app_module.app, host="127.0.0.1", port=8011, lifespan="off")
    finally:
        fixture.doCleanups()
        ProfileHTTPTests.tearDownClass()


if __name__ == "__main__":
    main()
