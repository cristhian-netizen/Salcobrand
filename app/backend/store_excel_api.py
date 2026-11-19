from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
import store_excel
from infrastructure import ManagementError


def router(require_admin):
    api = APIRouter(prefix='/api/admin/store-transfer', tags=['Excel de PDV'], dependencies=[Depends(require_admin)])

    @api.get('/workbook.xlsx')
    def export(template: bool = False, search: str = "", region: str = "", commune: str = "", status: str = "", include_deleted: bool = False):
        name = 'Plantilla_PDV.xlsx' if template else 'Salcobrand_PDV.xlsx'
        return Response(content=store_excel.workbook_bytes(template, search, region, commune, status, include_deleted),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':f'attachment; filename="{name}"','Cache-Control':'no-store'})

    @api.get('/filtered.csv')
    def csv(search: str = '', region: str = '', commune: str = '', status: str = '', include_deleted: bool = False):
        return Response(content=store_excel.csv_bytes(search,region,commune,status,include_deleted),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="Salcobrand_PDV.csv"','Cache-Control':'no-store'})

    @api.post('/import')
    async def import_stores(file: UploadFile = File(...), commit: bool = Form(False), version: str | None = Form(None), user=Depends(require_admin)):
        if not (file.filename or '').lower().endswith('.xlsx'):
            raise ManagementError('Usa un archivo .xlsx.')
        content = await file.read(5 * 1024 * 1024 + 1)
        return await run_in_threadpool(store_excel.transfer,content,user['username'],commit,version)

    return api
