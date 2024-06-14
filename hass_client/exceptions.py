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

    def __init__(self, error: Exception | None = None) -> None:
        """Initialize a connection failed error."""
        if error is None:
            super().__init__("Connection failed.")
            return
        super().__init__(f"{error}", error)


class ConnectionFailedDueToLargeMessage(ConnectionFailed):
    """Exception raised when an established connection fails due to an oversize message."""


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
