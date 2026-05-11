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
    bytes_up: int = 0
    bytes_down: int = 0


class DisconnectRequest(BaseModel):
    session_id: str


class NodesRequest(BaseModel):
    region: str | None = None


class ClientLogRequest(BaseModel):
    # 既有
    device_brand: str | None = None
    device_model: str | None = None
    os_version: str | None = None
    app_version: str | None = None
    flavor: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    log_text: str
    # 新增：更多裝置/環境資訊（皆選填，舊版客戶端不會傳）
    manufacturer: str | None = None
    device: str | None = None
    hardware: str | None = None
    fingerprint: str | None = None
    abi: str | None = None
    locale: str | None = None
    timezone: str | None = None
    network_type: str | None = None
    package_name: str | None = None
    version_code: int | None = None
    sdk_int: int | None = None


class ConnectionResponse(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    node_id: uuid.UUID
    session_id: str
    status: str
    bytes_up: int
    bytes_down: int
    last_keepalive: datetime
    connected_at: datetime
    disconnected_at: datetime | None

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    error: str
    message: str
    current: int | None = None
    max: int | None = None
