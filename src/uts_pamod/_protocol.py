from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import List, Optional

PROTO_SOF0 = 0xA5
PROTO_SOF1 = 0x5A
PROTO_VERSION = 0x01
PROTO_MAX_PAYLOAD = 256


class ProtoType(IntEnum):
    HEARTBEAT = 0x01
    DATA = 0x02
    CMD = 0x03
    ACK = 0x04
    NACK = 0x05


class ProtoFlags(IntFlag):
    NONE = 0
    ACK_REQ = 1 << 0
    IS_ACK = 1 << 1
    IS_NACK = 1 << 2


@dataclass
class ProtoFrame:
    type: ProtoType
    seq: int
    flags: int
    payload: bytes = field(default=b"")


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, no reflection."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode_frame(
    ftype: ProtoType,
    payload: bytes,
    seq: int,
    flags: int = 0,
) -> bytes:
    """Encode a protocol frame to wire bytes."""
    length = len(payload)
    # Bytes covered by CRC: VER TYPE SEQ LEN_L LEN_H FLAGS PAYLOAD
    crc_data = (
        bytes([
            PROTO_VERSION,
            int(ftype),
            seq & 0xFF,
            length & 0xFF,
            (length >> 8) & 0xFF,
            flags & 0xFF,
        ])
        + payload
    )
    crc = crc16_ccitt(crc_data)
    return (
        bytes([PROTO_SOF0, PROTO_SOF1])
        + crc_data
        + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    )


class FrameParser:
    """Stateful stream parser that extracts ProtoFrames from a byte stream."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[ProtoFrame]:
        """Feed bytes; return any complete frames decoded."""
        self._buf += data
        frames: List[ProtoFrame] = []

        while True:
            idx = self._find_sof()
            if idx is None:
                # Keep last byte — it might be the start of an upcoming SOF pair
                self._buf = self._buf[-1:] if self._buf else bytearray()
                break

            if idx > 0:
                self._buf = self._buf[idx:]

            # Minimum frame: SOF(2) + 6 header bytes + 2 CRC = 10 bytes
            if len(self._buf) < 10:
                break

            length = self._buf[5] | (self._buf[6] << 8)
            total = 10 + length
            if len(self._buf) < total:
                break

            frame_bytes = self._buf[:total]
            # CRC covers wire bytes [2 .. 8+length-1]: VER…FLAGS…PAYLOAD
            crc_data = bytes(frame_bytes[2 : 8 + length])
            crc_calc = crc16_ccitt(crc_data)
            crc_recv = frame_bytes[8 + length] | (frame_bytes[8 + length + 1] << 8)

            if crc_recv != crc_calc:
                # Skip SOF0 and resync
                self._buf = self._buf[1:]
                continue

            try:
                ftype = ProtoType(frame_bytes[3])
            except ValueError:
                self._buf = self._buf[total:]
                continue

            frames.append(
                ProtoFrame(
                    type=ftype,
                    seq=frame_bytes[4],
                    flags=frame_bytes[7],
                    payload=bytes(frame_bytes[8 : 8 + length]),
                )
            )
            self._buf = self._buf[total:]

        return frames

    def _find_sof(self) -> Optional[int]:
        for i in range(len(self._buf) - 1):
            if self._buf[i] == PROTO_SOF0 and self._buf[i + 1] == PROTO_SOF1:
                return i
        return None
