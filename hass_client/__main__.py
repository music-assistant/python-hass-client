"""Basic CLI to test Home Assistant client."""
import argparse
import asyncio
import logging
import sys

import aiohttp

from .client import HomeAssistantClient

LOGGER = logging.getLogger(__package__)


def get_arguments() -> argparse.Namespace:
    """Get parsed passed in arguments."""

    parser = argparse.ArgumentParser(
        description="Home Assistant simple client for Python"
    )
    parser.add_argument("--debug", action="store_true", help="Log with debug level")
    parser.add_argument(
        "url", type=str, help="URL of server, ie http://homeassistant:8123"
    )
    parser.add_argument("token", type=str, help="Long Lived Token")
    arguments = parser.parse_args()
    return arguments


async def start_cli() -> None:
    """Run main."""
    args = get_arguments()
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level)

    async with aiohttp.ClientSession() as session:
        await connect(args, session)


async def connect(args: argparse.Namespace, session: aiohttp.ClientSession) -> None:
    """Connect to the server."""
    async with HomeAssistantClient(args.url, args.token, session) as client:
        client.register_event_callback(log_events)
        await asyncio.sleep(360)


def log_events(event: str, event_data: dict) -> None:
    """Log node value changes."""

    LOGGER.info("Received event: %s", event)
    LOGGER.debug(event_data)


def main() -> None:
    """Run main."""
    try:
        asyncio.run(start_cli())
    except KeyboardInterrupt:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
