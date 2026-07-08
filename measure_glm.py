import asyncio
import struct
from bleak import BleakClient, BleakScanner

ADDRESS = "b0:10:a0:a1:35:0d"

CHAR_D1 = "02a6c0d1-0451-4000-b000-fb3210111989"  # indicate/write - commande + mesures

ENABLE_STREAM = bytes([0xC0, 0x55, 0x02, 0x01, 0x00, 0x1A])


def parse_frame(uuid, data: bytearray):
    print(f"[NOTIFY] {uuid}: {data.hex(' ')}  (len={len(data)})")
    if len(data) >= 11 and data[0] == 0xC0 and data[1] == 0x55 and data[2] == 0x10 and data[3] == 0x06:
        (distance_m,) = struct.unpack_from("<f", data, 7)
        print(f"    -> MESURE: {distance_m:.3f} m")


async def main():
    print("Recherche du GLM (assure-toi que son Bluetooth est actif à l'écran)...")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=15.0)
    if device is None:
        print("GLM introuvable. Réactive le Bluetooth sur son écran et réessaie.")
        return

    async with BleakClient(device) as client:
        print(f"Connecté: {client.is_connected}")

        await client.start_notify(CHAR_D1, lambda c, d: parse_frame(c.uuid, d))

        print("Activation du flux de mesure...")
        await client.write_gatt_char(CHAR_D1, ENABLE_STREAM, response=True)

        print("En écoute : appuie sur le bouton mesure du GLM (Ctrl+C pour arrêter).")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

        await client.stop_notify(CHAR_D1)

    print("Déconnecté.")


if __name__ == "__main__":
    asyncio.run(main())
