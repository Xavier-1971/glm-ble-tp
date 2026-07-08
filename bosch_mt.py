"""
Bosch MT connectivity protocol (BLE) helpers for the Bosch GLM 50 C.

Source: official Bosch documentation
  - "Bosch MT connectivity protocol", issue 1.2.9 (general frame format, CRC-8)
  - "MT protocol LRF command set", issue 2.5.0 (laser-rangefinder-specific commands)
found via github.com/PointerEvent/bosch-plr-demo/tree/main/docs (copies kept
in ./docs/ in this repo). Command bytes and the CRC-8 parameters below were
verified against the 14 worked examples in section 6 of the LRF doc plus the
AutoSyncEnable frame already captured working live on our GLM 50 C.

Frame format (LONG, the only one used here):
  Request:  [Mode=0xC0][Command][DataLen N][Data * N][CRC-8]
  Response: [Status][DataLen N][Data * N][CRC-8]
  Event (LRF acting as master, e.g. after a button press or remote trigger):
            [Mode=0xC0][Command][DataLen N][Data * N][CRC-8]  (same shape as a request)

CRC-8: poly x^8+x^6+x^3+x^2+1 (0xA6), init 0xAA, MSB-first, no reflection,
no final XOR. Computed over every byte from Mode/Status up to the last Data
byte (i.e. everything except the CRC byte itself).
"""
import struct

CHAR_UUID = "02a6c0d1-0451-4000-b000-fb3210111989"

MODE_REQUEST_LONG = 0xC0

# --- MT global commands (same on every Bosch MT device) ---
CMD_GET_COMM_INFO = 0x00
CMD_GET_DEVICE_NAME = 0x05
CMD_GET_DEVICE_INFO = 0x06

# --- LRF-specific commands (decimal command number -> hex byte on the wire) ---
CMD_MEASURE = 0x40          # cmd 64 dec: single/continuous distance measurement
CMD_LASER_ON = 0x41         # cmd 65 dec
CMD_LASER_OFF = 0x42        # cmd 66 dec
CMD_BUZZER_ON = 0x45        # cmd 69 dec
CMD_BUZZER_OFF = 0x46       # cmd 70 dec
CMD_GET_BATTERY_SOC = 0x4B  # cmd 75 dec
CMD_EXCHANGE_DATA = 0x55    # cmd 85 dec: Exchange data container (AutoSync/RemoteCtrl)
CMD_REMOTE_TRIGGER = 0x56   # cmd 86 dec: Do Remote Trigger Button

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
# Bit[7..2] = DevMode / RemoteCtrlCmd, e.g. 0 = NoAction, 60 = SetDevAppMode


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


# --- Ready-made request frames -------------------------------------------

def frame_enable_autosync() -> bytes:
    """Enable AutoSync so the LRF starts sending measurement/button events.
    Equivalent to the already-validated ENABLE_STREAM = C0 55 02 01 00 1A."""
    return build_frame(CMD_EXCHANGE_DATA, bytes([DEVMODESYNC_ENABLE_AUTOSYNC, 0x00]))


def frame_remote_trigger_measure() -> bytes:
    """Simulate pressing the physical measure button (needs AutoSync enabled first).
    The result arrives asynchronously as an Exchange Data Container event
    (same frame shape parse_exchange_data_container() below decodes)."""
    return build_frame(CMD_REMOTE_TRIGGER, bytes([EN_BUTTON_MEASURE]))


def frame_measure(mode: int = MEAS_MODE_SINGLE, reference: int = MEAS_REF_FRONT) -> bytes:
    """Standalone measurement command (handles laser on/off itself).
    mode: MEAS_MODE_SINGLE / MEAS_MODE_CONTINUOUS / MEAS_MODE_STOP_CONTINUOUS.
    Response is a direct LONG response (Status, DataLen=4, uint32 distance
    in 50 micrometre units, CRC), NOT an Exchange Data Container event."""
    return build_frame(CMD_MEASURE, bytes([reference | mode]))


def frame_laser_on() -> bytes:
    return build_frame(CMD_LASER_ON)


def frame_laser_off() -> bytes:
    return build_frame(CMD_LASER_OFF)


def frame_buzzer_on() -> bytes:
    return build_frame(CMD_BUZZER_ON)


def frame_buzzer_off() -> bytes:
    return build_frame(CMD_BUZZER_OFF)


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
        "ref_edge": ref_edge,
        "laser_on": bool(dev_status & 0b1),
        "unique_id": unique_id,
        "result": result,
        "component1": comp1,
        "component2": comp2,
        "crc_ok": check_frame(data),
    }


def parse_direct_response(data: bytes):
    """Decode a direct LONG response to a request we sent (e.g. CMD_MEASURE):
    Status(1) DataLen(1) Data(N) CRC(1). Returns a dict, or None if it looks
    like a Mode=0xC0 event frame instead (use parse_exchange_data_container)."""
    if len(data) < 3 or (data[0] & 0xC0) != 0x00:
        return None
    status, length = data[0], data[1]
    payload = data[2:2 + length]
    return {
        "status": status,
        "ok": status == 0,
        "payload": payload,
        "crc_ok": check_frame(data),
    }
