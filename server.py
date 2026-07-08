"""
Serveur web local pour piloter le Bosch GLM 50 C en Bluetooth Low Energy.

Backend FastAPI + WebSocket : la connexion BLE (via bleak) tourne cote serveur,
le navigateur n'a besoin de rien d'autre qu'une page web (fonctionne avec
n'importe quel navigateur, pas seulement Chrome/Edge, puisqu'aucun Web
Bluetooth API n'est utilise cote client).

Lancement : python server.py, puis ouvrir http://127.0.0.1:8000/
"""
import asyncio
import json
from pathlib import Path

from bleak import BleakClient, BleakScanner
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import bosch_mt as mt

ADDRESS = "b0:10:a0:a1:35:0d"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()

COMMANDS = {
    "measure": lambda: mt.frame_measure(),
    "measure_continuous": lambda: mt.frame_measure(mode=mt.MEAS_MODE_CONTINUOUS),
    "measure_stop": lambda: mt.frame_measure(mode=mt.MEAS_MODE_STOP_CONTINUOUS),
    "remote_trigger": mt.frame_remote_trigger_measure,
    "laser_on": mt.frame_laser_on,
    "laser_off": mt.frame_laser_off,
    "buzzer_on": mt.frame_buzzer_on,
    "buzzer_off": mt.frame_buzzer_off,
}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


class GlmSession:
    """One BLE connection to the GLM, driven by one browser tab's WebSocket."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.client: BleakClient | None = None
        self.loop = asyncio.get_event_loop()

    async def send_json(self, payload: dict):
        await self.websocket.send_text(json.dumps(payload))

    async def send_status(self, status: str, message: str = ""):
        await self.send_json({"type": "status", "status": status, "message": message})

    async def send_frame_log(self, direction: str, data: bytes, extra: dict | None = None):
        await self.send_json({
            "type": "frame",
            "direction": direction,
            "hex": data.hex(" "),
            "extra": extra,
        })

    def on_notify(self, _characteristic, data: bytearray):
        """bleak notification callback (sync); schedules the async log send."""
        data = bytes(data)
        extra = None
        event = mt.parse_exchange_data_container(data)
        if event is not None:
            extra = {"kind": "event", **event}
        else:
            resp = mt.parse_direct_response(data)
            if resp is not None:
                extra = {
                    "kind": "response",
                    "status": resp["status"],
                    "ok": resp["ok"],
                    "payload": resp["payload"].hex(" "),
                    "crc_ok": resp["crc_ok"],
                }
        asyncio.run_coroutine_threadsafe(self.send_frame_log("rx", data, extra), self.loop)

    async def connect(self) -> bool:
        await self.send_status("scanning", "Recherche du GLM (Bluetooth actif a l'ecran ?)...")
        device = await BleakScanner.find_device_by_address(ADDRESS, timeout=15.0)
        if device is None:
            await self.send_status("error", "GLM introuvable. Active le Bluetooth sur son ecran et reessaie.")
            return False

        self.client = BleakClient(device)
        await self.client.connect()
        await self.client.start_notify(mt.CHAR_UUID, self.on_notify)
        await self.send_status("connected", "Connecte au GLM.")

        await self.send_command_frame(mt.frame_enable_autosync())
        return True

    async def send_command_frame(self, frame: bytes):
        if self.client is None or not self.client.is_connected:
            await self.send_status("error", "Non connecte.")
            return
        await self.send_frame_log("tx", frame)
        await self.client.write_gatt_char(mt.CHAR_UUID, frame, response=True)

    async def disconnect(self):
        if self.client is not None and self.client.is_connected:
            await self.client.stop_notify(mt.CHAR_UUID)
            await self.client.disconnect()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = GlmSession(websocket)
    try:
        if not await session.connect():
            await websocket.close()
            return

        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            command = message.get("cmd")
            build_frame = COMMANDS.get(command)
            if build_frame is None:
                await session.send_status("error", f"Commande inconnue: {command}")
                continue
            await session.send_command_frame(build_frame())
    except WebSocketDisconnect:
        pass
    finally:
        await session.disconnect()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
