from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.config import GatewaySettings
from buddy_gateway.core_client import BuddyCoreClient
from buddy_gateway.state import GatewayState


logger = logging.getLogger(__name__)


async def serve(settings: GatewaySettings) -> None:
    state = GatewayState(session_history_limit=settings.session_history_limit)
    core_client = BuddyCoreClient(base_url=settings.buddy_core_base_url)
    http_server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(settings=settings, state=state, core_client=core_client),
            host=settings.host,
            port=settings.http_port,
            log_level="info",
        )
    )
    websocket_server = uvicorn.Server(
        uvicorn.Config(
            create_websocket_app(settings=settings, state=state, core_client=core_client),
            host=settings.host,
            port=settings.websocket_port,
            log_level="info",
        )
    )

    logger.info("Buddy Device Gateway HTTP OTA: http://%s:%s/xiaozhi/ota/", settings.host, settings.http_port)
    logger.info("Buddy Device Gateway WebSocket: %s", settings.websocket_url())
    logger.info("Buddy Core base URL: %s", settings.buddy_core_base_url)
    await asyncio.gather(http_server.serve(), websocket_server.serve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Buddy Device Gateway v0.2")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for HTTP and WebSocket servers.")
    parser.add_argument("--http-port", type=int, default=8003, help="HTTP OTA port.")
    parser.add_argument("--websocket-port", type=int, default=8000, help="WebSocket port.")
    parser.add_argument(
        "--buddy-core-base-url",
        default="http://127.0.0.1:8010",
        help="Buddy Core base URL used for debug text loop requests.",
    )
    parser.add_argument(
        "--advertise-host",
        default=None,
        help="Host/IP returned in OTA websocket.url. Defaults to LAN auto-detection.",
    )
    parser.add_argument("--session-history-limit", type=int, default=50, help="Recent session history size.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    settings = GatewaySettings(
        host=args.host,
        http_port=args.http_port,
        websocket_port=args.websocket_port,
        advertise_host=args.advertise_host,
        buddy_core_base_url=args.buddy_core_base_url,
        session_history_limit=args.session_history_limit,
    )
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
