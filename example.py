"""Some simple tests/example for the Home Assistant client."""

import argparse
import asyncio
import logging
import sys
from contextlib import suppress

from aiohttp import ClientSession

from hass_client import HomeAssistantClient
from hass_client.models import Event

LOGGER = logging.getLogger()


def get_arguments() -> argparse.Namespace:
    """Get parsed passed in arguments."""
    parser = argparse.ArgumentParser(description="Home Assistant simple client for Python")
    parser.add_argument("--debug", action="store_true", help="Log with debug level")
    parser.add_argument("url", type=str, help="URL of server, ie http://homeassistant:8123")
    parser.add_argument("token", type=str, help="Long Lived Token")
    return parser.parse_args()


async def start_cli() -> None:
    """Run main."""
    args = get_arguments()
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level)

    async with ClientSession() as session:
        await connect(args, session)


async def connect(args: argparse.Namespace, session: ClientSession) -> None:
    """Connect to the server."""
    websocket_url = args.url.replace("http", "ws") + "/api/websocket"
    async with HomeAssistantClient(websocket_url, args.token, session) as client:
        # start listening will wait forever until the connection is closed/lost
        listener_task = asyncio.create_task(client.start_listening())
        await client.subscribe_events(log_events)
        await listener_task

def log_events(event: Event) -> None:
    """Log node value changes."""
    LOGGER.info("Received event: %s", event["event_type"])
    LOGGER.debug(event)


def main() -> None:
    """Run main."""
    with suppress(KeyboardInterrupt):
        asyncio.run(start_cli())

    sys.exit(0)


if __name__ == "__main__":
    main()
