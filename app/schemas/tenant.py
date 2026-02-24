import uuid
from datetime import datetime

from pydantic import BaseModel


class TenantCreateRequest(BaseModel):
    name: str
    password: str


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    password: str | None = None
    is_active: bool | None = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    app_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantDetailResponse(TenantResponse):
    apps: list[dict] = []
