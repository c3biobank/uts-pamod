class UTSError(Exception):
    """Base exception for all uts_pamod errors."""

class UTSConnectionError(UTSError):
    """Raised when device connection fails."""

class UTSTimeoutError(UTSError):
    """Raised when a read or operation times out."""

class UTSProtocolError(UTSError):
    """Raised on protocol-level errors (bad CRC, NACK, unexpected response)."""

class UTSValueError(UTSError, ValueError):
    """Raised when a user-supplied argument is out of range."""
