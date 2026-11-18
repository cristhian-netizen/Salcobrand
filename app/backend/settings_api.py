"""Administrator configuration and authenticated display settings."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import settings_service as service


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=0)
    value: dict | list


class Assignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sku: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=100)
    subcategory: str = Field(min_length=1, max_length=100)
    subBrand: str = Field(default='', max_length=100)


class Assignments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = Field(max_length=100)
    assignments: list[Assignment] = Field(min_length=1, max_length=5000)


def router(require_admin, require_user):
    api = APIRouter(prefix='/api', tags=['Configuración'])

    @api.get('/admin/settings/classification')
    def classification(user=Depends(require_admin)):
        import classification_transfer
        return classification_transfer.options()

    @api.get('/admin/settings/classification/template.xlsx')
    def template(user=Depends(require_admin)):
        import classification_transfer
        return Response(classification_transfer.workbook_bytes(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="Clasificacion_Productos.xlsx"','Cache-Control':'no-store'})

    @api.post('/admin/settings/classification/import')
    async def import_classification(file: UploadFile = File(...), commit: bool = Form(False), version: str | None = Form(None), user=Depends(require_admin)):
        import classification_transfer
        from infrastructure import ManagementError
        if not (file.filename or '').lower().endswith('.xlsx'):
            raise ManagementError('Usa un archivo .xlsx.')
        rows = await run_in_threadpool(classification_transfer.read_file, await file.read(5*1024*1024+1))
        return await run_in_threadpool(classification_transfer.transfer, rows, user['username'], commit, version)

    @api.post('/admin/settings/classification/assign')
    def assign_classification(payload: Assignments, user=Depends(require_admin)):
        import classification_transfer
        rows = [{'sheet':'Asignaciones','row':i+2,'values':{'SKU':p.sku,'Categoría':p.category,'Subcategoría':p.subcategory,'Submarca':p.subBrand}}
                for i,p in enumerate(payload.assignments)]
        return classification_transfer.transfer(rows, user['username'], True, payload.version)

    @api.get('/admin/settings')
    def read(user=Depends(require_admin)):
        result = service.read()
        import db
        with db.get_conn() as conn:
            products = service.product_references(conn)
        return {**result, 'products': [{key: p[key] for key in ('subBrand', 'category', 'subcategory')} for p in products],
                'indicators': [{'key': key, 'label': data[0], 'direction': data[1]} for key, data in service.INDICATORS.items() if key != 'oos']}

    @api.patch('/admin/settings/{section}')
    def save(section: str, payload: Change, user=Depends(require_admin)):
        return service.save(section, payload.value, payload.version, user['username'])

    @api.get('/display-settings')
    def display(user=Depends(require_user)):
        return service.display_parameters()

    return api
