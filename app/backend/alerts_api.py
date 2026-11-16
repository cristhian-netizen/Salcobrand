from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import alerts_service


class AlertChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['Pendiente', 'Resuelta']
    version: StrictInt = Field(ge=0)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


def router(require_user, require_resolve, authorize_reading):
    api = APIRouter(prefix='/api/alerts', tags=['Alertas'])

    @api.get('')
    def summary(point: str = '', store: str = '', start: str = Query(default='', alias='from'),
                end: str = Query(default='', alias='to'), status: str = 'Pendiente', user=Depends(require_user)):
        return alerts_service.summary(user, point, store, start, end, status)

    @api.patch('/readings/{reading_id}/{kind}')
    def update(reading_id: int, kind: Literal['planogram', 'empty-space', 'no-price', 'absent'],
               payload: AlertChange, user=Depends(require_resolve)):
        authorize_reading(reading_id, user)
        return alerts_service.save(reading_id, kind, payload.model_dump(), user['username'])

    return api
