import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import generate_api_key, generate_api_secret, hash_secret
from app.models.app_region import AppRegion
from app.models.application import Application
from app.models.connection import Connection


async def create_app(
    db: AsyncSession, name: str, max_concurrent: int, usage_limit: int, regions: list[str]
) -> tuple[Application, str]:
    api_key = generate_api_key()
    api_secret_plain = generate_api_secret()
    api_secret_hash = hash_secret(api_secret_plain)

    app = Application(
        name=name,
        api_key=api_key,
        api_secret=api_secret_hash,
        max_concurrent=max_concurrent,
        usage_limit=usage_limit,
    )
    db.add(app)
    await db.flush()

    for region in regions:
        db.add(AppRegion(app_id=app.id, region=region))

    await db.commit()
    await db.refresh(app, attribute_names=["regions"])
    return app, api_secret_plain


async def get_app_by_id(db: AsyncSession, app_id: uuid.UUID) -> Application | None:
    result = await db.execute(
        select(Application).options(selectinload(Application.regions)).where(Application.id == app_id)
    )
    return result.scalar_one_or_none()


async def get_all_apps(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Application).options(selectinload(Application.regions)).order_by(Application.created_at.desc())
    )
    apps = result.scalars().all()
    app_list = []
    for app in apps:
        active_count = await get_active_connection_count(db, app.id)
        app_list.append({
            "app": app,
            "regions": [r.region for r in app.regions],
            "active_connections": active_count,
        })
    return app_list


async def update_app(
    db: AsyncSession, app: Application, name: str | None, max_concurrent: int | None,
    usage_limit: int | None, regions: list[str] | None, is_active: bool | None,
) -> Application:
    if name is not None:
        app.name = name
    if max_concurrent is not None:
        app.max_concurrent = max_concurrent
    if usage_limit is not None:
        app.usage_limit = usage_limit
    if is_active is not None:
        app.is_active = is_active

    if regions is not None:
        await db.execute(delete(AppRegion).where(AppRegion.app_id == app.id))
        for region in regions:
            db.add(AppRegion(app_id=app.id, region=region))

    await db.commit()
    await db.refresh(app, attribute_names=["regions"])
    return app


async def delete_app(db: AsyncSession, app: Application) -> None:
    await db.delete(app)
    await db.commit()


async def get_active_connection_count(db: AsyncSession, app_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Connection).where(
            Connection.app_id == app_id, Connection.status == "active"
        )
    )
    return result.scalar_one()
