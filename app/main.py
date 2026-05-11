import asyncio
import json
import logging
import os
import re
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


def format_gb(value: int) -> str:
    """Convert bytes to GB display with 2 decimal places."""
    gb = value / (1024 ** 3)
    return f"{gb:.2f} GB"


def format_mb(value: int) -> str:
    """Convert bytes to MB display with 1 decimal place."""
    mb = value / (1024 ** 2)
    return f"{mb:.1f} MB"


templates.env.filters["format_gb"] = format_gb
templates.env.filters["format_mb"] = format_mb


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

    total_usage = sum(a.usage_bytes for a in apps)

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


@app.get("/stats", response_class=HTMLResponse)
async def web_stats(request: Request):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))
    return templates.TemplateResponse("stats.html", {"request": request})


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


# --- Client Logs Web Routes ---

CLIENTLOG_ROOT = Path("clientlogs")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
SAFE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_admin_or_redirect(request: Request):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url=_prefix(request, "/login"))
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url=_prefix(request, "/login"))
    return None


@app.get("/clientlogs", response_class=HTMLResponse)
async def web_clientlogs(request: Request, q: str = "", flavor: str = "", limit: int = 200):
    redirect = _require_admin_or_redirect(request)
    if redirect:
        return redirect

    entries: list[dict] = []
    if CLIENTLOG_ROOT.exists():
        for date_dir in sorted(CLIENTLOG_ROOT.iterdir(), reverse=True):
            if not date_dir.is_dir() or not SAFE_DATE.match(date_dir.name):
                continue
            for f in sorted(date_dir.iterdir(), reverse=True):
                if f.suffix != ".json":
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if flavor and data.get("flavor") != flavor:
                    continue
                if q:
                    hay = " ".join(str(v) for v in data.values() if v).lower()
                    if q.lower() not in hay:
                        continue
                entries.append({
                    "date": date_dir.name,
                    "filename": f.name,
                    "received_at": data.get("received_at", ""),
                    "app_name": data.get("app_name", ""),
                    "flavor": data.get("flavor", ""),
                    "device_brand": data.get("device_brand", ""),
                    "device_model": data.get("device_model", ""),
                    "os_version": data.get("os_version", ""),
                    "app_version": data.get("app_version", ""),
                    "client_ip": data.get("client_ip", ""),
                    "attempt_count": data.get("attempt_count", 0),
                    "last_error": data.get("last_error", "") or "",
                })
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break

    # 蒐集去重 flavor 給篩選下拉
    flavors = sorted({e["flavor"] for e in entries if e["flavor"]})
    return templates.TemplateResponse("clientlogs.html", {
        "request": request,
        "entries": entries,
        "q": q,
        "flavor": flavor,
        "flavors": flavors,
        "limit": limit,
    })


@app.get("/clientlogs/{date}/{filename}", response_class=HTMLResponse)
async def web_clientlog_detail(request: Request, date: str, filename: str):
    redirect = _require_admin_or_redirect(request)
    if redirect:
        return redirect

    if not SAFE_DATE.match(date) or not SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="invalid path")
    fpath = (CLIENTLOG_ROOT / date / filename).resolve()
    root = CLIENTLOG_ROOT.resolve()
    if not str(fpath).startswith(str(root)) or not fpath.exists():
        raise HTTPException(status_code=404, detail="not found")
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="failed to parse log")
    return templates.TemplateResponse("clientlog_detail.html", {
        "request": request,
        "entry": data,
        "date": date,
        "filename": filename,
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
