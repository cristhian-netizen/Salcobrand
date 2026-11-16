from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import client_identity as service


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant: dict
    version: StrictInt = Field(ge=1)
    model: dict | None = None


def router(require_internal):
    api = APIRouter(prefix='/api/internal/clients',dependencies=[Depends(require_internal)],tags=['Consola interna de clientes'])

    @api.get('')
    def clients():
        return JSONResponse(service.directory(),headers={'Cache-Control':'no-store'})

    @api.get('/{client_id}')
    def identity(client_id: str):
        return JSONResponse(service.detail(client_id),headers={'Cache-Control':'no-store'})

    @api.patch('/{client_id}')
    def save(client_id: str,payload: Change,user=Depends(require_internal)):
        return service.save(client_id,payload.tenant,payload.version,user['username'],payload.model)

    return api
