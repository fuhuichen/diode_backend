import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentRegisterRequest(BaseModel):
    region: str
    name: str | None = None


class AgentRegisterResponse(BaseModel):
    node_id: uuid.UUID
    message: str = "registered"


class AgentHeartbeatRequest(BaseModel):
    client_address: str
    status: str = "running"


class NodeCreateRequest(BaseModel):
    name: str
    region: str


class NodeCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    region: str
    node_token: str


class NodeResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    region: str
    client_address: str | None
    status: str
    last_heartbeat: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NodeAvailable(BaseModel):
    node_id: uuid.UUID
    region: str
    client_address: str
