from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import people_service as service
import people_excel
from infrastructure import ManagementError


class Person(BaseModel):
    model_config = ConfigDict(extra='forbid')
    names: str
    paternal: str
    maternal: str = ''
    email: str
    username: str
    position: str
    startDate: str
    endDate: str = ''
    status: str
    role: str
    storeCodes: list[str] = Field(default_factory=list)
    allStores: bool = False


class SavePerson(BaseModel):
    model_config = ConfigDict(extra='forbid')
    person: Person
    version: StrictInt | None = None
    enable_access: bool = False
    password: str = ''


class Password(BaseModel):
    version: StrictInt = Field(ge=1)
    password: str
    confirmation: str


def router(require_admin):
    api = APIRouter(prefix='/api/admin/people', dependencies=[Depends(require_admin)], tags=['Personas y roles'])

    @api.get('')
    def people():
        return service.list_people()

    @api.get('/template.xlsx')
    def template():
        return Response(people_excel.template_bytes(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="Plantilla_Personas.xlsx"','Cache-Control':'no-store'})

    @api.post('/import')
    async def transfer(file: UploadFile = File(...),commit: bool = Form(False),version: str | None = Form(None),user=Depends(require_admin)):
        if not (file.filename or '').lower().endswith('.xlsx'):
            raise ManagementError('Usa un archivo .xlsx.')
        content = await file.read(5 * 1024 * 1024 + 1)
        return await run_in_threadpool(people_excel.transfer,content,user['username'],commit,version)

    @api.post('',status_code=201)
    def create(payload: SavePerson,user=Depends(require_admin)):
        return service.save(payload.person.model_dump(),user['username'],enable_access=payload.enable_access,password=payload.password)

    @api.patch('/{person_id}')
    def update(person_id: str,payload: SavePerson,user=Depends(require_admin)):
        return service.save(payload.person.model_dump(),user['username'],person_id,payload.version,payload.enable_access,payload.password)

    @api.delete('/{person_id}')
    def delete(person_id: str,version: int = Query(ge=1),user=Depends(require_admin)):
        return service.delete(person_id,version,user['username'])

    @api.post('/{person_id}/password')
    def password(person_id: str,payload: Password,user=Depends(require_admin)):
        if payload.password != payload.confirmation:
            raise ManagementError('Las contraseñas no coinciden.')
        return service.reset_password(person_id,payload.version,payload.password,user['username'])

    return api
