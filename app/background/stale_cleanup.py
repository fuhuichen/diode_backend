import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.database import async_session
from app.models.connection import Connection
from app.models.node import Node

logger = logging.getLogger(__name__)

KEEPALIVE_TIMEOUT = timedelta(minutes=2)
NODE_UNHEALTHY_TIMEOUT = timedelta(seconds=90)
NODE_OFFLINE_TIMEOUT = timedelta(seconds=300)
PROBE_FAIL_THRESHOLD = 3
CLEANUP_INTERVAL = 10  # seconds


async def cleanup_stale_connections():
    """Mark connections as closed if no keepalive for 30 seconds."""
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - KEEPALIVE_TIMEOUT
        result = await db.execute(
            update(Connection)
            .where(Connection.status == "active", Connection.last_keepalive < cutoff)
            .values(status="closed", disconnected_at=datetime.now(timezone.utc))
            .returning(Connection.id)
        )
        closed = result.all()
        if closed:
            logger.info(f"Closed {len(closed)} stale connections")
        await db.commit()


async def check_node_health():
    """Mark nodes unhealthy (90s) or offline (300s) if no heartbeat."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # Mark offline (>300s)
        offline_cutoff = now - NODE_OFFLINE_TIMEOUT
        await db.execute(
            update(Node)
            .where(
                Node.status.in_(["online", "unhealthy"]),
                Node.last_heartbeat < offline_cutoff,
            )
            .values(status="offline")
        )

        # Mark unhealthy (>90s but <300s)
        unhealthy_cutoff = now - NODE_UNHEALTHY_TIMEOUT
        await db.execute(
            update(Node)
            .where(
                Node.status == "online",
                Node.last_heartbeat < unhealthy_cutoff,
                Node.last_heartbeat >= offline_cutoff,
            )
            .values(status="unhealthy")
        )

        await db.commit()


async def check_probe_health():
    """Mark nodes unhealthy if SOCKS5 probe has failed consecutively."""
    async with async_session() as db:
        result = await db.execute(
            update(Node)
            .where(
                Node.status == "online",
                Node.probe_fail_count >= PROBE_FAIL_THRESHOLD,
            )
            .values(status="unhealthy")
            .returning(Node.id)
        )
        flagged = result.all()
        if flagged:
            logger.warning(f"Marked {len(flagged)} node(s) unhealthy due to probe failures")
        await db.commit()


async def run_cleanup_loop():
    """Background loop that runs cleanup tasks every 10 seconds."""
    logger.info("Starting background cleanup loop")
    while True:
        try:
            await cleanup_stale_connections()
            await check_node_health()
            await check_probe_health()
        except Exception:
            logger.exception("Error in cleanup loop")
        await asyncio.sleep(CLEANUP_INTERVAL)
