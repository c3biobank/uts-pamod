"""UTSSensor — high-level async API for the UTS optical sensor."""

from __future__ import annotations

import struct
from typing import List, Optional

from ._exceptions import (
    UTSConnectionError,
    UTSProtocolError,
    UTSTimeoutError,
    UTSValueError,
)
from ._protocol import ProtoFrame, ProtoFlags, ProtoType
from ._transport import UTSTransport

_DAC_MAX = 4095
_OD_COUNT = 11
_OJIP_SAMPLES = 4096
_PAM_SAMPLES = 1024
_CHUNK_BYTES = 256  # one binary DATA frame = 128 uint16 samples


class UTSSensor:
    """Async context manager for the UTSPAM photosynthesis sensor.

    Usage::

        async with UTSSensor() as sensor:          # auto-discovers port
            print(await sensor.get_id())
            od = await sensor.measure_od()

        # or with explicit port:
        async with UTSSensor(port="/dev/ttyACM0") as sensor:
            ...
    """

    def __init__(
        self,
        port: Optional[str] = None,
        transport: Optional[UTSTransport] = None,
    ) -> None:
        self._port = port
        self._transport: UTSTransport = transport or UTSTransport()

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "UTSSensor":
        await self.open()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    # ── Connection ────────────────────────────────────────────────────────────

    async def open(self) -> None:
        """Discover device (if port not given) and connect."""
        if self._port is None:
            ports = await self._transport.discover()
            if not ports:
                raise UTSConnectionError("No serial ports found")
            self._port = ports[0]
        await self._transport.connect(self._port)

    async def close(self) -> None:
        """Disconnect from device."""
        await self._transport.disconnect()

    # ── Device info ───────────────────────────────────────────────────────────

    async def get_id(self, timeout: float = 5.0) -> str:
        """Return device ID string (e.g. 'UTSPAM1')."""
        await self._send_cmd(b"i")
        text = await self._recv_text(timeout=timeout)
        if text.startswith("ID:"):
            return text[3:].strip()
        raise UTSProtocolError(f"Unexpected response to 'i': {text!r}")

    async def get_version(self, timeout: float = 5.0) -> str:
        """Return firmware version string (e.g. '1.0')."""
        await self._send_cmd(b"v")
        text = await self._recv_text(timeout=timeout)
        if text.startswith("VER:"):
            return text[4:].strip()
        raise UTSProtocolError(f"Unexpected response to 'v': {text!r}")

    # ── LED control ───────────────────────────────────────────────────────────

    async def set_measuring_led(self, value: int, timeout: float = 5.0) -> None:
        """Set measuring LED (MCP4822 ch-A) intensity 0–4095."""
        self._check_dac(value)
        await self._send_cmd(f"m{value:04d}".encode())
        text = await self._recv_text(timeout=timeout)
        if not text.startswith("OK:m"):
            raise UTSProtocolError(f"Unexpected response: {text!r}")

    async def set_saturation_led(self, value: int, timeout: float = 5.0) -> None:
        """Set saturation LED (MCP4822 ch-B) intensity 0–4095."""
        self._check_dac(value)
        await self._send_cmd(f"s{value:04d}".encode())
        text = await self._recv_text(timeout=timeout)
        if not text.startswith("OK:s"):
            raise UTSProtocolError(f"Unexpected response: {text!r}")

    async def set_reference_led(self, value: int, timeout: float = 5.0) -> None:
        """Set reference LED (DAC ch1) intensity 0–4095."""
        self._check_dac(value)
        await self._send_cmd(f"r{value:04d}".encode())
        text = await self._recv_text(timeout=timeout)
        if not text.startswith("OK:r"):
            raise UTSProtocolError(f"Unexpected response: {text!r}")

    async def led_on(self, led: int, timeout: float = 5.0) -> None:
        """Turn LED on. led: 0=measuring, 1=saturation, 2=reference."""
        self._check_led_index(led)
        await self._send_cmd(f"b{led}".encode())
        text = await self._recv_text(timeout=timeout)
        if not text.startswith(f"OK:b{led}"):
            raise UTSProtocolError(f"Unexpected response: {text!r}")

    async def led_off(self, led: int, timeout: float = 5.0) -> None:
        """Turn LED off. led: 0=measuring, 1=saturation, 2=reference."""
        self._check_led_index(led)
        await self._send_cmd(f"t{led}".encode())
        text = await self._recv_text(timeout=timeout)
        if not text.startswith(f"OK:t{led}"):
            raise UTSProtocolError(f"Unexpected response: {text!r}")

    async def get_measuring_led(self, timeout: float = 5.0) -> int:
        """Return current measuring LED value (m_value), 0–4095."""
        return await self._get_led_value(b"f0", "F0:", timeout)

    async def get_saturation_led(self, timeout: float = 5.0) -> int:
        """Return current saturation LED value (s_value), 0–4095."""
        return await self._get_led_value(b"f1", "F1:", timeout)

    async def get_reference_led(self, timeout: float = 5.0) -> int:
        """Return current reference LED value (r_value), 0–4095."""
        return await self._get_led_value(b"f2", "F2:", timeout)

    async def _get_led_value(
        self, cmd: bytes, prefix: str, timeout: float
    ) -> int:
        await self._send_cmd(cmd)
        text = (await self._recv_text(timeout=timeout)).strip()
        if not text.startswith(prefix):
            raise UTSProtocolError(f"Unexpected response to {cmd!r}: {text!r}")
        try:
            return int(text[len(prefix):])
        except ValueError:
            raise UTSProtocolError(f"Bad LED value: {text!r}")

    # ── Measurements ─────────────────────────────────────────────────────────

    async def read_adc(self, timeout: float = 5.0) -> int:
        """Return a direct ADC read of the photodiode signal."""
        await self._send_cmd(b"d")
        text = (await self._recv_text(timeout=timeout)).strip()
        if not text.startswith("D:"):
            raise UTSProtocolError(f"Unexpected response to 'd': {text!r}")
        try:
            return int(text[2:])
        except ValueError:
            raise UTSProtocolError(f"Bad ADC value: {text!r}")
    
    async def measure_od(self, timeout: float = 15.0) -> List[int]:
        """Run OD measurement. Returns 11 ADC readings."""
        await self._send_cmd(b"o")
        readings: List[int] = []
        while True:
            text = (await self._recv_text(timeout=timeout)).strip()
            if text == "OD:start":
                continue
            if text.startswith("OD:"):
                try:
                    readings.append(int(text[3:]))
                except ValueError:
                    raise UTSProtocolError(f"Bad OD value: {text!r}")
            elif text.startswith("OK:o"):
                break
            elif text.startswith("ERR:"):
                raise UTSProtocolError(text)
        return readings

    async def measure_ojip(self, timeout: float = 5.0) -> List[int]:
        """Run OJIP measurement. Returns 4096 ADC samples."""
        return await self._collect_binary_measurement(
            cmd=b"j",
            start_prefix="OJIP:START:",
            ok_prefix="OK:j",
            samples=_OJIP_SAMPLES,
            timeout=timeout,
        )

    async def measure_pam(self, timeout: float = 5.0) -> List[int]:
        """Run PAM measurement. Returns 1024 ADC samples."""
        return await self._collect_binary_measurement(
            cmd=b"p",
            start_prefix="PAM:START:",
            ok_prefix="OK:p",
            samples=_PAM_SAMPLES,
            timeout=timeout,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _send_cmd(self, payload: bytes) -> None:
        await self._transport.send(
            ProtoFrame(type=ProtoType.CMD, seq=0, flags=0, payload=payload)
        )

    async def _recv_text(self, timeout: float = 5.0) -> str:
        """Receive next DATA frame as text. Skips HB/ACK; raises on NACK."""
        while True:
            frame = await self._transport.recv(timeout=timeout)
            if frame.type == ProtoType.NACK:
                reason = frame.payload[1] if len(frame.payload) >= 2 else 0
                raise UTSProtocolError(f"NACK received (reason=0x{reason:02X})")
            if frame.type == ProtoType.DATA:
                return frame.payload.decode("ascii", errors="replace")

    async def _collect_binary_measurement(
        self,
        *,
        cmd: bytes,
        start_prefix: str,
        ok_prefix: str,
        samples: int,
        timeout: float,
    ) -> List[int]:
        await self._send_cmd(cmd)

        # Wait for START announcement
        while True:
            text = (await self._recv_text(timeout=timeout)).strip()
            if text.startswith(start_prefix):
                break
            if text.startswith("ERR:"):
                raise UTSProtocolError(text)

        # Collect exactly (samples*2 / _CHUNK_BYTES) binary DATA frames
        expected_bytes = samples * 2
        chunks = expected_bytes // _CHUNK_BYTES
        raw = bytearray()
        for _ in range(chunks):
            frame = await self._transport.recv(timeout=timeout)
            if frame.type == ProtoType.NACK:
                raise UTSProtocolError("NACK during binary transfer")
            if frame.type != ProtoType.DATA:
                raise UTSProtocolError(
                    f"Expected DATA frame, got {frame.type}"
                )
            raw.extend(frame.payload)

        if len(raw) != expected_bytes:
            raise UTSProtocolError(
                f"Expected {expected_bytes} bytes, got {len(raw)}"
            )

        # Wait for OK
        text = (await self._recv_text(timeout=timeout)).strip()
        if not text.startswith(ok_prefix):
            raise UTSProtocolError(f"Expected {ok_prefix!r}, got {text!r}")

        return list(struct.unpack_from(f"<{samples}H", raw))

    @staticmethod
    def _check_dac(value: int) -> None:
        if not 0 <= value <= _DAC_MAX:
            raise UTSValueError(f"DAC value must be 0–{_DAC_MAX}, got {value}")

    @staticmethod
    def _check_led_index(led: int) -> None:
        if led not in (0, 1, 2):
            raise UTSValueError(f"LED index must be 0, 1, or 2, got {led}")
