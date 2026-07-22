"""Tests for the HomeAssistantClient."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from hass_client.client import MAX_MESSAGE_SIZE, HomeAssistantClient
from hass_client.exceptions import ConnectionFailed, ConnectionFailedDueToLargeMessage


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
