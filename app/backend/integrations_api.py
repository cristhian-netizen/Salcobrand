"""Administración → APIs. Administrators enter, replace, remove and test keys; the Superusuario (viewer) sees status only.

No endpoint ever returns a secret: only whether it is configured, where it comes from and its last 4 characters.
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import integrations_service as service
import profiles

NO_STORE = {"Cache-Control": "no-store"}


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=0)
    values: Dict[str, str] = Field(default_factory=dict, max_length=10)
    remove: list[str] = Field(default_factory=list, max_length=10)


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: Optional[Dict[str, str]] = Field(default=None, max_length=10)


def router(require_admin, require_user):
    api = APIRouter(prefix="/api/admin/integrations", tags=["APIs"])

    def require_view(user=Depends(require_user)):
        if not (profiles.can(user, "manage") or profiles.profile_of(user) == "viewer"):
            raise HTTPException(status_code=403, detail="Tu perfil no permite ver las APIs.")
        return user

    @api.get("")
    def overview(user=Depends(require_view)):
        return JSONResponse(service.overview(can_edit=profiles.can(user, "manage")), headers=NO_STORE)

    @api.put("/{integration_id}")
    def save(integration_id: str, payload: Change, user=Depends(require_admin)):
        for value in payload.values.values():
            if len(value) > 300:
                raise HTTPException(status_code=400, detail="El valor es demasiado largo.")
        result = service.save(integration_id, payload.values, payload.version, user["username"], tuple(payload.remove))
        return JSONResponse(result, headers=NO_STORE)

    @api.post("/{integration_id}/test")
    async def test(integration_id: str, payload: Probe = Probe(), user=Depends(require_admin)):
        result = await run_in_threadpool(service.test, integration_id, user["username"], payload.values or None)
        return JSONResponse(result, headers=NO_STORE)

    return api
