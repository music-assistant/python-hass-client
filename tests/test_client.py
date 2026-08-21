"""Tests for the HomeAssistantClient."""

import asyncio
import json
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from hass_client.client import MAX_MESSAGE_SIZE, HomeAssistantClient
from hass_client.exceptions import (
    ConnectionFailed,
    ConnectionFailedDueToLargeMessage,
    FailedCommand,
    NotConnected,
)


class _FakeReader:
    """Websocket reader that hands out buffered frames without suspending."""

    def __init__(self) -> None:
        """Initialize an empty reader."""
        self._buffer: deque[aiohttp.WSMessage] = deque()
        self._waiter: asyncio.Future[None] | None = None

    def feed(self, message: dict[str, Any]) -> None:
        """Buffer a text frame and wake up a pending read."""
        self._buffer.append(aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(message), None))
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(None)

    async def read(self) -> aiohttp.WSMessage:
        """Return the next frame, awaiting only when the buffer ran empty."""
        if not self._buffer:
            self._waiter = asyncio.get_running_loop().create_future()
            await self._waiter
        return self._buffer.popleft()


def _mocked_session() -> MagicMock:
    """Return a mocked aiohttp ClientSession with a successful auth flow."""
    ws_client = MagicMock()
    ws_client.receive_json = AsyncMock(
        side_effect=[
            {"type": "auth_required", "ha_version": "2026.1.0"},
            {"type": "auth_ok", "ha_version": "2026.1.0"},
        ]
    )
    ws_client.send_json = AsyncMock()
    ws_client.closed = False
    session = MagicMock(spec=aiohttp.ClientSession)
    session.ws_connect = AsyncMock(return_value=ws_client)
    return session


def _mocked_session_with_reader(reader: _FakeReader) -> MagicMock:
    """Return a mocked aiohttp ClientSession which reads its frames from the given reader."""
    session = _mocked_session()
    ws_client = session.ws_connect.return_value
    ws_client.receive = reader.read
    ws_client.close = AsyncMock()
    return session


async def test_default_max_msg_size_passed_to_ws_connect() -> None:
    """Test the default message size limit is passed to ws_connect."""
    session = _mocked_session()
    client = HomeAssistantClient("ws://test/api/websocket", "token", session)
    await client.connect()
    session.ws_connect.assert_called_once_with(
        "ws://test/api/websocket", heartbeat=55, max_msg_size=MAX_MESSAGE_SIZE, ssl=True
    )
    assert MAX_MESSAGE_SIZE == 16 * 1024 * 1024


async def test_custom_max_msg_size_passed_to_ws_connect() -> None:
    """Test a custom message size limit is passed to ws_connect."""
    session = _mocked_session()
    client = HomeAssistantClient("ws://test/api/websocket", "token", session, max_msg_size=0)
    await client.connect()
    session.ws_connect.assert_called_once_with(
        "ws://test/api/websocket", heartbeat=55, max_msg_size=0, ssl=True
    )


async def test_error_frame_raises_connection_failed_with_error() -> None:
    """Test an ERROR frame surfaces the underlying aiohttp error."""
    session = _mocked_session()
    ws_client = session.ws_connect.return_value
    error = aiohttp.WebSocketError(aiohttp.WSCloseCode.PROTOCOL_ERROR, "protocol error")
    ws_client.receive = AsyncMock(
        return_value=aiohttp.WSMessage(aiohttp.WSMsgType.ERROR, error, None)
    )
    ws_client.close = AsyncMock()
    client = HomeAssistantClient("ws://test/api/websocket", "token", session)
    with pytest.raises(ConnectionFailed) as exc_info:
        await client.start_listening()
    assert exc_info.value.error is error
    assert "protocol error" in str(exc_info.value)


async def test_message_too_big_raises_distinct_error() -> None:
    """Test a MESSAGE_TOO_BIG ERROR frame raises ConnectionFailedDueToLargeMessage."""
    session = _mocked_session()
    ws_client = session.ws_connect.return_value
    error = aiohttp.WebSocketError(
        aiohttp.WSCloseCode.MESSAGE_TOO_BIG, "Received message size exceeds limit"
    )
    ws_client.receive = AsyncMock(
        return_value=aiohttp.WSMessage(aiohttp.WSMsgType.ERROR, error, None)
    )
    ws_client.close = AsyncMock()
    client = HomeAssistantClient("ws://test/api/websocket", "token", session, max_msg_size=1024)
    with pytest.raises(ConnectionFailedDueToLargeMessage) as exc_info:
        await client.start_listening()
    assert exc_info.value.error is error
    assert exc_info.value.max_msg_size == 1024
    assert "(1024 bytes)" in str(exc_info.value)


async def test_remove_listener_sends_unsubscribe_events() -> None:
    """Test the returned teardown callable always sends unsubscribe_events."""
    client = HomeAssistantClient("ws://test/api/websocket", "token")
    client.send_command = AsyncMock(return_value=None)
    client.send_command_no_wait = AsyncMock(return_value=None)

    remove_listener = await client.subscribe_entities(MagicMock(), ["light.test"])
    message_id = client.send_command.call_args.kwargs["message_id"]

    remove_listener()
    await asyncio.sleep(0)  # let the fire-and-forget unsubscribe task run

    client.send_command_no_wait.assert_called_once_with(
        "unsubscribe_events", subscription=message_id
    )


async def test_event_arriving_with_subscribe_result_is_delivered() -> None:
    """Test an event arriving in the same burst as the subscribe result reaches the callback."""
    reader = _FakeReader()
    session = _mocked_session_with_reader(reader)
    ws_client = session.ws_connect.return_value

    async def send_json(message: dict[str, Any]) -> None:
        if message["type"] != "subscribe_entities":
            return
        reader.feed({"id": message["id"], "type": "result", "success": True, "result": None})
        reader.feed(
            {"id": message["id"], "type": "event", "event": {"a": {"light.test": {"s": "on"}}}}
        )

    ws_client.send_json = AsyncMock(side_effect=send_json)
    client = HomeAssistantClient("ws://test/api/websocket", "token", session)
    listener = asyncio.create_task(client.start_listening())
    await asyncio.sleep(0)  # let the listener start reading

    messages: list[dict[str, Any]] = []
    await client.subscribe(messages.append, "subscribe_entities", entity_ids=["light.test"])
    await asyncio.sleep(0)  # let the scheduled subscription callback run

    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)

    assert len(messages) == 1
    assert messages[0]["event"] == {"a": {"light.test": {"s": "on"}}}


async def test_failed_subscribe_leaves_no_subscription() -> None:
    """Test a rejected subscribe command does not leave a subscription behind."""
    reader = _FakeReader()
    session = _mocked_session_with_reader(reader)
    ws_client = session.ws_connect.return_value

    async def send_json(message: dict[str, Any]) -> None:
        if message["type"] != "subscribe_entities":
            return
        reader.feed(
            {
                "id": message["id"],
                "type": "result",
                "success": False,
                "error": {"message": "unknown entity"},
            }
        )

    ws_client.send_json = AsyncMock(side_effect=send_json)
    client = HomeAssistantClient("ws://test/api/websocket", "token", session)
    listener = asyncio.create_task(client.start_listening())
    await asyncio.sleep(0)  # let the listener start reading

    with pytest.raises(FailedCommand):
        await client.subscribe(MagicMock(), "subscribe_entities", entity_ids=["light.test"])

    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)

    assert not client._subscriptions


async def test_cancelled_subscribe_leaves_no_subscription() -> None:
    """Test a subscribe cancelled while in flight does not leave a subscription behind."""
    reader = _FakeReader()
    session = _mocked_session_with_reader(reader)
    ws_client = session.ws_connect.return_value
    sent = asyncio.Event()

    async def send_json(message: dict[str, Any]) -> None:
        # the subscribe command is never answered, so the caller stays in flight
        if message["type"] == "subscribe_entities":
            sent.set()

    ws_client.send_json = AsyncMock(side_effect=send_json)
    client = HomeAssistantClient("ws://test/api/websocket", "token", session)
    listener = asyncio.create_task(client.start_listening())
    await asyncio.sleep(0)  # let the listener start reading

    subscribe = asyncio.create_task(
        client.subscribe(MagicMock(), "subscribe_entities", entity_ids=["light.test"])
    )
    await asyncio.wait_for(sent.wait(), 1)
    subscribe.cancel()

    with pytest.raises(asyncio.CancelledError):
        await subscribe

    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)

    assert not client._subscriptions


async def test_send_command_no_wait_raises_when_disconnected() -> None:
    """Test the fire-and-forget send surfaces a closed connection to its caller."""
    client = HomeAssistantClient("ws://test/api/websocket", "token")
    assert not client.connected
    with pytest.raises(NotConnected):
        await client.send_command_no_wait("unsubscribe_events", subscription=2)


async def test_remove_listener_on_dead_connection_does_not_leak_exception() -> None:
    """Test tearing down a subscription after the connection died stays silent."""
    unhandled: list[dict[str, Any]] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: unhandled.append(context)
    )
    client = HomeAssistantClient("ws://test/api/websocket", "token")
    client.send_command = AsyncMock(return_value=None)

    remove_listener = await client.subscribe_entities(MagicMock(), ["light.test"])
    assert not client.connected

    remove_listener()
    await asyncio.sleep(0)  # let the fire-and-forget unsubscribe task run
    await asyncio.sleep(0)  # and let its done-callback retrieve the exception

    assert not unhandled
