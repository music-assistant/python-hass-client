"""Some simple tests/examples for the Home Assistant client."""

import asyncio
import sys
from hass_client import HomeAssistant
import logging

LOGGER = logging.getLogger()

if __name__ == "__main__":

    logformat = logging.Formatter(
        "%(asctime)-15s %(levelname)-5s %(name)s.%(module)s -- %(message)s"
    )
    consolehandler = logging.StreamHandler()
    consolehandler.setFormatter(logformat)
    LOGGER.addHandler(consolehandler)
    LOGGER.setLevel(logging.DEBUG)

    if len(sys.argv) < 3:
        LOGGER.error("usage: test.py <url> <token>")
        sys.exit()

    url = sys.argv[1]
    token = sys.argv[2]
    loop = asyncio.get_event_loop()
    hass = HomeAssistant(url, token)


    async def hass_event(event, event_details):
        LOGGER.info("received event %s --> %s\n", event, event_details)
        
    hass.register_event_callback(hass_event, )

    async def run():
        await hass.connect()

    try:
        loop.create_task(run())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
        loop.close()
