from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node


async def register_node(db: AsyncSession, node: Node, region: str, name: str | None) -> Node:
    node.region = region
    if name:
        node.name = name
    node.status = "online"
    node.last_heartbeat = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(node)
    return node


async def heartbeat_node(
    db: AsyncSession,
    node: Node,
    client_address: str,
    probe_ok: bool | None = None,
    probe_latency_ms: float | None = None,
    probe_error: str | None = None,
) -> None:
    node.client_address = client_address
    node.status = "online"
    node.last_heartbeat = datetime.now(timezone.utc)

    if probe_ok is not None:
        node.probe_ok = probe_ok
        node.probe_latency_ms = probe_latency_ms
        node.probe_error = probe_error
        node.last_probe_at = datetime.now(timezone.utc)
        if probe_ok:
            node.probe_fail_count = 0
        else:
            node.probe_fail_count = (node.probe_fail_count or 0) + 1

    await db.commit()


async def deregister_node(db: AsyncSession, node: Node) -> None:
    node.status = "offline"
    node.client_address = None
    await db.commit()


async def get_online_nodes_by_regions(db: AsyncSession, regions: list[str]) -> list[Node]:
    result = await db.execute(
        select(Node).where(Node.status == "online", Node.region.in_(regions))
    )
    return list(result.scalars().all())


async def get_all_nodes(db: AsyncSession) -> list[Node]:
    result = await db.execute(select(Node).order_by(Node.created_at.desc()))
    return list(result.scalars().all())
