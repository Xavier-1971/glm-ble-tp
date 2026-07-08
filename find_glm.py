import asyncio
from bleak import BleakScanner

TARGET = "b0:10:a0:a1:35:0d"


async def main():
    print("Scan BLE (15s), rapproche-toi du GLM et vérifie que le Bluetooth reste actif...")
    result = await BleakScanner.discover(timeout=15.0, return_adv=True)

    if not result:
        print("Aucun appareil BLE détecté du tout.")
        return

    for address, (device, adv) in result.items():
        marker = "  <-- adresse GLM connue" if address.lower() == TARGET.lower() else ""
        print(f"{address}  name={adv.local_name!r}  rssi={adv.rssi}{marker}")
        if adv.manufacturer_data:
            for company_id, data in adv.manufacturer_data.items():
                print(f"    manufacturer_data: id=0x{company_id:04x} data={data.hex(' ')}")
        if adv.service_uuids:
            print(f"    service_uuids: {adv.service_uuids}")


if __name__ == "__main__":
    asyncio.run(main())
