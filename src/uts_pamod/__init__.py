"""uts_pamod — async Python API for the UTSPAM1 optical sensor."""

from ._exceptions import (
    UTSConnectionError,
    UTSError,
    UTSProtocolError,
    UTSTimeoutError,
    UTSValueError,
)
from ._protocol import ProtoFlags, ProtoFrame, ProtoType
from .main import UTSSensor

__all__ = [
    "UTSSensor",
    "UTSError",
    "UTSConnectionError",
    "UTSTimeoutError",
    "UTSProtocolError",
    "UTSValueError",
    "ProtoType",
    "ProtoFlags",
    "ProtoFrame",
]
