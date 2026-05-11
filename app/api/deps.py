import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.application import Application
from app.models.node import Node
from app.models.tenant import Tenant


# Maximum clock skew for HMAC timestamp (seconds)
SIGNATURE_MAX_SKEW = 300


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


# --- Helpers for HMAC request signing ---

def _compute_signature(secret: str, method: str, path: str, timestamp: str, body: bytes, apk_sig: str = "") -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    if apk_sig:
        msg = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}\n{apk_sig}".encode()
    else:
        msg = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


# --- Dependency: App client auth ---
# Supports three modes:
#   (v2)     X-API-Key + X-Timestamp + X-Signature  (no app sig in HMAC)
#   (v1)     X-API-Key + X-Timestamp + X-Signature + X-App-Signature  (app sig in HMAC)
#   (legacy) X-API-Key + X-API-Secret

async def get_current_app(
    request: Request,
    x_api_key: str = Header(...),
    x_api_secret: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_app_signature: str | None = Header(default=None),
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

    if x_signature is not None:
        # New HMAC mode
        if not x_timestamp:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Timestamp")
        try:
            ts = int(x_timestamp)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Timestamp")
        now = int(time.time())
        if abs(now - ts) > SIGNATURE_MAX_SKEW:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Timestamp out of window")

        body = await request.body()
        apk_sig = (x_app_signature or "").lower()
        # Try v2 (without app sig), then v1 (with app sig) for backward compat
        expected_v2 = _compute_signature(
            secret=app.api_secret_plain,
            method=request.method,
            path=request.url.path,
            timestamp=x_timestamp,
            body=body,
        )
        expected_v1 = _compute_signature(
            secret=app.api_secret_plain,
            method=request.method,
            path=request.url.path,
            timestamp=x_timestamp,
            body=body,
            apk_sig=apk_sig,
        ) if apk_sig else ""
        if not (hmac.compare_digest(expected_v2, x_signature.lower()) or
                (expected_v1 and hmac.compare_digest(expected_v1, x_signature.lower()))):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    else:
        # Legacy mode
        if not x_api_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
        if not verify_secret(x_api_secret, app.api_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API secret")
        # Legacy clients bypass app-signature whitelist (they don't send it)

    if not app.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Application is disabled")

    tenant = await db.get(Tenant, app.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is disabled")

    return app
