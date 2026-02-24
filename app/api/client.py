from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_app
from app.database import get_db
from app.models.application import Application
from app.models.connection import Connection
from app.schemas.connection import (
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    ErrorResponse,
    KeepaliveRequest,
    NodesRequest,
)
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
