import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.api.client import router as client_router
from app.api.deps import create_jwt_token, decode_jwt_token
from app.background.stale_cleanup import run_cleanup_loop
from app.config import settings
from app.database import get_db
from app.models.application import Application
from app.models.connection import Connection
from app.models.node import Node
from app.models.tenant import Tenant
from app.services.app_service import get_active_connection_count
from app.services.tenant_service import get_all_tenants, get_tenant_by_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_cleanup_loop())
    logger.info("Diode Backend started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Diode Backend",
    version="1.0.0",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),
)

# Routers
app.include_router(agent_router)
app.include_router(admin_router)
app.include_router(client_router)

# Templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# --- Web UI Routes ---

def get_admin_token(request: Request) -> str | None:
    return request.cookies.get("admin_token")


def _prefix(request: Request, path: str) -> str:
    """Prepend root_path to an internal path for redirects."""
    return request.scope.get("root_path", "") + path


@app.get("/", response_class=HTMLResponse)
async def web_root(request: Request):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))
    return RedirectResponse(url=_prefix(request, "/dashboard"))


@app.get("/login", response_class=HTMLResponse)
async def web_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def web_login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username != settings.ADMIN_USERNAME or password != settings.ADMIN_PASSWORD:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    token = create_jwt_token({"sub": username, "role": "admin"})
    response = RedirectResponse(url=_prefix(request, "/dashboard"), status_code=303)
    response.set_cookie("admin_token", token, httponly=False, max_age=86400, path=request.scope.get("root_path", "") or "/")
    return response


@app.get("/logout")
async def web_logout(request: Request):
    response = RedirectResponse(url=_prefix(request, "/login"))
    response.delete_cookie("admin_token", path=request.scope.get("root_path", "") or "/")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def web_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    nodes_result = await db.execute(select(Node).order_by(Node.created_at.desc()))
    nodes = list(nodes_result.scalars().all())
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.status == "online")
    unhealthy_nodes = sum(1 for n in nodes if n.status == "unhealthy")

    apps_result = await db.execute(
        select(Application).options(selectinload(Application.regions)).order_by(Application.created_at.desc())
    )
    apps = list(apps_result.scalars().all())
    total_apps = len(apps)

    active_conns = await db.execute(
        select(func.count()).select_from(Connection).where(Connection.status == "active")
    )
    total_active = active_conns.scalar_one()

    total_conns = await db.execute(select(func.count()).select_from(Connection))
    total_connections = total_conns.scalar_one()

    total_usage = sum(a.usage_count for a in apps)

    # Tenant count
    tenants_data = await get_all_tenants(db)
    total_tenants = len(tenants_data)

    # Recent connections (last 10)
    recent_conns_result = await db.execute(
        select(Connection).order_by(Connection.connected_at.desc()).limit(10)
    )
    recent_connections = list(recent_conns_result.scalars().all())

    # Region stats
    region_stats = {}
    for n in nodes:
        r = n.region
        if r not in region_stats:
            region_stats[r] = {"total": 0, "online": 0}
        region_stats[r]["total"] += 1
        if n.status == "online":
            region_stats[r]["online"] += 1

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "unhealthy_nodes": unhealthy_nodes,
        "total_apps": total_apps,
        "active_connections": total_active,
        "total_connections": total_connections,
        "total_usage": total_usage,
        "total_tenants": total_tenants,
        "nodes": nodes[:5],
        "apps": apps[:5],
        "recent_connections": recent_connections,
        "region_stats": region_stats,
    })


# --- Tenant Web Routes ---

@app.get("/tenants", response_class=HTMLResponse)
async def web_tenants(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    tenants_data = await get_all_tenants(db)
    return templates.TemplateResponse("tenants.html", {"request": request, "tenants_data": tenants_data})


@app.get("/tenants/{tenant_id}", response_class=HTMLResponse)
async def web_tenant_detail(request: Request, tenant_id: str, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    import uuid as uuid_mod
    tenant = await get_tenant_by_id(db, uuid_mod.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Build apps data with active connections
    apps_data = []
    for app_obj in tenant.apps:
        active_count = await get_active_connection_count(db, app_obj.id)
        apps_data.append({
            "app": app_obj,
            "regions": [r.region for r in app_obj.regions],
            "active_connections": active_count,
        })

    # Get available regions from existing nodes
    nodes_result = await db.execute(select(Node.region).distinct())
    available_regions = sorted([row[0] for row in nodes_result.all()])

    return templates.TemplateResponse("tenant_detail.html", {
        "request": request,
        "tenant": tenant,
        "apps_data": apps_data,
        "available_regions": available_regions,
    })


@app.get("/nodes", response_class=HTMLResponse)
async def web_nodes(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    result = await db.execute(select(Node).order_by(Node.created_at.desc()))
    nodes = result.scalars().all()
    return templates.TemplateResponse("nodes.html", {"request": request, "nodes": nodes})


@app.get("/apps", response_class=HTMLResponse)
async def web_apps(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    result = await db.execute(
        select(Application, Tenant.name.label("tenant_name"))
        .join(Tenant, Application.tenant_id == Tenant.id)
        .options(selectinload(Application.regions))
        .order_by(Application.created_at.desc())
    )
    rows = result.all()

    apps_data = []
    for row in rows:
        a = row[0]
        tenant_name = row[1]
        count_result = await db.execute(
            select(func.count()).select_from(Connection).where(
                Connection.app_id == a.id, Connection.status == "active"
            )
        )
        active = count_result.scalar_one()
        apps_data.append({
            "app": a,
            "tenant_name": tenant_name,
            "regions": [r.region for r in a.regions],
            "active_connections": active,
        })

    return templates.TemplateResponse("apps.html", {"request": request, "apps_data": apps_data})


@app.get("/apps/{app_id}", response_class=HTMLResponse)
async def web_app_detail(request: Request, app_id: str, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    import uuid as uuid_mod
    result = await db.execute(
        select(Application).options(selectinload(Application.regions)).where(Application.id == uuid_mod.UUID(app_id))
    )
    app_obj = result.scalar_one_or_none()
    if not app_obj:
        raise HTTPException(status_code=404, detail="App not found")

    conns_result = await db.execute(
        select(Connection).where(Connection.app_id == app_obj.id).order_by(Connection.connected_at.desc()).limit(100)
    )
    connections = conns_result.scalars().all()

    active_count = sum(1 for c in connections if c.status == "active")

    # Get available regions from existing nodes
    nodes_result = await db.execute(select(Node.region).distinct())
    available_regions = sorted([row[0] for row in nodes_result.all()])

    return templates.TemplateResponse("app_detail.html", {
        "request": request,
        "app": app_obj,
        "regions": [r.region for r in app_obj.regions],
        "connections": connections,
        "active_connections": active_count,
        "available_regions": available_regions,
    })


@app.get("/connections", response_class=HTMLResponse)
async def web_connections(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))

    result = await db.execute(
        select(Connection).order_by(Connection.connected_at.desc()).limit(200)
    )
    connections = result.scalars().all()
    return templates.TemplateResponse("connections.html", {"request": request, "connections": connections})
