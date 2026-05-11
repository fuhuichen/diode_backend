import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_app
from app.database import get_db
from app.models.application import Application
from app.models.connection import Connection
from app.schemas.connection import (
    ClientLogRequest,
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    ErrorResponse,
    KeepaliveRequest,
    NodesRequest,
)

CLIENT_LOG_DIR = Path("clientlogs")
MAX_LOG_TEXT_BYTES = 256 * 1024

logger = logging.getLogger(__name__)
from app.schemas.node import NodeAvailable
from app.services.connection_service import (
    MaxConcurrentError,
    NodeNotAvailableError,
    UsageLimitError,
    create_connection,
    disconnect_connection,
    get_available_nodes,
    keepalive_connection,
)

router = APIRouter(prefix="/api/v1", tags=["client"])


@router.post("/nodes")
async def list_available_nodes(
    req: NodesRequest,
    app: Application = Depends(get_current_app),
    db: AsyncSession = Depends(get_db),
):
    nodes = await get_available_nodes(db, app)
    if req.region:
        nodes = [n for n in nodes if n.region == req.region]

    # Count active connections per node
    node_ids = [n.id for n in nodes if n.client_address]
    active_counts: dict = {}
    if node_ids:
        count_result = await db.execute(
            select(Connection.node_id, func.count())
            .where(Connection.node_id.in_(node_ids), Connection.status == "active")
            .group_by(Connection.node_id)
        )
        active_counts = dict(count_result.all())

    node_list = [
        NodeAvailable(
            node_id=n.id,
            region=n.region,
            client_address=n.client_address,
            active_connections=active_counts.get(n.id, 0),
        )
        for n in nodes
        if n.client_address
    ]
    node_list.sort(key=lambda x: x.active_connections)

    return {"nodes": node_list}


@router.post("/connect", response_model=ConnectResponse)
async def connect(
    req: ConnectRequest,
    app: Application = Depends(get_current_app),
    db: AsyncSession = Depends(get_db),
):
    try:
        conn = await create_connection(db, app.id, req.node_id, req.session_id)
        return ConnectResponse(session_id=conn.session_id)
    except MaxConcurrentError as e:
        raise HTTPException(
            status_code=429,
            detail=ErrorResponse(
                error="max_concurrent_reached",
                message="系統達人數最大值",
                current=e.current,
                max=e.max,
            ).model_dump(),
        )
    except UsageLimitError:
        raise HTTPException(
            status_code=429,
            detail=ErrorResponse(error="usage_limit_reached", message="使用量已達上限").model_dump(),
        )
    except NodeNotAvailableError:
        raise HTTPException(status_code=400, detail="Node is not available")


@router.post("/keepalive")
async def keepalive(
    req: KeepaliveRequest,
    app: Application = Depends(get_current_app),
    db: AsyncSession = Depends(get_db),
):
    result = await keepalive_connection(db, req.session_id, app.id, req.bytes_up, req.bytes_down)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found or already closed")
    return {"message": "ok", "warning": result["warning"]}


@router.post("/disconnect")
async def disconnect(
    req: DisconnectRequest,
    app: Application = Depends(get_current_app),
    db: AsyncSession = Depends(get_db),
):
    ok = await disconnect_connection(db, req.session_id, app.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found or already closed")
    return {"message": "disconnected"}


def _extract_client_ip(request: Request) -> str:
    """nginx / proxy 後面取真實 IP；X-Forwarded-For 取第一個（client 端）"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


@router.post("/clientlog")
async def submit_client_log(
    req: ClientLogRequest,
    request: Request,
    app: Application = Depends(get_current_app),
):
    text = req.log_text or ""
    if len(text.encode("utf-8", errors="ignore")) > MAX_LOG_TEXT_BYTES:
        text = text.encode("utf-8", errors="ignore")[:MAX_LOG_TEXT_BYTES].decode("utf-8", errors="ignore")

    client_ip = _extract_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    now = datetime.now(timezone.utc)
    day_dir = CLIENT_LOG_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%H%M%S_%f')}_{app.id}_{req.flavor or 'unknown'}.json"
    fpath = day_dir / fname

    payload = {
        "received_at": now.isoformat(),
        "app_id": str(app.id),
        "app_name": app.name,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "device_brand": req.device_brand,
        "device_model": req.device_model,
        "manufacturer": req.manufacturer,
        "device": req.device,
        "hardware": req.hardware,
        "fingerprint": req.fingerprint,
        "abi": req.abi,
        "os_version": req.os_version,
        "sdk_int": req.sdk_int,
        "locale": req.locale,
        "timezone": req.timezone,
        "network_type": req.network_type,
        "package_name": req.package_name,
        "app_version": req.app_version,
        "version_code": req.version_code,
        "flavor": req.flavor,
        "attempt_count": req.attempt_count,
        "last_error": req.last_error,
        "log_text": text,
    }
    try:
        fpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "client log saved: app=%s flavor=%s device=%s/%s ip=%s attempts=%s file=%s",
            app.name, req.flavor, req.device_brand, req.device_model, client_ip, req.attempt_count, fpath.name,
        )
    except OSError as e:
        logger.error("failed to write client log: %s", e)
        raise HTTPException(status_code=500, detail="failed to persist log")
    return {"message": "ok", "file": fpath.name}
