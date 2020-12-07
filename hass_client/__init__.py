"""
Home Assistant Client for python.

Simple wrapper for the websockets and rest Api's
provided by Home Assistant that allows for rapid development of apps
connected to Hopme Assistant.
"""

import asyncio
import functools
import logging
import os
from typing import Any, Awaitable, Callable, List, Union

import aiohttp

LOGGER = logging.getLogger("hass-client")

EVENT_CONNECTED = "connected"
EVENT_STATE_CHANGED = "state_changed"

IS_SUPERVISOR = os.environ.get("HASSIO_TOKEN") is not None


class HomeAssistant:
    """Connection to HomeAssistant (over websockets)."""

    def __init__(self, url: str = None, token: str = None, loop=None):
        """
        Initialize the connection to HomeAssistant.

            :param url: full url to the HomeAssistant instance.
            :param token: a long lived token.
        If url and token are omitted, assume supervisor install.
        """
        self._loop = loop
        self._states = {}
        self.__async_send_ws = None
        self.__last_id = 10
        self._ws_callbacks = {}
        self._device_registry = {}
        self._entity_registry = {}
        self._area_registry = {}
        if not url and not token and IS_SUPERVISOR:
            self._host = "hassio/homeassistant"
            self._use_ssl = False
            self._token = None
        elif url.startswith("https://"):
            self._use_ssl = True
            self._host = url.replace("https://", "")
            self._token = token
        elif url and token:
            self._use_ssl = False
            self._host = url.replace("http://", "")
            self._token = token
        else:
            raise RuntimeError("Please provide a valid url and token!")
        self._http_session = None
        self._initial_state_received = False
        self._connected_callback = None
        self._event_listeners = []
        self._ws_task = None

    async def async_connect(self):
        """Connect to HomeAssistant."""
        if not self._loop:
            self._loop = asyncio.get_running_loop()
        self._http_session = aiohttp.ClientSession(
            loop=self._loop, connector=aiohttp.TCPConnector()
        )
        self._ws_task = self._loop.create_task(self.__async_hass_websocket())

    async def async_close(self):
        """Close/stop the connection."""
        if self._ws_task:
            self._ws_task.cancel()
        if self._http_session:
            await self._http_session.close()
        LOGGER.info("Disconnected from Home Assistant")

    def register_event_callback(
        self,
        cb_func: Callable[..., Union[None, Awaitable]],
        event_filter: Union[None, str, List[str]] = None,
        entity_filter: Union[None, str, List[str]] = None,
    ) -> Callable:
        """
        Add callback for events.

        Returns function to remove the listener.
            :param cb_func: callback function or coroutine
            :param event_filter: Optionally only listen for these events
            :param event_filter: In case of state_changed event, only forward these entities
        """
        listener = (cb_func, event_filter, entity_filter)
        self._event_listeners.append(listener)

        def remove_listener():
            self._event_listeners.remove(listener)

        return remove_listener

    @property
    def device_registry(self) -> dict:
        """Return device registry."""
        if not self._device_registry:
            LOGGER.warning("Connection is not yet ready.")
        return self._device_registry

    @property
    def entity_registry(self) -> dict:
        """Return device registry."""
        if not self._entity_registry:
            LOGGER.warning("Connection is not yet ready.")
        return self._entity_registry

    @property
    def area_registry(self) -> dict:
        """Return device registry."""
        return self._area_registry

    @property
    def states(self) -> dict:
        """Return all hass states."""
        return self._states

    @property
    def lights(self) -> List[dict]:
        """Return all light entities."""
        return self.items_by_domain("light")

    @property
    def switches(self) -> List[dict]:
        """Return all switch entities."""
        return self.items_by_domain("switch")

    @property
    def media_players(self) -> List[dict]:
        """Return all media_player entities."""
        return self.items_by_domain("media_player")

    @property
    def sensors(self) -> List[dict]:
        """Return all sensor entities."""
        return self.items_by_domain("sensor")

    @property
    def binary_sensors(self) -> List[dict]:
        """Return all binary_sensor entities."""
        return self.items_by_domain("binary_sensor")

    def items_by_domain(self, domain: str) -> List[dict]:
        """Retrieve all items for a domain."""
        if not self._initial_state_received:
            LOGGER.warning("Connection is not yet ready.")
        all_items = []
        for key, value in self._states.items():
            if key.startswith(domain):
                all_items.append(value)
        return all_items

    def get_state(self, entity_id: str, attribute: str = "state") -> dict:
        """
        Get state(obj) of a Home Assistant entity.

            :param entity_id: The entity id for which the state must be returned.
            :param attribute: The attribute to return from the state object.
        """
        if not self._initial_state_received:
            LOGGER.warning("Connection is not yet ready.")
        state_obj = self._states.get(entity_id)
        if state_obj:
            if attribute == "state":
                return state_obj["state"]
            if attribute:
                return state_obj["attributes"].get(attribute)
            return state_obj
        return None

    async def async_get_state(self, entity_id: str, attribute: str = "state") -> dict:
        """
        Get state(obj) of a Home Assistant entity.

            :param entity_id: The entity id for which the state must be returned.
            :param attribute: The attribute to return from the state object.
        """
        return self.get_state(entity_id, attribute)  # safe to call in loop

    async def async_call_service(
        self, domain: str, service: str, service_data: dict = None
    ):
        """
        Call service on Home Assistant.

            :param url: Domain of the service to call (e.g. light, switch).
            :param service: The service to call  (e.g. turn_on).
            :param service_data: Optional dict with parameters (e.g. { brightness: 20 }).
        """
        if not self._initial_state_received:
            LOGGER.warning("Connection is not yet ready.")
        msg = {"type": "call_service", "domain": domain, "service": service}
        if service_data:
            msg["service_data"] = service_data
        return await self.__async_send_ws(msg)

    async def async_set_state(
        self, entity_id: str, new_state: str, state_attributes: dict = None
    ):
        """
        Set state on a homeassistant entity.

            :param entity_id: Entity id to set state for.
            :param new_state: The new state.
            :param state_attributes: Optional dict with parameters (e.g. { name: 'Cool entity' }).
        """
        if state_attributes is None:
            state_attributes = {}
        data = {
            "state": new_state,
            "entity_id": entity_id,
            "attributes": state_attributes,
        }
        return await self.__async_post_data(f"states/{entity_id}", data)

    async def __async_hass_websocket(self):
        """Receive events from Hass through websockets."""
        protocol = "wss" if self._use_ssl else "ws"
        while True:
            try:
                LOGGER.info("Connecting to %s", self._host)
                self.__async_send_ws = None
                self.__last_id = 10
                self._ws_callbacks = {}

                async with self._http_session.ws_connect(
                    f"{protocol}://{self._host}/api/websocket", verify_ssl=False
                ) as conn:

                    # callback to send messages back to the ws
                    async def _send_msg(msg, callback=None):
                        """Callback: send message to the websockets client."""
                        msg_id = self.__last_id + 1
                        self.__last_id = msg_id
                        msg["id"] = msg_id
                        if callback:
                            self._ws_callbacks[msg_id] = callback
                        await conn.send_json(msg)

                    self.__async_send_ws = _send_msg

                    async for msg in conn:
                        await self.__process_ws_message(conn, msg)

            except (
                aiohttp.client_exceptions.ClientConnectorError,
                ConnectionRefusedError,
            ) as exc:
                LOGGER.error(exc)
                await asyncio.sleep(10)

    async def __process_ws_message(self, conn, msg):
        """Process incoming WS message."""
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = msg.json()
            if data["type"] == "auth_required":
                # send auth token
                auth_msg = {"type": "auth", "access_token": self.__get_token()}
                await conn.send_json(auth_msg)
            elif data["type"] == "auth_invalid":
                raise Exception(data)
            elif data["type"] == "auth_ok":
                LOGGER.info("Connected to %s", self._host)
                # subscribe to events
                await self.__async_subscribe_events()
            elif data["id"] in self._ws_callbacks:
                self._loop.create_task(self._ws_callbacks[data["id"]](data))
        elif msg.type == aiohttp.WSMsgType.ERROR:
            raise Exception("error in websocket")

    async def __async_subscribe_events(self):
        """Subscribe to common events when the ws was (re)connected."""
        # request all current states
        await self.__async_send_ws(
            {"type": "get_states"}, callback=self.__async_receive_all_states
        )
        # subscribe to all events
        await self.__async_send_ws(
            {"type": "subscribe_events"}, callback=self.__async_state_changed
        )
        # request all area, device and entity registry
        await self.__async_send_ws(
            {"type": "config/area_registry/list"},
            callback=self.__async_receive_area_registry,
        )
        # request device registry
        await self.__async_send_ws(
            {"type": "config/device_registry/list"},
            callback=self.__async_receive_device_registry,
        )
        # request entity registry
        await self.__async_send_ws(
            {"type": "config/entity_registry/list"},
            callback=self.__async_receive_entity_registry,
        )

    async def __async_state_changed(self, msg: dict):
        """Received state_changed event."""
        if "event" not in msg:
            return
        event_type = msg["event"]["event_type"]
        event_data = msg["event"]["data"]
        if event_type == EVENT_STATE_CHANGED:
            entity_id = event_data["entity_id"]
            self._states[entity_id] = event_data["new_state"]
        await self.__async_signal_event(event_type, event_data)

    async def __async_receive_all_states(self, msg: dict):
        """Received all states."""
        for item in msg["result"]:
            entity_id = item["entity_id"]
            self._states[entity_id] = item
        if not self._initial_state_received:
            await self.__async_signal_event(EVENT_CONNECTED)
            self._initial_state_received = True

    async def __async_receive_area_registry(self, msg: dict):
        """Received area registry."""
        LOGGER.debug("Received area registry.")
        for item in msg["result"]:
            item_id = item["area_id"]
            self._area_registry[item_id] = item

    async def __async_receive_device_registry(self, msg: dict):
        """Received device registry."""
        LOGGER.debug("Received device registry.")
        for item in msg["result"]:
            item_id = item["id"]
            self._device_registry[item_id] = item

    async def __async_receive_entity_registry(self, msg: dict):
        """Received entity registry."""
        LOGGER.debug("Received entity registry.")
        for item in msg["result"]:
            item_id = item["entity_id"]
            self._entity_registry[item_id] = item

    async def __async_get_data(self, endpoint: str):
        """Get data from hass rest api."""
        if not self._http_session:
            LOGGER.warning("Not connected")
            return
        url = f"http://{self._host}/api/{endpoint}"
        if self._use_ssl:
            url = f"https://{self._host}/api/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.__get_token()}",
            "Content-Type": "application/json",
        }
        async with self._http_session.get(
            url, headers=headers, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_post_data(self, endpoint: str, data: dict):
        """Post data to hass rest api."""
        if not self._http_session:
            LOGGER.warning("Not connected")
            return
        url = f"http://{self._host}/api/{endpoint}"
        if self._use_ssl:
            url = f"https://{self._host}/api/{endpoint}"
        headers = {
            "Authorization": "Bearer %s" % self.__get_token(),
            "Content-Type": "application/json",
        }
        async with self._http_session.post(
            url, headers=headers, json=data, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_signal_event(self, event: str, event_details: Any = None):
        """Signal event to registered callbacks."""
        for cb_func, event_filter, entity_filter in self._event_listeners:
            if not (event_filter is None or event in event_filter):
                continue
            if event == EVENT_STATE_CHANGED:
                entity_id = event_details.get("entity_id")
                if not (
                    entity_filter is None or not entity_id or entity_id in entity_filter
                ):
                    continue
            # call callback
            check_target = cb_func
            while isinstance(check_target, functools.partial):
                check_target = check_target.func
                check_target.args = (event, event_details)
            if asyncio.iscoroutine(check_target):
                self._loop.create_task(check_target)
            elif asyncio.iscoroutinefunction(check_target):
                self._loop.create_task(check_target(event, event_details))
            else:
                self._loop.run_in_executor(None, cb_func, event, event_details)

    def __get_token(self) -> str:
        """Get auth token for Home Assistant."""
        if IS_SUPERVISOR:
            # On supervisor installs the token is provided by a environment variable
            return os.environ["HASSIO_TOKEN"]
        return self._token
