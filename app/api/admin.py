import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    create_jwt_token,
    generate_node_token,
    get_current_admin,
    hash_secret,
    verify_secret,
)
from app.config import settings
from app.database import get_db
from app.models.connection import Connection
from app.models.node import Node
from app.models.tenant import Tenant
from app.schemas.application import (
    AppCreateRequest,
    AppCreateResponse,
    AppResponse,
    AppUpdateRequest,
)
from app.schemas.node import NodeCreateRequest, NodeCreateResponse, NodeResponse
from app.schemas.tenant import TenantCreateRequest, TenantResponse, TenantUpdateRequest
from app.services.app_service import (
    check_app_name_unique,
    create_app,
    delete_app,
    get_active_connection_count,
    get_all_apps,
    get_app_by_id,
    update_app,
)
from app.services.tenant_service import (
    create_tenant,
    delete_tenant,
    get_all_tenants,
    get_tenant_by_id,
    update_tenant,
)
from app.services.node_service import get_all_nodes

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Auth ---

class LoginRequest:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password


from pydantic import BaseModel


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginBody):
    if body.username != settings.ADMIN_USERNAME or body.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_jwt_token({"sub": body.username, "role": "admin"})
    return {"access_token": token, "token_type": "bearer"}


# --- Dashboard ---

@router.get("/dashboard", dependencies=[Depends(get_current_admin)])
async def dashboard(db: AsyncSession = Depends(get_db)):
    nodes = await get_all_nodes(db)
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.status == "online")

    apps_data = await get_all_apps(db)
    total_apps = len(apps_data)

    active_conns = await db.execute(
        select(func.count()).select_from(Connection).where(Connection.status == "active")
    )
    total_active = active_conns.scalar_one()

    tenants_data = await get_all_tenants(db)
    total_tenants = len(tenants_data)

    return {
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "total_apps": total_apps,
        "active_connections": total_active,
        "total_tenants": total_tenants,
    }


# --- Tenant Management ---

@router.post("/tenants", response_model=TenantResponse, status_code=201, dependencies=[Depends(get_current_admin)])
async def create_tenant_endpoint(req: TenantCreateRequest, db: AsyncSession = Depends(get_db)):
    tenant = await create_tenant(db, req.name, req.password)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        app_count=0,
        created_at=tenant.created_at,
    )


@router.get("/tenants", response_model=list[TenantResponse], dependencies=[Depends(get_current_admin)])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    tenants_data = await get_all_tenants(db)
    return [
        TenantResponse(
            id=d["tenant"].id,
            name=d["tenant"].name,
            is_active=d["tenant"].is_active,
            app_count=d["app_count"],
            created_at=d["tenant"].created_at,
        )
        for d in tenants_data
    ]


@router.get("/tenants/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(get_current_admin)])
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        app_count=len(tenant.apps),
        created_at=tenant.created_at,
    )


@router.put("/tenants/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(get_current_admin)])
async def update_tenant_endpoint(tenant_id: uuid.UUID, req: TenantUpdateRequest, db: AsyncSession = Depends(get_db)):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant = await update_tenant(db, tenant, req.name, req.password, req.is_active)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        app_count=len(tenant.apps) if hasattr(tenant, 'apps') and tenant.apps else 0,
        created_at=tenant.created_at,
    )


@router.delete("/tenants/{tenant_id}", dependencies=[Depends(get_current_admin)])
async def delete_tenant_endpoint(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(db, tenant)
    return {"message": "deleted"}


# --- Node Management ---

@router.post("/nodes", response_model=NodeCreateResponse, status_code=201, dependencies=[Depends(get_current_admin)])
async def create_node(req: NodeCreateRequest, db: AsyncSession = Depends(get_db)):
    token = generate_node_token()
    node = Node(name=req.name, region=req.region, node_token=token)
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return NodeCreateResponse(id=node.id, name=node.name, region=node.region, node_token=token)


@router.get("/nodes", response_model=list[NodeResponse], dependencies=[Depends(get_current_admin)])
async def list_nodes(db: AsyncSession = Depends(get_db)):
    nodes = await get_all_nodes(db)
    return nodes


@router.delete("/nodes/{node_id}", dependencies=[Depends(get_current_admin)])
async def remove_node(node_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.delete(node)
    await db.commit()
    return {"message": "deleted"}


# --- App Management ---

@router.post("/apps", response_model=AppCreateResponse, status_code=201, dependencies=[Depends(get_current_admin)])
async def create_application(req: AppCreateRequest, db: AsyncSession = Depends(get_db)):
    # Verify tenant exists
    tenant = await db.get(Tenant, req.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not await check_app_name_unique(db, req.tenant_id, req.name):
        raise HTTPException(status_code=409, detail="An app with this name already exists for this tenant")
    app, secret_plain = await create_app(db, req.tenant_id, req.name, req.max_concurrent, req.usage_limit, req.regions)
    return AppCreateResponse(
        id=app.id,
        name=app.name,
        tenant_id=app.tenant_id,
        api_key=app.api_key,
        api_secret=secret_plain,
        max_concurrent=app.max_concurrent,
        usage_limit=app.usage_limit,
        regions=[r.region for r in app.regions],
    )


@router.get("/apps", response_model=list[AppResponse], dependencies=[Depends(get_current_admin)])
async def list_apps(db: AsyncSession = Depends(get_db)):
    apps_data = await get_all_apps(db)
    return [
        AppResponse(
            id=d["app"].id,
            name=d["app"].name,
            tenant_id=d["app"].tenant_id,
            tenant_name=d["tenant_name"],
            api_key=d["app"].api_key,
            api_secret=d["app"].api_secret_plain,
            max_concurrent=d["app"].max_concurrent,
            usage_limit=d["app"].usage_limit,
            usage_count=d["app"].usage_count,
            is_active=d["app"].is_active,
            regions=d["regions"],
            active_connections=d["active_connections"],
            created_at=d["app"].created_at,
        )
        for d in apps_data
    ]


@router.get("/apps/{app_id}", response_model=AppResponse, dependencies=[Depends(get_current_admin)])
async def get_application(app_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    app = await get_app_by_id(db, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    active = await get_active_connection_count(db, app.id)
    tenant = await db.get(Tenant, app.tenant_id)
    return AppResponse(
        id=app.id,
        name=app.name,
        tenant_id=app.tenant_id,
        tenant_name=tenant.name if tenant else "",
        api_key=app.api_key,
        api_secret=app.api_secret_plain,
        max_concurrent=app.max_concurrent,
        usage_limit=app.usage_limit,
        usage_count=app.usage_count,
        is_active=app.is_active,
        regions=[r.region for r in app.regions],
        active_connections=active,
        created_at=app.created_at,
    )


@router.put("/apps/{app_id}", response_model=AppResponse, dependencies=[Depends(get_current_admin)])
async def update_application(app_id: uuid.UUID, req: AppUpdateRequest, db: AsyncSession = Depends(get_db)):
    app = await get_app_by_id(db, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if req.name is not None and not await check_app_name_unique(db, app.tenant_id, req.name, exclude_app_id=app.id):
        raise HTTPException(status_code=409, detail="An app with this name already exists for this tenant")
    app = await update_app(db, app, req.name, req.max_concurrent, req.usage_limit, req.regions, req.is_active)
    active = await get_active_connection_count(db, app.id)
    tenant = await db.get(Tenant, app.tenant_id)
    return AppResponse(
        id=app.id,
        name=app.name,
        tenant_id=app.tenant_id,
        tenant_name=tenant.name if tenant else "",
        api_key=app.api_key,
        api_secret=app.api_secret_plain,
        max_concurrent=app.max_concurrent,
        usage_limit=app.usage_limit,
        usage_count=app.usage_count,
        is_active=app.is_active,
        regions=[r.region for r in app.regions],
        active_connections=active,
        created_at=app.created_at,
    )


@router.delete("/apps/{app_id}", dependencies=[Depends(get_current_admin)])
async def delete_application(app_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    app = await get_app_by_id(db, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    await delete_app(db, app)
    return {"message": "deleted"}
