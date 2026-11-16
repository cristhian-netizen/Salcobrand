"""Administrator configuration and authenticated display settings."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import settings_service as service


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=0)
    value: dict | list


def router(require_admin, require_user):
    api = APIRouter(prefix='/api', tags=['Configuración'])

    @api.get('/admin/settings')
    def read(user=Depends(require_admin)):
        result = service.read()
        import db
        with db.get_conn() as conn:
            products = service.product_references(conn)
        return {**result, 'products': [{key: p[key] for key in ('subBrand', 'category', 'subcategory')} for p in products],
                'indicators': [{'key': key, 'label': data[0], 'direction': data[1]} for key, data in service.INDICATORS.items()]}

    @api.patch('/admin/settings/{section}')
    def save(section: str, payload: Change, user=Depends(require_admin)):
        return service.save(section, payload.value, payload.version, user['username'])

    @api.get('/display-settings')
    def display(user=Depends(require_user)):
        return service.display_parameters()

    return api
