#!/usr/bin/env python3
from __future__ import annotations

"""
Diode Node Agent

Runs on each diode_remote node. Registers with the backend,
sends periodic heartbeats, and deregisters on shutdown.

Usage:
    python agent.py --backend-url http://backend:8000 --node-token nt_xxx --region asia-east

Environment variables (alternative to CLI args):
    BACKEND_URL, NODE_TOKEN, REGION, NODE_NAME, CLIENT_ADDRESS
"""

import argparse
import asyncio
import logging
import os
import re
import signal
import struct
import subprocess
import sys
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diode-agent")

HEARTBEAT_INTERVAL = 30  # seconds
PROBE_TIMEOUT = 10  # seconds
PROBE_HOST = "connectivitycheck.gstatic.com"
PROBE_PORT = 80


def get_diode_client_address() -> str | None:
    """Parse the diode client address from `diode config`."""
    try:
        result = subprocess.run(
            ["diode", "config"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        match = re.search(r"Client address\s*:\s*(0x[0-9a-fA-F]+)", output)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning(f"Failed to get diode client address: {e}")
    return None


def get_client_address(port: int = 41046) -> str:
    """Return diode client address, falling back to external IP."""
    diode_addr = get_diode_client_address()
    if diode_addr:
        return diode_addr
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"{ip}:{port}"
    except Exception:
        return f"127.0.0.1:{port}"


async def probe_socks5() -> tuple[bool, float | None, str | None]:
    """Test local SOCKS5 proxy by connecting through it to an external host.

    Returns (success, latency_ms, error_message).
    """
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 1080),
            timeout=PROBE_TIMEOUT,
        )

        # SOCKS5 greeting: version=5, 1 auth method, no-auth(0)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(2), timeout=PROBE_TIMEOUT)
        if resp != b"\x05\x00":
            writer.close()
            return False, None, f"SOCKS5 greeting failed: {resp.hex()}"

        # SOCKS5 CONNECT to probe host
        host_bytes = PROBE_HOST.encode()
        # version=5, cmd=CONNECT(1), rsv=0, atyp=DOMAIN(3), len, domain, port
        connect_req = (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + struct.pack("!H", PROBE_PORT)
        )
        writer.write(connect_req)
        await writer.drain()

        # Read CONNECT response (at least 10 bytes for IPv4)
        resp = await asyncio.wait_for(reader.read(256), timeout=PROBE_TIMEOUT)
        if len(resp) < 4 or resp[1] != 0x00:
            writer.close()
            return False, None, f"SOCKS5 CONNECT failed: rep={resp[1] if len(resp) > 1 else 'short'}"

        # Send HTTP GET
        http_req = (
            f"GET /generate_204 HTTP/1.1\r\n"
            f"Host: {PROBE_HOST}\r\n"
            f"Connection: close\r\n\r\n"
        )
        writer.write(http_req.encode())
        await writer.drain()

        # Read HTTP response
        http_resp = await asyncio.wait_for(reader.read(1024), timeout=PROBE_TIMEOUT)
        writer.close()

        elapsed_ms = (time.monotonic() - start) * 1000

        if b"HTTP/" in http_resp:
            logger.info(f"Probe OK: {elapsed_ms:.0f}ms")
            return True, elapsed_ms, None
        else:
            return False, elapsed_ms, "No HTTP response received"

    except asyncio.TimeoutError:
        return False, None, "Probe timeout"
    except ConnectionRefusedError:
        return False, None, "SOCKS5 port 1080 refused"
    except Exception as e:
        return False, None, str(e)


class DiodeAgent:
    def __init__(self, backend_url: str, node_token: str, region: str,
                 name: str | None = None, client_address: str | None = None):
        self.backend_url = backend_url.rstrip("/")
        self.node_token = node_token
        self.region = region
        self.name = name
        self.client_address = client_address or get_client_address()
        self.running = False
        self.node_id: str | None = None

    @property
    def headers(self) -> dict:
        return {"X-Node-Token": self.node_token, "Content-Type": "application/json"}

    async def register(self) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.backend_url}/api/agent/register",
                    headers=self.headers,
                    json={"region": self.region, "name": self.name},
                    timeout=10,
                )
                if resp.status_code == 201:
                    data = resp.json()
                    self.node_id = data["node_id"]
                    logger.info(f"Registered as node {self.node_id} in region '{self.region}'")
                    return True
                else:
                    logger.error(f"Registration failed: {resp.status_code} {resp.text}")
                    return False
            except Exception as e:
                logger.error(f"Registration error: {e}")
                return False

    async def heartbeat(
        self,
        probe_ok: bool | None = None,
        probe_latency_ms: float | None = None,
        probe_error: str | None = None,
    ) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "client_address": self.client_address,
                    "status": "running",
                    "probe_ok": probe_ok,
                    "probe_latency_ms": probe_latency_ms,
                    "probe_error": probe_error,
                }
                resp = await client.post(
                    f"{self.backend_url}/api/agent/heartbeat",
                    headers=self.headers,
                    json=payload,
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.debug("Heartbeat OK")
                    return True
                else:
                    logger.warning(f"Heartbeat failed: {resp.status_code}")
                    return False
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")
                return False

    async def deregister(self):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.backend_url}/api/agent/deregister",
                    headers=self.headers,
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.info("Deregistered successfully")
                else:
                    logger.warning(f"Deregister failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Deregister error: {e}")

    async def run(self):
        self.running = True

        # Register
        if not await self.register():
            logger.error("Failed to register, retrying in 10 seconds...")
            while self.running:
                await asyncio.sleep(10)
                if await self.register():
                    break

        # Heartbeat loop
        while self.running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self.running:
                ok, latency, err = await probe_socks5()
                await self.heartbeat(probe_ok=ok, probe_latency_ms=latency, probe_error=err)

    async def shutdown(self):
        logger.info("Shutting down...")
        self.running = False
        await self.deregister()


async def main():
    parser = argparse.ArgumentParser(description="Diode Node Agent")
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://localhost:8000"))
    parser.add_argument("--node-token", default=os.getenv("NODE_TOKEN"))
    parser.add_argument("--region", default=os.getenv("REGION"))
    parser.add_argument("--name", default=os.getenv("NODE_NAME"))
    parser.add_argument("--client-address", default=os.getenv("CLIENT_ADDRESS"))
    args = parser.parse_args()

    if not args.node_token:
        print("Error: --node-token or NODE_TOKEN is required", file=sys.stderr)
        sys.exit(1)
    if not args.region:
        print("Error: --region or REGION is required", file=sys.stderr)
        sys.exit(1)

    agent = DiodeAgent(
        backend_url=args.backend_url,
        node_token=args.node_token,
        region=args.region,
        name=args.name,
        client_address=args.client_address,
    )

    loop = asyncio.get_event_loop()

    def handle_signal():
        asyncio.ensure_future(agent.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
