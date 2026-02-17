import asyncio
import logging
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


app = FastAPI(title="Diode Backend", version="1.0.0", lifespan=lifespan)

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


@app.get("/", response_class=HTMLResponse)
async def web_root(request: Request):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/dashboard")


@app.get("/login", response_class=HTMLResponse)
async def web_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def web_login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username != settings.ADMIN_USERNAME or password != settings.ADMIN_PASSWORD:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    token = create_jwt_token({"sub": username, "role": "admin"})
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie("admin_token", token, httponly=True, max_age=86400)
    return response


@app.get("/logout")
async def web_logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("admin_token")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def web_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")

    nodes_result = await db.execute(select(Node))
    nodes = nodes_result.scalars().all()
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.status == "online")

    apps_result = await db.execute(select(func.count()).select_from(Application))
    total_apps = apps_result.scalar_one()

    active_conns = await db.execute(
        select(func.count()).select_from(Connection).where(Connection.status == "active")
    )
    total_active = active_conns.scalar_one()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "total_apps": total_apps,
        "active_connections": total_active,
    })


@app.get("/nodes", response_class=HTMLResponse)
async def web_nodes(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Node).order_by(Node.created_at.desc()))
    nodes = result.scalars().all()
    return templates.TemplateResponse("nodes.html", {"request": request, "nodes": nodes})


@app.get("/apps", response_class=HTMLResponse)
async def web_apps(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")

    result = await db.execute(
        select(Application).options(selectinload(Application.regions)).order_by(Application.created_at.desc())
    )
    apps = result.scalars().all()

    apps_data = []
    for a in apps:
        count_result = await db.execute(
            select(func.count()).select_from(Connection).where(
                Connection.app_id == a.id, Connection.status == "active"
            )
        )
        active = count_result.scalar_one()
        apps_data.append({"app": a, "regions": [r.region for r in a.regions], "active_connections": active})

    return templates.TemplateResponse("apps.html", {"request": request, "apps_data": apps_data})


@app.get("/apps/{app_id}", response_class=HTMLResponse)
async def web_app_detail(request: Request, app_id: str, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")

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

    return templates.TemplateResponse("app_detail.html", {
        "request": request,
        "app": app_obj,
        "regions": [r.region for r in app_obj.regions],
        "connections": connections,
        "active_connections": active_count,
    })


@app.get("/connections", response_class=HTMLResponse)
async def web_connections(request: Request, db: AsyncSession = Depends(get_db)):
    token = get_admin_token(request)
    if not token:
        return RedirectResponse(url="/login")
    try:
        decode_jwt_token(token)
    except Exception:
        return RedirectResponse(url="/login")

    result = await db.execute(
        select(Connection).order_by(Connection.connected_at.desc()).limit(200)
    )
    connections = result.scalars().all()
    return templates.TemplateResponse("connections.html", {"request": request, "connections": connections})
