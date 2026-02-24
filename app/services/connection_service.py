import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.connection import Connection
from app.models.node import Node
from app.services.node_service import get_online_nodes_by_regions


class MaxConcurrentError(Exception):
    def __init__(self, current: int, max_val: int):
        self.current = current
        self.max = max_val
        super().__init__("系統達人數最大值")


class UsageLimitError(Exception):
    pass


class NodeNotAvailableError(Exception):
    pass


async def get_available_nodes(db: AsyncSession, app: Application) -> list[Node]:
    regions = [r.region for r in app.regions]
    if not regions:
        return []
    return await get_online_nodes_by_regions(db, regions)


async def create_connection(
    db: AsyncSession, app_id: uuid.UUID, node_id: uuid.UUID, session_id: str
) -> Connection:
    # Lock the app row to prevent race conditions
    result = await db.execute(
        select(Application).where(Application.id == app_id).with_for_update()
    )
    app = result.scalar_one()

    # Check hard usage limit (120%)
    if app.usage_bytes >= int(app.usage_limit * 1.2):
        raise UsageLimitError("使用量已達上限")

    # Count active connections
    count_result = await db.execute(
        select(func.count()).select_from(Connection).where(
            Connection.app_id == app_id, Connection.status == "active"
        )
    )
    active_count = count_result.scalar_one()

    if active_count >= app.max_concurrent:
        raise MaxConcurrentError(current=active_count, max_val=app.max_concurrent)

    # Verify node is online
    node_result = await db.execute(
        select(Node).where(Node.id == node_id, Node.status == "online")
    )
    node = node_result.scalar_one_or_none()
    if not node:
        raise NodeNotAvailableError("Node is not available")

    # Create connection
    conn = Connection(app_id=app_id, node_id=node_id, session_id=session_id)
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def keepalive_connection(
    db: AsyncSession, session_id: str, app_id: uuid.UUID,
    bytes_up: int = 0, bytes_down: int = 0,
) -> dict | None:
    """Returns dict with warning flag, or None if session not found."""
    result = await db.execute(
        select(Connection).where(
            Connection.session_id == session_id,
            Connection.app_id == app_id,
            Connection.status == "active",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return None
    conn.last_keepalive = datetime.now(timezone.utc)
    conn.bytes_up += bytes_up
    conn.bytes_down += bytes_down

    # Atomic increment of application usage_bytes
    delta = bytes_up + bytes_down
    if delta > 0:
        await db.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(usage_bytes=Application.usage_bytes + delta)
        )

    await db.commit()

    # Check soft limit for warning
    app_result = await db.execute(
        select(Application.usage_bytes, Application.usage_limit).where(Application.id == app_id)
    )
    row = app_result.one()
    warning = row.usage_bytes >= row.usage_limit

    return {"warning": warning}


async def disconnect_connection(db: AsyncSession, session_id: str, app_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Connection).where(
            Connection.session_id == session_id,
            Connection.app_id == app_id,
            Connection.status == "active",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return False
    conn.status = "closed"
    conn.disconnected_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def get_connections_by_app(db: AsyncSession, app_id: uuid.UUID) -> list[Connection]:
    result = await db.execute(
        select(Connection).where(Connection.app_id == app_id).order_by(Connection.connected_at.desc())
    )
    return list(result.scalars().all())
