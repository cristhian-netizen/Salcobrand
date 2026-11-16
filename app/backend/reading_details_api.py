from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt
import reading_details as service


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    productId: str = Field(min_length=1, max_length=120)
    position: str = Field(min_length=1, max_length=80)
    ownership: Literal['Propio', 'Competencia', 'Sin clasificar'] = 'Sin clasificar'
    expected: StrictBool | None = None
    present: StrictBool | None = None
    faces: StrictInt | None = Field(default=None, ge=0, le=10000)
    match: Literal['Sí', 'No', 'N/A'] = 'N/A'
    observedPrice: StrictFloat | None = Field(default=None, ge=0)
    confidence: StrictFloat | None = Field(default=None, ge=0, le=100)


class DetailsPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=0)
    reviewVersion: StrictInt = Field(ge=0)
    shelfInstanceId: str = Field(min_length=1, max_length=120)
    details: list[Observation] = Field(max_length=500)
    scopeConfirmed: StrictBool = False
    expectedConfirmed: StrictBool = False
    comparisonConfirmed: StrictBool = False


def router(require_user, require_review, authorize_reading):
    api = APIRouter(prefix='/api/readings', tags=['Detalle manual por producto'])

    @api.get('/{reading_id}/product-details')
    def read(reading_id: int, user=Depends(require_user)):
        authorize_reading(reading_id, user)
        return service.read(reading_id)

    @api.get('/{reading_id}/product-detail-options')
    def options(reading_id: int, user=Depends(require_review)):
        authorize_reading(reading_id, user)
        return service.options(reading_id)

    @api.patch('/{reading_id}/product-details')
    def save(reading_id: int, payload: DetailsPayload, user=Depends(require_review)):
        authorize_reading(reading_id, user)
        return service.save(reading_id, payload.model_dump(), user['username'])

    return api
