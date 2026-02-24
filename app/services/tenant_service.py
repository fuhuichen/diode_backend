import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import hash_secret
from app.models.application import Application
from app.models.tenant import Tenant


async def create_tenant(db: AsyncSession, name: str, password: str) -> Tenant:
    hashed = hash_secret(password)
    tenant = Tenant(name=name, password=hashed)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def get_all_tenants(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Tenant, func.count(Application.id).label("app_count"))
        .outerjoin(Application, Application.tenant_id == Tenant.id)
        .group_by(Tenant.id)
        .order_by(Tenant.created_at.desc())
    )
    rows = result.all()
    return [{"tenant": row[0], "app_count": row[1]} for row in rows]


async def get_tenant_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.apps).selectinload(Application.regions))
        .where(Tenant.id == tenant_id)
    )
    return result.scalar_one_or_none()


async def update_tenant(
    db: AsyncSession, tenant: Tenant, name: str | None, password: str | None, is_active: bool | None
) -> Tenant:
    if name is not None:
        tenant.name = name
    if password is not None:
        tenant.password = hash_secret(password)
    if is_active is not None:
        tenant.is_active = is_active
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def delete_tenant(db: AsyncSession, tenant: Tenant) -> None:
    await db.delete(tenant)
    await db.commit()
