"""
Home Assistant Client for python.

Simple wrapper for the Websocket API
provided by Home Assistant that allows for rapid development of apps
connected to Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pprint
from collections.abc import Callable
from ssl import SSLContext
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import (
    ClientSession,
    ClientWebSocketResponse,
    Fingerprint,
    TCPConnector,
    WSMsgType,
    client_exceptions,
)

from .const import MATCH_ALL
from .exceptions import (
    AuthenticationFailed,
    CannotConnect,
    ConnectionFailed,
    ConnectionFailedDueToLargeMessage,
    FailedCommand,
    InvalidMessage,
    NotConnected,
)
from .models import (
    Area,
    AuthCommandMessage,
    AuthRequiredMessage,
    AuthResultMessage,
    CallServiceResult,
    CommandResultData,
    Config,
    Device,
    Entity,
    EntityStateEvent,
    Event,
    Message,
    State,
)

if TYPE_CHECKING:
    from types import TracebackType

try:
    import orjson as json

    HAS_ORJSON = True
except ImportError:
    import json

    HAS_ORJSON = False

LOGGER = logging.getLogger(__package__)
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16MB

EventCallback = Callable[[Event], None]
EntityChangedCallback = Callable[[EntityStateEvent], None]
SubscriptionCallback = Callable[[Message], None]


class HomeAssistantClient:
    """Connection to HomeAssistant (over websockets)."""

    def __init__(
        self,
        websocket_url: str,
        token: str | None,
        aiohttp_session: ClientSession | None = None,
    ) -> None:
        """
        Initialize the connection to HomeAssistant.

        Parameters:
        - websocket_url: full url to the HomeAssistant websocket api or None for supervisor.
        - token: a long lived token or None when using supervisor.
        - aiohttp_session: optionally provide an existing aiohttp session.
        """
        self._websocket_url = websocket_url
        self._token = token
        self._subscriptions: dict[int, tuple[dict[str, Any], SubscriptionCallback]] = {}
        self._version = None
        self._last_msg_id = 1
        self._loop = asyncio.get_running_loop()
        self._http_session_provided = aiohttp_session is not None
        self._http_session = aiohttp_session
        self._client: ClientWebSocketResponse | None = None
        self._result_futures: dict[str, asyncio.Future] = {}
        self._shutdown_complete_event: asyncio.Event | None = None
        self._msg_id_lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        """Return if we're currently connected."""
        return self._client is not None and not self._client.closed

    @property
    def version(self) -> str:
        """Return version of connected Home Assistant instance."""
        return self._version

    async def subscribe_events(
        self, cb_func: Callable[[Event], None], event_type: str = MATCH_ALL
    ) -> Callable:
        """
        Subscribe to (all) HA events.

        Parameters:
            - cb_func: callback function or coroutine
            - event_type: Optionally only listen for these event types (defaults to all.)

        Returns: function to remove the listener.
        """

        def handle_message(message: Message):
            if asyncio.iscoroutinefunction(cb_func):
                self._loop.create_task(cb_func(message["event"]))
            else:
                self._loop.call_soon(cb_func, message["event"])

        return await self.subscribe(handle_message, "subscribe_events", event_type=event_type)

    async def subscribe_entities(
        self, cb_func: Callable[[EntityStateEvent], None], entity_ids: list[str]
    ) -> None:
        """
        Subscribe to state_changed events for specific entities only.

        Parameters:
            - cb_func: callback function or coroutine
            - entity_ids: A list of entity_ids to watch.

        Returns: function to remove the listener.

        NOTE: The returned events are a compressed version of the state for performance reasons.
        """

        def handle_message(message: Message):
            if asyncio.iscoroutinefunction(cb_func):
                self._loop.create_task(cb_func(message["event"]))
            else:
                self._loop.call_soon(cb_func, message["event"])

        return await self.subscribe(handle_message, "subscribe_entities", entity_ids=entity_ids)

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        target: dict[str, Any] | None = None,
    ) -> CallServiceResult:
        """
        Call service on Home Assistant.

        Parameters:
            - domain: Domain of the service to call (e.g. light, switch).
            - service: The service to call  (e.g. turn_on).
            - service_data: Optional dict with parameters (e.g. { brightness: 20 }).
            - target: Optional dict with target parameters (e.g. { device_id: "aabbccddeeffgg" }).
        """
        if not self.connected:
            msg = "Please call connect first."
            raise NotConnected(msg)
        params = {"domain": domain, "service": service}
        if service_data:
            params["service_data"] = service_data
        if target:
            params["target"] = target
        return await self.send_command("call_service", **params)

    async def get_states(self) -> list[State]:
        """Get dump of the current states within Home Assistant."""
        return await self.send_command("get_states")

    async def get_config(self) -> list[Config]:
        """Get dump of the current config in Home Assistant."""
        return await self.send_command("get_states")

    async def get_services(self) -> dict[str, dict[str, Any]]:
        """Get dump of the current services in Home Assistant."""
        return await self.send_command("get_services")

    async def get_area_registry(self) -> list[Area]:
        """Get Area Registry."""
        return await self.send_command("config/area_registry/list")

    async def get_device_registry(self) -> list[Device]:
        """Get Device Registry."""
        return await self.send_command("config/device_registry/list")

    async def get_entity_registry(self) -> list[Entity]:
        """Get Entity Registry."""
        return await self.send_command("config/entity_registry/list")

    async def get_entity_registry_entry(self, entity_id: str) -> Entity:
        """Get single entry from Entity Registry."""
        return await self.send_command("config/entity_registry/get", entity_id=entity_id)

    async def send_command(self, command: str, **kwargs: dict[str, Any]) -> CommandResultData:
        """Send a command to the HA websocket and return response."""
        future: asyncio.Future[CommandResultData] = self._loop.create_future()
        if "message_id" in kwargs:
            message_id = kwargs.pop("message_id")
        else:
            message_id = await self._get_message_id()
        message = {"id": message_id, "type": command, **kwargs}
        self._result_futures[message_id] = future
        await self._send_json_message(message)
        try:
            return await future
        finally:
            self._result_futures.pop(message_id)

    async def send_command_no_wait(
        self, command: str, **kwargs: dict[str, Any]
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Send a command to the HA websocket without awaiting the response."""
        message_id = await self._get_message_id()
        message = {"id": message_id, "type": command, **kwargs}
        asyncio.create_task(self._send_json_message(message))

    async def subscribe(
        self, cb_func: Callable[[Message], None], command: str, **kwargs: dict[str, Any]
    ) -> Callable:
        """
        Instantiate a subscription for the given command.

        Parameters:
            - cb_func: callback function or coroutine which will be called when a message comes in.
            - command: The command to issue to the server.
            - kwargs: Optionally provider any arguments.

        Returns: function to remove the listener.
        """
        message_base = {"command": command, **kwargs}
        sub = (message_base, cb_func)

        message_id = await self._get_message_id()
        await self.send_command(**message_base, message_id=message_id)
        self._subscriptions[message_id] = sub

        def remove_listener():
            self._subscriptions.pop(message_id)
            # try to unsubscribe
            if "subscribe" not in message_base["command"]:
                return
            unsub_command = message_base["command"].replace("subscribe", "unsubscribe")
            asyncio.create_task(self.send_command_no_wait(unsub_command, subscription=message_id))

        return remove_listener

    async def connect(self, ssl: SSLContext | bool | Fingerprint | None = True) -> None:
        """Connect to the websocket server."""
        if self.connected:
            # already connected
            return
        if not self._http_session_provided and self._http_session is None:
            self._http_session = ClientSession(
                loop=self._loop,
                connector=TCPConnector(enable_cleanup_closed=True),
            )
        ws_url = self._websocket_url or "ws://supervisor/core/websocket"
        ws_token = self._token or os.environ.get("HASSIO_TOKEN")
        LOGGER.debug("Connecting to Home Assistant Websocket API on %s", ws_url)
        try:
            self._client = await self._http_session.ws_connect(
                ws_url, heartbeat=55, max_msg_size=MAX_MESSAGE_SIZE, ssl=ssl
            )
            version_msg: AuthRequiredMessage = await self._client.receive_json()
            self._version = version_msg["ha_version"]
            # send authentication
            auth_command: AuthCommandMessage = {
                "type": "auth",
                "access_token": ws_token,
            }
            await self._client.send_json(auth_command)
            auth_result: AuthResultMessage = await self._client.receive_json()
            if auth_result["type"] != "auth_ok":
                await self._client.close()
                raise AuthenticationFailed(auth_result.get("message", "Authentication failed"))
        except (
            client_exceptions.WSServerHandshakeError,
            client_exceptions.ClientError,
        ) as err:
            raise CannotConnect(err) from err

        LOGGER.info(
            "Connected to Home Assistant %s (version %s)",
            self._websocket_url.split("://")[1].split("/")[0],
            self.version,
        )

    async def disconnect(self) -> None:
        """Disconnect the client."""
        if not self.connected:
            return
        LOGGER.debug("Closing client connection")
        self._shutdown_complete_event = asyncio.Event()
        await self._client.close()

        if not self._http_session_provided and self._http_session:
            await self._http_session.close()
            self._http_session = None
        await self._shutdown_complete_event.wait()

    async def start_listening(self) -> None:
        """Connect (if needed) and start listening to incoming messages from the server."""
        await self.connect()
        try:
            while not self._client.closed:
                msg = await self._client.receive()

                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
                    break

                if msg.type == WSMsgType.ERROR:
                    if msg.data.code == aiohttp.WSCloseCode.MESSAGE_TOO_BIG:
                        # in the edge case we run into this, the lib consumer could
                        # decide to increase the MAX_MESSAGE_SIZE constant but messages
                        # bigger than 16MB are really just to big for a websocket.
                        raise ConnectionFailedDueToLargeMessage
                    raise ConnectionFailed

                if msg.type != WSMsgType.TEXT:
                    msg = f"Received non-Text message: {msg.type}"
                    raise InvalidMessage(msg)

                try:
                    data = msg.json(loads=json.loads)
                except ValueError as err:
                    msg = "Received invalid JSON."
                    raise InvalidMessage(msg) from err

                if LOGGER.isEnabledFor(logging.DEBUG):
                    LOGGER.debug("Received message:\n%s\n", pprint.pformat(msg))

                self._handle_incoming_message(data)

        finally:
            LOGGER.debug("Listen completed. Cleaning up")
            # cancel all command-tasks awaiting a result
            for future in self._result_futures.values():
                future.cancel()

            if not self._client.closed:
                await self._client.close()

            if self._shutdown_complete_event:
                self._shutdown_complete_event.set()

    def _handle_incoming_message(self, msg: Message) -> None:
        """Handle incoming message."""
        # command result
        if msg["type"] == "result":
            future = self._result_futures.get(msg["id"])

            if future is None:
                LOGGER.debug("Received result for unknown message with ID: %s", msg["id"])
                return

            if msg["success"]:
                future.set_result(msg["result"])
                return

            future.set_exception(FailedCommand(msg["error"]["message"]))
            return

        # subscription callback
        if msg["id"] in self._subscriptions:
            handler = self._subscriptions[msg["id"]][1]
            if asyncio.iscoroutinefunction(handler):
                self._loop.create_task(handler(msg))
            else:
                self._loop.call_soon(handler, msg)
            return

        # unknown message received, log it
        LOGGER.debug("Received message with unknown type '%s': %s", msg["type"], msg)

    async def _send_json_message(self, message: dict[str, Any]) -> None:
        """Send a message.

        Raises NotConnected if client not connected.
        """
        if not self.connected:
            raise NotConnected

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("Publishing message:\n%s\n", pprint.pformat(message))

        assert self._client
        assert "id" in message

        if HAS_ORJSON:
            await self._client.send_str(json.dumps(message).decode())
        else:
            await self._client.send_json(message)

    async def __aenter__(self) -> HomeAssistantClient:
        """Connect to the websocket."""
        await self.connect()
        self._listener_task = asyncio.create_task(self.start_listening())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit context manager."""
        await self.disconnect()

    def __repr__(self) -> str:
        """Return the representation."""
        prefix = "" if self.connected else "not "
        return f"{type(self).__name__}(ws_server_url={self._websocket_url!r}, {prefix}connected)"

    async def _get_message_id(self) -> int:
        """Return a new message id."""
        async with self._msg_id_lock:
            self._last_msg_id = message_id = self._last_msg_id + 1
            return message_id
