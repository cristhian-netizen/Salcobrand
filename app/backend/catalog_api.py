from typing import List, Literal
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt
import catalog_service as service


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductFields(Payload):
    sku: str
    name: str
    subBrand: str
    category: str
    subcategory: str
    description: str = ""
    barcode: str = ""
    saleUnit: str
    productType: str
    quantity: StrictFloat
    height: StrictFloat
    width: StrictFloat
    thickness: StrictFloat
    price: StrictFloat | None = None
    photo: str = ""


class ProductUpdate(ProductFields):
    version: StrictInt = Field(ge=1)


class Selection(Payload):
    id: str
    version: StrictInt = Field(ge=1)


class ProductDeletion(Payload):
    products: List[Selection] = Field(min_length=1, max_length=5000)


class Position(Payload):
    level: StrictInt
    position: StrictInt
    faces: StrictInt
    productId: str = ""
    legacy_item_id: StrictInt | None = None
    legacy_title: str = ""
    sku: str = ""
    barcode: str = ""


class PlanFields(Payload):
    category: str | None = None
    subcategories: List[str] | None = Field(default=None, max_length=1000)
    name: str
    store_code: str | None = None
    status: str = "Activo"
    description: str = ""
    photo: str = ""
    document: str = ""
    document_name: str = ""
    document_page: StrictInt = Field(default=1, ge=1)
    position_mode: Literal['faces', 'products'] = 'faces'
    positionRows: List[Position] = Field(default_factory=list, max_length=5000)


class PlanUpdate(PlanFields):
    version: StrictInt = Field(ge=0)


class PlanAssignments(Payload):
    stores: List[str] = Field(default_factory=list, max_length=10000)
    type_id: str | None = Field(default=None, max_length=150)
    version: StrictInt = Field(ge=0)
    replace_conflicts: bool = False


def router(require_admin):
    api = APIRouter(prefix="/api/admin/catalog", dependencies=[Depends(require_admin)], tags=["Productos y Planogramas"])

    @api.get("")
    def state():
        return service.state()

    @api.get('/planograms/{plan_id}/assignments')
    def assignments(plan_id: str):
        import plan_assignments
        return plan_assignments.details(plan_id)

    @api.post('/planograms/{plan_id}/assignments/preview')
    def assignment_preview(plan_id: str, payload: PlanAssignments, user=Depends(require_admin)):
        import plan_assignments
        return plan_assignments.change(plan_id,payload.model_dump(),user['username'])

    @api.put('/planograms/{plan_id}/assignments')
    def assignment_save(plan_id: str, payload: PlanAssignments, user=Depends(require_admin)):
        import plan_assignments
        return plan_assignments.change(plan_id,payload.model_dump(),user['username'],True)

    @api.get("/products/{product_id}")
    def product_detail(product_id: str):
        return service.product_detail(product_id)

    @api.get("/planograms/{plan_id}")
    def plan_detail(plan_id: str):
        return service.plan_detail(plan_id)

    @api.post("/products", status_code=201)
    def create_product(payload: ProductFields, user=Depends(require_admin)):
        return service.save_product(payload.model_dump(), user["username"])

    @api.patch("/products/{product_id}")
    def update_product(product_id: str, payload: ProductUpdate, user=Depends(require_admin)):
        return service.save_product(payload.model_dump(), user["username"], product_id)

    @api.post("/products/delete")
    def delete_products(payload: ProductDeletion, user=Depends(require_admin)):
        return service.delete_products([r.model_dump() for r in payload.products], user["username"])

    @api.get("/products.xlsx")
    def export_products(template: bool = False):
        from catalog_excel import workbook_bytes
        return Response(workbook_bytes(template), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="' + ("Plantilla_Productos.xlsx" if template else "Productos.xlsx") + '"'})

    @api.post("/products/import")
    async def import_products(file: UploadFile = File(...), commit: bool = Form(False), version: int | None = Form(None), user=Depends(require_admin)):
        from catalog_excel import transfer
        from infrastructure import ManagementError
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise ManagementError("Usa un archivo .xlsx.")
        content = await file.read(5 * 1024 * 1024 + 1)
        from fastapi.concurrency import run_in_threadpool
        return await run_in_threadpool(transfer, content, user["username"], commit, version)

    @api.post("/planograms", status_code=201)
    def create_plan(payload: PlanFields, user=Depends(require_admin)):
        return service.save_plan(payload.model_dump(), user["username"])

    @api.post("/reference")
    async def reference(file: UploadFile = File(...)):
        import base64
        from infrastructure import ManagementError
        content = await file.read(5 * 1024 * 1024 + 1)
        if len(content) > 5 * 1024 * 1024:
            raise ManagementError("Usa un PDF de hasta 5 MB.")
        encoded = "data:application/pdf;base64," + base64.b64encode(content).decode()
        from fastapi.concurrency import run_in_threadpool
        validated = await run_in_threadpool(service.document_reference, encoded, 1)
        return {"document": validated["content"], "document_pages": validated["pages"], "document_page": 1,
                "document_name": (file.filename or "planograma.pdf")[:200], "photo": ""}

    @api.patch("/planograms/{plan_id}")
    def update_plan(plan_id: str, payload: PlanUpdate, user=Depends(require_admin)):
        return service.save_plan(payload.model_dump(), user["username"], plan_id)

    @api.delete("/planograms/{plan_id}")
    def delete_plan(plan_id: str, version: int = Query(ge=0), user=Depends(require_admin)):
        return service.delete_plan(plan_id, version, user["username"])

    return api
