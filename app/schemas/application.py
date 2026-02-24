import uuid
from datetime import datetime

from pydantic import BaseModel


class AppCreateRequest(BaseModel):
    tenant_id: uuid.UUID
    name: str
    max_concurrent: int = 10
    usage_limit: int = 1073741824
    regions: list[str]


class AppCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID
    api_key: str
    api_secret: str
    max_concurrent: int
    usage_limit: int
    regions: list[str]


class AppUpdateRequest(BaseModel):
    name: str | None = None
    max_concurrent: int | None = None
    usage_limit: int | None = None
    regions: list[str] | None = None
    is_active: bool | None = None


class AppResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID
    tenant_name: str = ""
    api_key: str
    api_secret: str = ""
    max_concurrent: int
    usage_limit: int
    usage_bytes: int
    is_active: bool
    regions: list[str]
    active_connections: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class AppListResponse(BaseModel):
    apps: list[AppResponse]
