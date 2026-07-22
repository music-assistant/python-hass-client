"""Exceptions for hass-client."""


class BaseHassClientError(Exception):
    """Base Hass Client exception."""


class TransportError(BaseHassClientError):
    """Exception raised to represent transport errors."""

    def __init__(self, message: str, error: Exception | None = None) -> None:
        """Initialize a transport error."""
        super().__init__(message)
        self.error = error


class CannotConnect(TransportError):
    """Exception raised when failed to connect the client."""

    def __init__(self, error: Exception) -> None:
        """Initialize a cannot connect error."""
        super().__init__(f"{error}", error)


class ConnectionFailed(TransportError):
    """Exception raised when an established connection fails."""

    def __init__(self, error: Exception | None = None, message: str | None = None) -> None:
        """Initialize a connection failed error."""
        if message is None:
            message = "Connection failed." if error is None else f"{error}"
        super().__init__(message, error)


class ConnectionFailedDueToLargeMessage(ConnectionFailed):
    """Exception raised when an established connection fails due to an oversize message."""

    def __init__(self, error: Exception | None = None, max_msg_size: int | None = None) -> None:
        """Initialize a connection failed due to an oversize message error."""
        size_info = f" ({max_msg_size} bytes)" if max_msg_size else ""
        message = (
            f"Connection closed: a websocket message exceeded the maximum message size{size_info}. "
        )
        super().__init__(error, message)
        self.max_msg_size = max_msg_size


class NotFoundError(BaseHassClientError):
    """Exception that is raised when an entity can't be found."""


class NotConnected(BaseHassClientError):
    """Exception raised when trying to handle unknown handler."""


class InvalidState(BaseHassClientError):
    """Exception raised when data gets in invalid state."""


class InvalidMessage(BaseHassClientError):
    """Exception raised when an invalid message is received."""


class AuthenticationFailed(BaseHassClientError):
    """Exception raised when authentication failed."""


class FailedCommand(BaseHassClientError):
    """When a command has failed."""
