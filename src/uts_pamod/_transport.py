"""Async serial transport for the UTSPAMx device."""

from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

from ._exceptions import UTSConnectionError, UTSTimeoutError
from ._protocol import FrameParser, ProtoFrame, ProtoType, encode_frame

_BAUD = 115200
_READY_MARKER = b"OPTICS-UTS:READY"
_CLAIM_BYTE = b"\x00"
_HB_INTERVAL = 0.5  # seconds
# USB CDC / ST-Link UART needs ~1s after port open for the STM32 HAL_UART_Receive_IT
# to re-arm after the bridge reconfigures.  Without this, the first CMD is lost.
_PORT_SETTLE_S = 1.0


class UTSTransport:
    """Low-level async transport: discover, connect, send, recv."""

    def __init__(self) -> None:
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer = None  # asyncio.StreamWriter (or duck-typed mock)
        self._rx_queue: asyncio.Queue[ProtoFrame] = asyncio.Queue()
        self._tx_seq: int = 0
        self._reader_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def discover(self) -> List[str]:
        """Return names of serial ports with real hardware (excludes phantom ttyS)."""
        import serial.tools.list_ports  # type: ignore[import]
        return [
            p.device
            for p in serial.tools.list_ports.comports()
            if p.hwid != "n/a"
        ]

    async def connect(
        self,
        port: str,
        timeout: float = 10.0,
        _streams: Optional[Tuple] = None,
    ) -> None:
        """Open *port*, wait for READY broadcast, claim channel, start tasks.

        *_streams*: inject (reader, writer) for unit tests.
        """
        if _streams is not None:
            self._reader, self._writer = _streams
        else:
            import serial_asyncio
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=port, baudrate=_BAUD
            )
            # USB CDC / ST-Link bridge reconfigures the UART on port open.
            # Wait for the STM32 HAL_UART_Receive_IT to re-arm before sending.
            await asyncio.sleep(_PORT_SETTLE_S)

        ready = await self._wait_for_ready(timeout)
        if ready:
            # Within discovery window — send claim byte
            self._writer.write(_CLAIM_BYTE)
            await self._writer.drain()
        # else: device already past discovery window, in normal mode — proceed

        self._reader_task = asyncio.create_task(self._reader_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """Cancel background tasks and close the serial port."""
        for task in (self._reader_task, self._heartbeat_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reader_task = None
        self._heartbeat_task = None

        if self._writer is not None:
            try:
                self._writer.close()
                if hasattr(self._writer, "wait_closed"):
                    await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    async def send(self, frame: ProtoFrame) -> None:
        """Encode and transmit a frame."""
        if self._writer is None:
            raise UTSConnectionError("Not connected")
        data = encode_frame(frame.type, frame.payload, self._tx_seq, frame.flags)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        self._writer.write(data)
        await self._writer.drain()

    async def recv(self, timeout: float = 5.0) -> ProtoFrame:
        """Return the next received frame, or raise UTSTimeoutError."""
        try:
            return await asyncio.wait_for(self._rx_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise UTSTimeoutError("No frame received within timeout")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _wait_for_ready(self, timeout: float) -> bool:
        """Wait for READY broadcast. Returns True if claimed, False if already past window."""
        buf = bytearray()

        async def _inner() -> None:
            assert self._reader is not None
            while True:
                chunk = await self._reader.read(64)
                if not chunk:  # EOF — break so wait_for can return
                    return
                buf.extend(chunk)
                if _READY_MARKER in buf:
                    return

        try:
            await asyncio.wait_for(_inner(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        return _READY_MARKER in buf

    async def _reader_loop(self) -> None:
        assert self._reader is not None
        parser = FrameParser()
        try:
            while True:
                data = await self._reader.read(512)
                if not data:
                    break
                for frame in parser.feed(data):
                    await self._rx_queue.put(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_HB_INTERVAL)
                hb = encode_frame(ProtoType.HEARTBEAT, b"", self._tx_seq)
                self._tx_seq = (self._tx_seq + 1) & 0xFF
                if self._writer is not None:
                    self._writer.write(hb)
                    await self._writer.drain()
        except asyncio.CancelledError:
            raise
