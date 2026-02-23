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
import signal
import socket
import sys

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diode-agent")

HEARTBEAT_INTERVAL = 30  # seconds


def get_client_address(port: int = 41046) -> str:
    """Attempt to detect external IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"{ip}:{port}"
    except Exception:
        return f"127.0.0.1:{port}"


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

    async def heartbeat(self) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.backend_url}/api/agent/heartbeat",
                    headers=self.headers,
                    json={"client_address": self.client_address, "status": "running"},
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
                await self.heartbeat()

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
