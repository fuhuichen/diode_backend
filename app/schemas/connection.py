import uuid
from datetime import datetime

from pydantic import BaseModel


class ConnectRequest(BaseModel):
    node_id: uuid.UUID
    session_id: str


class ConnectResponse(BaseModel):
    message: str = "connected"
    session_id: str


class KeepaliveRequest(BaseModel):
    session_id: str


class DisconnectRequest(BaseModel):
    session_id: str


class NodesRequest(BaseModel):
    region: str | None = None


class ConnectionResponse(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    node_id: uuid.UUID
    session_id: str
    status: str
    last_keepalive: datetime
    connected_at: datetime
    disconnected_at: datetime | None

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    error: str
    message: str
    current: int | None = None
    max: int | None = None
