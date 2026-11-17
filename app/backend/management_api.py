"""Master-data API. Management writes require administrator authorization."""
from typing import List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictFloat
import infrastructure as service
import profiles


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoreAssignment(Payload):
    type_id: str
    quantity: StrictInt = Field(ge=0, le=10000)
    version: StrictInt = Field(ge=0)


class StoreFields(Payload):
    name: str
    store_type: str
    region: str
    commune: str
    address: str
    manager: str
    status: str = "Activo"
    description: str = ""
    assignments: List[StoreAssignment] | None = None


class StoreCreate(StoreFields):
    code: str


class StoreUpdate(StoreFields):
    version: StrictInt = Field(ge=1)


class Version(Payload):
    version: StrictInt = Field(ge=1)


class TypeFields(Payload):
    name: str
    width_cm: StrictFloat
    depths: List[StrictFloat]
    photo: str = ""
    status: str = "Activo"
    kind: str = 'Estante'
    supplier: str = ''
    height_cm: StrictFloat | None = None


class TypeUpdate(TypeFields):
    version: StrictInt = Field(ge=1)


class Quantity(Payload):
    quantity: StrictInt = Field(ge=0, le=10000)
    version: StrictInt = Field(ge=0)


class Link(Payload):
    store_code: str
    type_id: str
    point_id: str
    version: StrictInt = Field(ge=0)


class InstanceUpdate(Version):
    label: str = ""
    note: str = ""


def router(require_user, require_admin):
    api = APIRouter(prefix="/api", tags=["PDV e Infraestructura"])

    @api.get("/stores")
    def stores(user=Depends(require_user)):
        scope = profiles.store_scope(user)
        return [{key: s[key] for key in ("code", "name", "status", "region", "commune")}
                for s in service.list_stores() if scope is None or s["code"] in scope]

    @api.get("/admin/location-catalog")
    def catalog(user=Depends(require_admin)):
        from settings_service import read
        return {"regions": service.REGIONS, "store_types": read()['state']['pdvTypes']}

    @api.get("/location-catalog")
    def locations(user=Depends(require_user)):
        from capture_selection import geography
        return {'regions': geography(user)}

    @api.get("/admin/stores")
    def all_stores(include_deleted: bool = False, user=Depends(require_admin)):
        return service.list_stores(include_deleted)

    @api.post("/admin/stores", status_code=201)
    def create_store(payload: StoreCreate, user=Depends(require_admin)):
        return service.save_store(payload.model_dump(), user["username"])

    @api.patch("/admin/stores/{code}")
    def update_store(code: str, payload: StoreUpdate, user=Depends(require_admin)):
        return service.save_store(payload.model_dump(), user["username"], code)

    @api.delete("/admin/stores/{code}")
    def retire_store(code: str, version: int = Query(ge=1), user=Depends(require_admin)):
        return service.retire_store(code, version, user["username"])

    @api.post("/admin/stores/{code}/restore")
    def restore_store(code: str, payload: Version, user=Depends(require_admin)):
        return service.retire_store(code, payload.version, user["username"], restore=True)

    @api.get("/admin/stores/{code}/history")
    def history(code: str, user=Depends(require_admin)):
        return service.store_history(code)

    @api.get("/admin/shelf-types")
    def types(user=Depends(require_admin)):
        return service.list_types()

    @api.post("/admin/shelf-types", status_code=201)
    def create_type(payload: TypeFields, user=Depends(require_admin)):
        return service.save_type(payload.model_dump(exclude_unset=True), user["username"])

    @api.patch("/admin/shelf-types/{type_id}")
    def update_type(type_id: str, payload: TypeUpdate, user=Depends(require_admin)):
        return service.save_type(payload.model_dump(exclude_unset=True), user["username"], type_id)

    @api.delete("/admin/shelf-types/{type_id}")
    def delete_type(type_id: str, version: int = Query(ge=1), user=Depends(require_admin)):
        return service.delete_type(type_id, version, user['username'])

    @api.get("/admin/infrastructure")
    def state(store_code: str = None, user=Depends(require_admin)):
        return service.infrastructure_state(store_code)

    @api.put("/admin/stores/{code}/shelf-assignments/{type_id}")
    def quantity(code: str, type_id: str, payload: Quantity, user=Depends(require_admin)):
        return service.set_quantity(code, type_id, payload.quantity, payload.version, user["username"])

    @api.post("/admin/shelf-instances/link-existing")
    def link(payload: Link, user=Depends(require_admin)):
        return service.link_existing(**payload.model_dump(), actor=user["username"])

    @api.patch("/admin/shelf-instances/{instance_id}")
    def instance(instance_id: str, payload: InstanceUpdate, user=Depends(require_admin)):
        return service.save_instance(instance_id, payload.model_dump(), user["username"])

    return api
