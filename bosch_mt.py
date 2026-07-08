"""
Bosch MT connectivity protocol (BLE) helpers for the Bosch GLM 50 C.

Source: official Bosch documentation
  - "Bosch MT connectivity protocol", issue 1.2.9 (general frame format, CRC-8)
  - "MT protocol LRF command set", issue 2.5.0 (laser-rangefinder-specific commands)
kept in ./docs/ in this repo (see docs/SOURCES.md for provenance) and summarised in
docs/commands_reference.md. Command bytes and the CRC-8 parameters below were verified
against the 14 worked examples in section 6 of the LRF doc plus frames captured live.

Frame format (LONG, the only one used here):
  Request:  [Mode=0xC0][Command][DataLen N][Data * N][CRC-8]
  Response: [Status][DataLen N][Data * N][CRC-8]
  Event (LRF acting as master, e.g. after a button press or remote trigger):
            [Mode=0xC0][Command][DataLen N][Data * N][CRC-8]  (same shape as a request)

CRC-8: poly x^8+x^6+x^3+x^2+1 (0xA6), init 0xAA, MSB-first, no reflection,
no final XOR. Computed over every byte from Mode/Status up to the last Data
byte (i.e. everything except the CRC byte itself).

Not implemented here: Get/Set user settings (cmd 83/84) — the doc marks these
GLM80-platform only, not available on the GLM 50 C (SPAD platform); measurement
list get/clear (cmd 81/82) — per-device availability in the doc is ambiguous and
the payload (repeated 33-byte Sync_Container_t) isn't worth the complexity yet.
"""
import struct

CHAR_UUID = "02a6c0d1-0451-4000-b000-fb3210111989"

MODE_REQUEST_LONG = 0xC0

# --- MT global commands (same on every Bosch MT device) ---
CMD_GET_COMM_INFO = 0x00
CMD_GET_DEVICE_NAME = 0x05
CMD_GET_DEVICE_INFO = 0x06
CMD_GET_RTC = 0x0F   # cmd 15 dec
CMD_SET_RTC = 0x10   # cmd 16 dec
CMD_DO_ECHO = 0x3E   # cmd 62 dec
CMD_DO_PING = 0x3F   # cmd 63 dec

# --- LRF-specific commands (decimal command number -> hex byte on the wire) ---
CMD_MEASURE = 0x40              # cmd 64 dec: single/continuous distance measurement
CMD_LASER_ON = 0x41             # cmd 65 dec
CMD_LASER_OFF = 0x42            # cmd 66 dec
CMD_BUZZER_ON = 0x45            # cmd 69 dec
CMD_BUZZER_OFF = 0x46           # cmd 70 dec
CMD_LCD_BACKLIGHT_ON = 0x47     # cmd 71 dec
CMD_LCD_BACKLIGHT_OFF = 0x48    # cmd 72 dec
CMD_GET_BATTERY_SOC = 0x4B      # cmd 75 dec
CMD_CHECK_LASER_ENABLE = 0x4C   # cmd 76 dec
CMD_GET_LASER_CLASS = 0x4D      # cmd 77 dec
CMD_GET_MEASUREMENT_INFO = 0x73  # cmd 115 dec
CMD_EXCHANGE_DATA = 0x55        # cmd 85 dec: Exchange data container (AutoSync/RemoteCtrl)
CMD_REMOTE_TRIGGER = 0x56       # cmd 86 dec: Do Remote Trigger Button

EN_BUTTON_MEASURE = 0x00

# CMD_MEASURE (0x40) Parameter byte
MEAS_REF_FRONT = 0 << 6
MEAS_REF_TRIPOD = 1 << 6
MEAS_REF_REAR = 2 << 6
MEAS_REF_PIN = 3 << 6
MEAS_MODE_SINGLE = 0b00
MEAS_MODE_CONTINUOUS = 0b01
MEAS_MODE_STOP_CONTINUOUS = 0b10

# CMD_EXCHANGE_DATA (0x55) DevModeSync byte, "LRF as slave" request
DEVMODESYNC_ENABLE_AUTOSYNC = 0b0000_0001  # bit0
DEVMODESYNC_KEYPAD_BYPASS = 0b0000_0010    # bit1
# Bit[7..2] = DevMode / RemoteCtrlCmd

# RemoteCtrlCmd 60 = SetDevAppMode: RemoteCtrlData = one of these DevMode values
DEVMODE_NO_ACTION = 0
DEVMODE_SINGLE_DISTANCE = 1
DEVMODE_CONTIN_DISTANCE = 2
DEVMODE_AREA_FINAL = 4
DEVMODE_VOLUME_FINAL = 7
DEVMODE_SINGLE_ANGLE = 8
DEVMODE_CONTIN_ANGLE = 9
DEVMODE_INDIRECT_HEIGHT = 10
DEVMODE_INDIRECT_LENGTH = 11
DEVMODE_DOUBLE_INDIRECT_HEIGHT_FINAL = 13
DEVMODE_WALL_AREA_CONSECUTIVE = 15
DEVMODE_LEVEL = 22
DEVMODE_CONTIN_LEVEL = 23
REMOTECTRLCMD_SET_DEV_APP_MODE = 60

DEVMODE_LABELS = {
    DEVMODE_NO_ACTION: "Aucune action (1er appui : laser allume, pas de mesure)",
    DEVMODE_SINGLE_DISTANCE: "Distance simple",
    DEVMODE_CONTIN_DISTANCE: "Distance continue",
    DEVMODE_AREA_FINAL: "Aire",
    DEVMODE_VOLUME_FINAL: "Volume",
    DEVMODE_SINGLE_ANGLE: "Angle simple",
    DEVMODE_CONTIN_ANGLE: "Angle continu",
    DEVMODE_INDIRECT_HEIGHT: "Hauteur indirecte",
    DEVMODE_INDIRECT_LENGTH: "Longueur indirecte",
    DEVMODE_DOUBLE_INDIRECT_HEIGHT_FINAL: "Double hauteur indirecte",
    DEVMODE_WALL_AREA_CONSECUTIVE: "Aire de mur",
    DEVMODE_LEVEL: "Niveau a bulle",
    DEVMODE_CONTIN_LEVEL: "Niveau a bulle continu",
}

# Response Status byte, Comm Status bits[2:0] meaning
COMM_STATUS_LABELS = {
    0: "OK",
    1: "Timeout de communication",
    2: "Mode invalide / non supporte",
    3: "Erreur de checksum",
    4: "Commande inconnue",
    5: "Niveau d'acces invalide",
    6: "Parametre ou donnee invalide",
    7: "reserve",
}


def crc8(data: bytes) -> int:
    """Bosch MT-protocol CRC-8 (poly 0xA6, init 0xAA, MSB-first, no reflection/xorout)."""
    crc = 0xAA
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xA6) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_frame(command: int, data: bytes = b"") -> bytes:
    """Build a LONG-format request frame: Mode, Command, DataLen, Data, CRC-8."""
    body = bytes([MODE_REQUEST_LONG, command, len(data)]) + data
    return body + bytes([crc8(body)])


def check_frame(frame: bytes) -> bool:
    """Verify a received/sent frame's trailing CRC-8 byte."""
    if len(frame) < 1:
        return False
    return crc8(frame[:-1]) == frame[-1]


def decode_status(status: int) -> dict:
    """Decode a response Status byte: device-state bits + Comm Status meaning."""
    return {
        "hand_raised": bool(status & 0x20),
        "device_not_ready": bool(status & 0x10),
        "hardware_error": bool(status & 0x08),
        "comm_status": status & 0x07,
        "comm_status_label": COMM_STATUS_LABELS.get(status & 0x07, "?"),
    }


def breakdown_frame(data: bytes) -> list[dict]:
    """Byte-level breakdown of a frame into labelled fields, for teaching the
    LONG frame layout regardless of whether the command/content is otherwise
    recognised. Two shapes: Mode=0xC0 (request/event) vs Status (response)."""
    if not data:
        return []
    fields = []
    crc_ok = check_frame(data)
    if data[0] == MODE_REQUEST_LONG:
        fields.append({"label": "Mode", "value": f"0x{data[0]:02x} (requete / evenement)"})
        if len(data) > 1:
            fields.append({"label": "Commande", "value": f"0x{data[1]:02x}"})
        if len(data) > 2:
            n = data[2]
            payload = data[3:3 + n]
            fields.append({"label": "Longueur donnees", "value": str(n)})
            fields.append({"label": "Donnees", "value": payload.hex(" ") if payload else "(vide)"})
    else:
        status = data[0]
        st = decode_status(status)
        fields.append({"label": "Status", "value": f"0x{status:02x} ({st['comm_status_label']})"})
        flags = [name for name, on in (
            ("main levee", st["hand_raised"]),
            ("appareil non pret", st["device_not_ready"]),
            ("erreur materielle", st["hardware_error"]),
        ) if on]
        if flags:
            fields.append({"label": "Indicateurs", "value": ", ".join(flags)})
        if len(data) > 1:
            n = data[1]
            payload = data[2:2 + n]
            fields.append({"label": "Longueur donnees", "value": str(n)})
            fields.append({"label": "Donnees", "value": payload.hex(" ") if payload else "(vide)"})
    fields.append({"label": "CRC-8", "value": f"0x{data[-1]:02x} ({'valide' if crc_ok else 'INVALIDE'})"})
    return fields


# --- Ready-made request frames -------------------------------------------

def frame_enable_autosync() -> bytes:
    """Enable AutoSync so the LRF starts sending measurement/button events.
    Equivalent to the already-validated ENABLE_STREAM = C0 55 02 01 00 1A."""
    return build_frame(CMD_EXCHANGE_DATA, bytes([DEVMODESYNC_ENABLE_AUTOSYNC, 0x00]))


def frame_remote_trigger_measure() -> bytes:
    """Simulate pressing the physical measure button (needs AutoSync enabled first).
    On this device, a first press turns the laser on and a second executes the
    measurement (both are echoed as events) -- prefer frame_measure() for a
    reliable single-shot remote measurement instead."""
    return build_frame(CMD_REMOTE_TRIGGER, bytes([EN_BUTTON_MEASURE]))


def frame_measure(mode: int = MEAS_MODE_SINGLE, reference: int = MEAS_REF_FRONT) -> bytes:
    """Standalone measurement command (handles laser on/off itself, single shot).
    mode: MEAS_MODE_SINGLE / MEAS_MODE_CONTINUOUS / MEAS_MODE_STOP_CONTINUOUS.
    Response is a direct LONG response (Status, DataLen=4, uint32 distance
    in 50 micrometre units, CRC), NOT an Exchange Data Container event.
    Note per the doc: in continuous mode each new value still has to be polled
    by sending this command again -- it is not an automatic stream."""
    return build_frame(CMD_MEASURE, bytes([reference | mode]))


def frame_laser_on() -> bytes:
    return build_frame(CMD_LASER_ON)


def frame_laser_off() -> bytes:
    return build_frame(CMD_LASER_OFF)


def frame_buzzer_on() -> bytes:
    return build_frame(CMD_BUZZER_ON)


def frame_buzzer_off() -> bytes:
    return build_frame(CMD_BUZZER_OFF)


def frame_backlight_on() -> bytes:
    return build_frame(CMD_LCD_BACKLIGHT_ON)


def frame_backlight_off() -> bytes:
    return build_frame(CMD_LCD_BACKLIGHT_OFF)


def frame_get_comm_info() -> bytes:
    return build_frame(CMD_GET_COMM_INFO)


def frame_get_device_name() -> bytes:
    return build_frame(CMD_GET_DEVICE_NAME)


def frame_get_device_info() -> bytes:
    return build_frame(CMD_GET_DEVICE_INFO)


def frame_get_rtc() -> bytes:
    return build_frame(CMD_GET_RTC)


def frame_get_battery_soc() -> bytes:
    return build_frame(CMD_GET_BATTERY_SOC)


def frame_check_laser_enable() -> bytes:
    return build_frame(CMD_CHECK_LASER_ENABLE)


def frame_get_laser_class() -> bytes:
    return build_frame(CMD_GET_LASER_CLASS)


def frame_get_measurement_info() -> bytes:
    return build_frame(CMD_GET_MEASUREMENT_INFO)


def frame_echo(payload: bytes = b"\x77\x88") -> bytes:
    return build_frame(CMD_DO_ECHO, payload)


def frame_ping() -> bytes:
    return build_frame(CMD_DO_PING)


def frame_set_dev_app_mode(dev_mode: int) -> bytes:
    """Switch the LRF's active measurement mode remotely (Exchange Data
    Container, RemoteCtrlCmd=60 SetDevAppMode). Follow up with
    frame_remote_trigger_measure() to actually take that measurement; the
    result comes back as an Exchange Data Container event with this dev_mode."""
    dev_mode_sync = (REMOTECTRLCMD_SET_DEV_APP_MODE << 2) | DEVMODESYNC_ENABLE_AUTOSYNC
    return build_frame(CMD_EXCHANGE_DATA, bytes([dev_mode_sync & 0xFF, dev_mode]))


# --- Response / event parsing ---------------------------------------------

def parse_exchange_data_container(data: bytes):
    """Decode an Exchange Data Container event/response (LONG frame with
    Command echoed = 0x55): Mode(1) Cmd(1) DataLen(1) [DevModeRef(1)
    DevStatus(1) UniqueID(2) Result(4f) Component1(4f) Component2(4f)] CRC(1).
    Returns a dict, or None if the frame doesn't look like this shape.
    """
    if len(data) < 19 or data[0] != MODE_REQUEST_LONG or data[1] != CMD_EXCHANGE_DATA:
        return None
    dev_mode_ref = data[3]
    dev_mode = dev_mode_ref >> 2
    ref_edge = dev_mode_ref & 0b11
    dev_status = data[4]
    (unique_id,) = struct.unpack_from("<H", data, 5)
    (result,) = struct.unpack_from("<f", data, 7)
    (comp1,) = struct.unpack_from("<f", data, 11)
    (comp2,) = struct.unpack_from("<f", data, 15)
    return {
        "dev_mode": dev_mode,
        "dev_mode_label": DEVMODE_LABELS.get(dev_mode, str(dev_mode)),
        "ref_edge": ref_edge,
        "laser_on": bool(dev_status & 0b1),
        "unique_id": unique_id,
        "result": result,
        "component1": comp1,
        "component2": comp2,
        "crc_ok": check_frame(data),
    }


def parse_direct_response(data: bytes):
    """Decode a direct LONG response to a request we sent: Status(1) DataLen(1)
    Data(N) CRC(1). Returns a dict with the raw payload plus decoded status
    bits, or None if it looks like a Mode=0xC0 event frame instead (use
    parse_exchange_data_container)."""
    if len(data) < 3 or (data[0] & 0xC0) != 0x00:
        return None
    status, length = data[0], data[1]
    payload = data[2:2 + length]
    return {
        "status": status,
        "ok": (status & 0x07) == 0,
        **decode_status(status),
        "payload": payload,
        "crc_ok": check_frame(data),
    }


# --- Payload decoders for specific commands (call once you know what you asked for) ---

def decode_measure_distance(payload: bytes) -> float | None:
    """CMD_MEASURE response payload -> distance in meters (raw unit = 50 micrometres)."""
    if len(payload) < 4:
        return None
    (raw,) = struct.unpack_from("<I", payload, 0)
    return raw * 0.00005


def decode_battery_soc(payload: bytes) -> int | None:
    return payload[0] if payload else None


def decode_laser_class(payload: bytes) -> int | None:
    return payload[0] if payload else None


def decode_laser_enable_status(payload: bytes) -> bool | None:
    return bool(payload[0]) if payload else None


def decode_rtc(payload: bytes) -> int | None:
    if len(payload) < 4:
        return None
    (seconds,) = struct.unpack_from("<I", payload, 0)
    return seconds


def decode_device_name(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def decode_device_info(payload: bytes) -> dict | None:
    if len(payload) < 29:
        return None
    date_code = payload[0:3].decode("ascii", errors="replace")
    (serial_no,) = struct.unpack_from("<I", payload, 4)
    (sw_revision,) = struct.unpack_from("<H", payload, 8)
    sw_version = tuple(payload[10:13])
    hw_version = tuple(payload[13:16])
    ttnr = payload[16:29].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return {
        "date_code": date_code,
        "serial_no": serial_no,
        "sw_revision": sw_revision,
        "sw_version": sw_version,
        "hw_version": hw_version,
        "ttnr": ttnr,
    }


def decode_measurement_info(payload: bytes) -> dict | None:
    if len(payload) < 20:
        return None
    snr, snr_star, vhv, dac, temperature = struct.unpack_from("<5f", payload, 0)
    return {
        "snr": snr,
        "snr_star": snr_star,
        "vhv": vhv,
        "dac": dac,
        "temperature": temperature,
    }


def decode_comm_info(payload: bytes) -> dict | None:
    if len(payload) < 8:
        return None
    (max_rx, max_tx) = struct.unpack_from("<HH", payload, 4)
    return {
        "program_mode": payload[0],
        "frame_modes": payload[1],
        "baud_rates": payload[2],
        "comm_modes": payload[3],
        "max_payload_rx": max_rx,
        "max_payload_tx": max_tx,
    }


# Maps a command byte to the decoder for its direct-response payload, so the
# caller (server.py) can interpret a generic Status/Data response once it
# knows which command it just sent.
PAYLOAD_DECODERS = {
    CMD_MEASURE: decode_measure_distance,
    CMD_GET_BATTERY_SOC: decode_battery_soc,
    CMD_GET_LASER_CLASS: decode_laser_class,
    CMD_CHECK_LASER_ENABLE: decode_laser_enable_status,
    CMD_GET_RTC: decode_rtc,
    CMD_GET_DEVICE_NAME: decode_device_name,
    CMD_GET_DEVICE_INFO: decode_device_info,
    CMD_GET_MEASUREMENT_INFO: decode_measurement_info,
    CMD_GET_COMM_INFO: decode_comm_info,
}
