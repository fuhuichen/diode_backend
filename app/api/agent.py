from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_node
from app.database import get_db
from app.models.node import Node
from app.schemas.node import (
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentRegisterResponse,
)
from app.services.node_service import deregister_node, heartbeat_node, register_node

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/register", response_model=AgentRegisterResponse, status_code=201)
async def register(
    req: AgentRegisterRequest,
    node: Node = Depends(get_current_node),
    db: AsyncSession = Depends(get_db),
):
    node = await register_node(db, node, req.region, req.name)
    return AgentRegisterResponse(node_id=node.id)


@router.post("/heartbeat")
async def heartbeat(
    req: AgentHeartbeatRequest,
    node: Node = Depends(get_current_node),
    db: AsyncSession = Depends(get_db),
):
    await heartbeat_node(
        db, node, req.client_address,
        probe_ok=req.probe_ok,
        probe_latency_ms=req.probe_latency_ms,
        probe_error=req.probe_error,
    )
    return {"message": "ok"}


@router.post("/deregister")
async def deregister(
    node: Node = Depends(get_current_node),
    db: AsyncSession = Depends(get_db),
):
    await deregister_node(db, node)
    return {"message": "deregistered"}
