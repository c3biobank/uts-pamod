import asyncio
from uts_pamod import UTSSensor

async def main():
    async with UTSSensor() as sensor:          # auto-discovers USB/UART port
        print("ID :", await sensor.get_id())
        print("FW :", await sensor.get_version())

        # Configure LEDs (0–4095)
        await sensor.set_measuring_led(100)
        await sensor.set_saturation_led(2800)
        await sensor.set_reference_led(2200)

        # Run measurements
        od = await sensor.measure_od()         # 10 readings, ~10 s
        print("OD :", od)

        ojip = await sensor.measure_ojip()     # 1024 × 1 ms samples
        print("OJIP samples:", len(ojip))

        pam = await sensor.measure_pam()       # 1024 × 1 ms + 20 µs pulse
        print("PAM samples:", len(pam))

asyncio.run(main())
