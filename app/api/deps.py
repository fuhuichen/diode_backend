import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.application import Application
from app.models.node import Node
from app.models.tenant import Tenant


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_secret(plain), hashed)


def create_jwt_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def generate_api_key() -> str:
    return f"dk_{uuid.uuid4().hex}"


def generate_api_secret() -> str:
    return f"ds_{uuid.uuid4().hex}{uuid.uuid4().hex[:16]}"


def generate_node_token() -> str:
    return f"nt_{uuid.uuid4().hex}{uuid.uuid4().hex[:16]}"


# --- Dependency: Agent auth via X-Node-Token ---

async def get_current_node(
    x_node_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Node:
    result = await db.execute(select(Node).where(Node.node_token == x_node_token))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node token")
    return node


# --- Dependency: Admin auth via Bearer JWT ---

async def get_current_admin(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    token = authorization[7:]
    payload = decode_jwt_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return payload


# --- Dependency: App client auth via X-API-Key + X-API-Secret ---

async def get_current_app(
    x_api_key: str = Header(...),
    x_api_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Application:
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.regions))
        .where(Application.api_key == x_api_key)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if not verify_secret(x_api_secret, app.api_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API secret")
    if not app.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Application is disabled")

    # Check tenant is active
    tenant = await db.get(Tenant, app.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is disabled")

    return app
