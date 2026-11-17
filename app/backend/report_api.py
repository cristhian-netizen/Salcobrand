"""Report filters and measurement approval share server-side authorization."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

import measurement_reports as service
import profiles
import db


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    note: str = Field(default="", max_length=2000)
    version: StrictInt = Field(ge=0)


def router(require_report, require_review, authorize_reading, store_scope, require_user):
    api = APIRouter(prefix="/api", tags=["Reportes y exportaciones"])

    def require_catalog_report(user=Depends(require_report)):
        if profiles.profile_of(user) != 'viewer':
            raise HTTPException(403, 'Los reportes de catálogos están disponibles para Superusuario.')
        return user

    def catalog_response(content, filename):
        return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="' + filename + '"','Cache-Control':'no-store'})

    @api.get('/reports/catalog/products.xlsx')
    def products(user=Depends(require_catalog_report)):
        from catalog_excel import workbook_bytes
        return catalog_response(workbook_bytes(), 'Neuravision_Productos.xlsx')

    @api.get('/reports/catalog/stores.xlsx')
    def stores(user=Depends(require_catalog_report)):
        from store_excel import workbook_bytes
        return catalog_response(workbook_bytes(), 'Neuravision_PDV.xlsx')

    def filters(store: str = "", point: str = "", start: str = Query(default="", alias="from"),
                end: str = Query(default="", alias="to"), status: str = "", user=Depends(require_report)):
        return service.history(store_scope(user), store, point, start, end, status)

    @api.get("/reports/measurements")
    def preview(result=Depends(filters)):
        return {**result, "rows": result["rows"][:100], "preview_limit": 100,
                "timezone": "America/Santiago", "statuses": service.STATES}

    @api.get("/measurements")
    def measurements(store: str = "", point: str = "", start: str = Query(default="", alias="from"),
                     end: str = Query(default="", alias="to"), status: str = "", offset: int = Query(default=0, ge=0),
                     user=Depends(require_user)):
        result = service.history(store_scope(user), store, point, start, end, status,
                                 captured_by=profiles.reading_author(user))
        return {"rows": result["rows"][offset:offset + 50], "count": result["totals"]["measurements"],
                "stores": result["stores"], "points": result["points"], "page_size": 50, "offset": offset}

    @api.get("/reports/measurements.csv")
    def csv(result=Depends(filters)):
        return Response(content=service.csv_bytes(result["rows"]), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="Neuravision_Mediciones.csv"', "Cache-Control": "no-store"})

    @api.get("/reports/measurements.xlsx")
    def excel(result=Depends(filters)):
        return Response(content=service.xlsx_bytes(result["rows"]),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="Neuravision_Mediciones.xlsx"', "Cache-Control": "no-store"})

    @api.patch("/readings/{reading_id}/review")
    def review(reading_id: int, payload: ReviewPayload, user=Depends(require_review)):
        authorize_reading(reading_id, user)
        return service.save_review(reading_id, payload.status, payload.note, payload.version, user["username"])

    @api.get('/readings/{reading_id}/report.xlsx')
    def reading_excel(reading_id: int, user=Depends(require_user)):
        authorize_reading(reading_id, user)
        reading = db.get_reading(reading_id)
        history = service.history(store_scope(user), point=reading['point_id'])
        row = next(item for item in history['rows'] if item['id'] == reading_id)
        return catalog_response(service.reading_xlsx_bytes(reading, row), f'Neuravision_Medicion_{reading_id}.xlsx')

    return api
