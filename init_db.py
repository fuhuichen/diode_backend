#!/usr/bin/env python3
"""Initialize database tables directly (alternative to alembic for quick setup)."""
import asyncio

from app.database import Base, engine
from app.models.node import Node  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.app_region import AppRegion  # noqa: F401
from app.models.connection import Connection  # noqa: F401


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created successfully.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init())
