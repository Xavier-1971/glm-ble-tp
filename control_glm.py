"""
Controle interactif du telemetre Bosch GLM 50 C en Bluetooth Low Energy.

Protocole "Bosch MT" officiel (voir bosch_mt.py + docs/). Pense a activer le
Bluetooth sur l'ecran du GLM avant de lancer ce script.

Commandes clavier une fois connecte :
  m  -> declenche une mesure a distance (sans toucher l'appareil)
  c  -> demarre la mesure en continu
  x  -> arrete la mesure en continu
  l  -> laser ON
  o  -> laser OFF
  b  -> buzzer ON (bip)
  n  -> buzzer OFF
  q  -> quitter
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

import bosch_mt as mt

ADDRESS = "b0:10:a0:a1:35:0d"


def on_notify(_char, data: bytearray):
    data = bytes(data)
    print(f"[NOTIFY] {data.hex(' ')}  (len={len(data)})")

    evt = mt.parse_exchange_data_container(data)
    if evt is not None:
        print(f"    -> event dev_mode={evt['dev_mode']} laser_on={evt['laser_on']} "
              f"result={evt['result']:.3f} comp1={evt['component1']:.3f} "
              f"comp2={evt['component2']:.3f} crc_ok={evt['crc_ok']}")
        return

    resp = mt.parse_direct_response(data)
    if resp is not None:
        print(f"    -> reponse directe status={resp['status']:#04x} ok={resp['ok']} "
              f"payload={resp['payload'].hex(' ')} crc_ok={resp['crc_ok']}")


async def ainput(prompt: str) -> str:
    return await asyncio.get_event_loop().run_in_executor(None, input, prompt)


async def main():
    print("Recherche du GLM (Bluetooth actif a l'ecran)...")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=15.0)
    if device is None:
        print("GLM introuvable. Reactive le Bluetooth sur son ecran et reessaie.")
        return

    async with BleakClient(device) as client:
        print(f"Connecte: {client.is_connected}")

        await client.start_notify(mt.CHAR_UUID, on_notify)

        print("Activation AutoSync (necessaire pour recevoir les mesures)...")
        await client.write_gatt_char(mt.CHAR_UUID, mt.frame_enable_autosync(), response=True)

        print(__doc__)
        try:
            while True:
                cmd = (await ainput("> ")).strip().lower()
                if cmd == "q":
                    break
                elif cmd == "m":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_remote_trigger_measure(), response=True)
                elif cmd == "c":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_measure(mode=mt.MEAS_MODE_CONTINUOUS), response=True)
                elif cmd == "x":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_measure(mode=mt.MEAS_MODE_STOP_CONTINUOUS), response=True)
                elif cmd == "l":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_laser_on(), response=True)
                elif cmd == "o":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_laser_off(), response=True)
                elif cmd == "b":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_buzzer_on(), response=True)
                elif cmd == "n":
                    await client.write_gatt_char(mt.CHAR_UUID, mt.frame_buzzer_off(), response=True)
                else:
                    print("Commande inconnue. m/c/x/l/o/b/n/q")
        except KeyboardInterrupt:
            pass

        await client.stop_notify(mt.CHAR_UUID)

    print("Deconnecte.")


if __name__ == "__main__":
    asyncio.run(main())
