"""
Determine the exact CRC-8 variant used by the Bosch MT connectivity protocol.

The official doc (MT_connectivity_protocol_1_2_9.pdf, section 3.1.4) states:
    CRC8 polynomial: x^8 + x^6 + x^3 + x^2 + 1 = 0xA6
    CRC8 initial value: 0xAA
    "All checksum formats are calculated from all message bytes from Mode to
     Data N respectively Command."

It does NOT state bit order (reflected in/out) or XOR-out value, so we brute
force those against known-good (message, checksum) pairs taken verbatim from
the official command examples table (MT_connectivity_protocol_LRF_command_set_2_5_0.pdf,
section 6) plus the frame the TP has already captured working live.
"""

from itertools import product

KNOWN = [
    (bytes([0xC0, 0x45, 0x00]), 0xD0),  # Buzzer on
    (bytes([0xC0, 0x46, 0x00]), 0x58),  # Buzzer off
    (bytes([0xC0, 0x00, 0x00]), 0xFC),  # Get communication info
    (bytes([0xC0, 0x05, 0x00]), 0xC2),  # Get device name
    (bytes([0xC0, 0x06, 0x00]), 0x4A),  # Get device info
    (bytes([0xC0, 0x40, 0x01, 0x00]), 0xFA),  # Single distance meas, front edge (cmd 64 dec = 0x40)
    (bytes([0xC0, 0x41, 0x00]), 0x96),  # Laser on (cmd 65 dec = 0x41)
    (bytes([0xC0, 0x42, 0x00]), 0x1E),  # Laser off (cmd 66 dec = 0x42)
    (bytes([0xC0, 0x4B, 0x00]), 0xEA),  # Get battery pack SOC (cmd 75 dec = 0x4B)
    (bytes([0xC0, 0x0D, 0x00]), 0x4E),  # Get HW error code (cmd 13 dec = 0x0D)
    (bytes([0xC0, 0x55, 0x02, 0x01, 0x00]), 0x1A),  # Set AutoSyncEnable (our known-working frame)
    (bytes([0xC0, 0x55, 0x02, 0x00, 0x00]), 0x62),  # Set AutoSyncDisable
    (bytes([0xC0, 0x5E, 0x02, 0x01, 0x00]), 0x5C),  # Set GIS AutoSyncEnable
    (bytes([0xC0, 0x3E, 0x02, 0x77, 0x88]), 0xFE),  # Echo 2 bytes
]

POLY = 0xA6
INIT = 0xAA


def reflect(byte, width):
    r = 0
    for _ in range(width):
        r = (r << 1) | (byte & 1)
        byte >>= 1
    return r


def crc8(data: bytes, poly: int, init: int, refin: bool, refout: bool, xorout: int) -> int:
    crc = init
    for b in data:
        if refin:
            b = reflect(b, 8)
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    if refout:
        crc = reflect(crc, 8)
    return crc ^ xorout


def main():
    found = []
    for refin, refout, xorout in product([False, True], [False, True], range(256)):
        if all(crc8(msg, POLY, INIT, refin, refout, xorout) == exp for msg, exp in KNOWN):
            found.append((refin, refout, xorout))

    if not found:
        print("Aucune combinaison refin/refout/xorout ne colle avec poly=0xA6 init=0xAA.")
        return

    print(f"{len(found)} combinaison(s) valide(s) trouvee(s) parmi {len(KNOWN)} trames connues:\n")
    for refin, refout, xorout in found:
        print(f"  poly=0x{POLY:02X} init=0x{INIT:02X} refin={refin} refout={refout} xorout=0x{xorout:02X}")


if __name__ == "__main__":
    main()
