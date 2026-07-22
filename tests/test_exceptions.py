"""Tests for hass-client exceptions."""

from hass_client.exceptions import (
    ConnectionFailed,
    ConnectionFailedDueToLargeMessage,
    TransportError,
)


def test_connection_failed_without_error() -> None:
    """Test ConnectionFailed falls back to the generic message."""
    exc = ConnectionFailed()
    assert str(exc) == "Connection failed."
    assert exc.error is None


def test_connection_failed_with_error() -> None:
    """Test ConnectionFailed includes the underlying error."""
    err = ValueError("something went wrong")
    exc = ConnectionFailed(err)
    assert str(exc) == "something went wrong"
    assert exc.error is err


def test_connection_failed_due_to_large_message_default() -> None:
    """Test ConnectionFailedDueToLargeMessage has a distinct message."""
    exc = ConnectionFailedDueToLargeMessage()
    assert "maximum message size" in str(exc)
    assert str(exc) != "Connection failed."
    assert exc.error is None
    assert exc.max_msg_size is None
    # backward compatibility: still a ConnectionFailed/TransportError
    assert isinstance(exc, ConnectionFailed)
    assert isinstance(exc, TransportError)


def test_connection_failed_due_to_large_message_with_details() -> None:
    """Test ConnectionFailedDueToLargeMessage includes the configured limit and error."""
    err = ValueError("Received message size 17000000 exceeds limit 16777216")
    exc = ConnectionFailedDueToLargeMessage(err, 16 * 1024 * 1024)
    assert "(16777216 bytes)" in str(exc)
    assert "Increase max_msg_size" in str(exc)
    assert exc.error is err
    assert exc.max_msg_size == 16 * 1024 * 1024
