# uts-pamod

Async Python API for the **UTSPAMx** optical sensor — a photosynthesis measurement system that performs OD, OJIP, and PAM fluorescence measurements.

Compatible with **Ubuntu Linux** and **Raspberry Pi 3/4/5**.

## Installation

1. cd to your working directory
2. run bash

```bash
git clone https://github.com/c3biobank/uts-pamod.git
cd uts-pamod
pip install .            # or: pip install -e .  for editable/dev
```

## Quick start

```python
import asyncio
from uts_pamod import UTSSensor

async def main():
    async with UTSSensor() as sensor:          # auto-discovers USB/UART port
        print("ID :", await sensor.get_id())
        print("FW :", await sensor.get_version())

        # Configure LEDs (0–4095)
        await sensor.set_measuring_led(500)
        await sensor.set_saturation_led(2048)
        await sensor.set_reference_led(2200)

        # Read back current LED settings (0–4095)
        print("meas LED:", await sensor.get_measuring_led())
        print("sat  LED:", await sensor.get_saturation_led())
        print("ref  LED:", await sensor.get_reference_led())

        # Single direct photodiode read (raw 16-bit count)
        print("ADC:", await sensor.read_adc())

        # Run measurements
        od = await sensor.measure_od()         # 11 readings, ~10 s
        print("OD :", od)

        ojip = await sensor.measure_ojip()     # 4096 samples, ~1 s
        print("OJIP samples:", len(ojip))

        pam = await sensor.measure_pam()       # 1024 × 1 ms + 20 µs pulse
        print("PAM samples:", len(pam))

asyncio.run(main())
```

## API reference

| Method | Description |
|---|---|
| `get_id()` | Device ID string |
| `get_version()` | Firmware version string |
| `read_adc()` | Single direct photodiode read, raw 16-bit count |
| `set_measuring_led(v)` | Measuring LED intensity, 0–4095 |
| `set_saturation_led(v)` | Saturation LED intensity, 0–4095 |
| `set_reference_led(v)` | Reference LED intensity, 0–4095 |
| `led_on(n)` / `led_off(n)` | LED on/off, n=0/1/2 |
| `get_measuring_led()` | Current measuring LED value, 0–4095 |
| `get_saturation_led()` | Current saturation LED value, 0–4095 |
| `get_reference_led()` | Current reference LED value, 0–4095 |
| `measure_od()` | Returns `list[int]` of 11 ADC readings, discard the first value |
| `measure_ojip()` | Returns `list[int]` of 4096 ADC samples |
| `measure_pam()` | Returns `list[int]` of 1024 ADC samples |

All values are raw 16-bit ADC counts (uint16, 0–65535).
LED index `n`: 0=measuring, 1=saturation, 2=reference.

**To skip auto-discovery, pass an explicit port:**

```python
async with UTSSensor(port="/dev/ttyACM0") as sensor:
    ...
```

## Errors

All exceptions derive from `UTSError`:

| Exception | Raised when |
|---|---|
| `UTSConnectionError` | No port found / connect fails |
| `UTSTimeoutError` | Device gave no response in time |
| `UTSProtocolError` | Unexpected or malformed response |
| `UTSValueError` | Argument out of range (e.g. LED > 4095) |

## Hardware

- **MCU**: STM32F072RB (Nucleo-F072RB)
- **Connection**: USB-CDC (`/dev/ttyACM0`) or UART (`/dev/ttyS0`) at 115200 8N1

## License

MIT — see [LICENSE](LICENSE).
