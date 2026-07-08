import asyncio
from bleak import BleakClient

ADDRESS = "b0:10:a0:a1:35:0d"  # Bosch GLM 50-27 CG


def notify_handler(characteristic, data: bytearray):
    print(f"[NOTIFY] {characteristic.uuid}: {data.hex(' ')}  (len={len(data)})")


async def main():
    print(f"Connexion à {ADDRESS} ...")
    async with BleakClient(ADDRESS) as client:
        print(f"Connecté: {client.is_connected}\n")

        notify_uuids = []

        for service in client.services:
            print(f"[Service] {service.uuid}  ({service.description})")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  [Char] {char.uuid}  props=({props})  handle={char.handle}")
                for desc in char.descriptors:
                    print(f"    [Desc] {desc.uuid}  handle={desc.handle}")

                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        print(f"    -> lecture: {value.hex(' ')}")
                    except Exception as e:
                        print(f"    -> lecture impossible: {e}")

                if "notify" in char.properties or "indicate" in char.properties:
                    notify_uuids.append(char.uuid)
            print()

        if notify_uuids:
            print("Abonnement aux caractéristiques notify/indicate...")
            for uuid in notify_uuids:
                await client.start_notify(uuid, notify_handler)

            print("En écoute 20s : appuie sur le bouton mesure du GLM maintenant.\n")
            await asyncio.sleep(20)

            for uuid in notify_uuids:
                await client.stop_notify(uuid)

    print("Déconnecté.")


if __name__ == "__main__":
    asyncio.run(main())
