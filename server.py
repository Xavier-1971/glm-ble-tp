"""
Serveur web local pour piloter le Bosch GLM 50 C en Bluetooth Low Energy.

Backend FastAPI + WebSocket : la connexion BLE (via bleak) tourne cote serveur,
le navigateur n'a besoin de rien d'autre qu'une page web (fonctionne avec
n'importe quel navigateur, pas seulement Chrome/Edge, puisqu'aucun Web
Bluetooth API n'est utilise cote client). Chaque trame TX/RX est aussi
journalisee dans logs/ (un fichier par lancement du serveur, les 10 plus
recents sont conserves) et sur la sortie standard.

Lancement : python server.py, puis ouvrir http://127.0.0.1:8000/
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import bosch_mt as mt

ADDRESS = "b0:10:a0:a1:35:0d"
STATIC_DIR = Path(__file__).parent / "static"
LOG_DIR = Path(__file__).parent / "logs"
MAX_LOG_FILES = 10
DEFAULT_CONTINUOUS_INTERVAL_MS = 200


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"server_{timestamp}.log"

    logger = logging.getLogger("glm")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Ne garde que les MAX_LOG_FILES fichiers de log les plus recents.
    existing = sorted(LOG_DIR.glob("server_*.log"))
    for old_log in existing[:-MAX_LOG_FILES]:
        old_log.unlink()

    logger.info(f"Journal de cette session : {log_path}")
    return logger


logger = setup_logging()

app = FastAPI()

# Commandes sans parametre : nom envoye par le navigateur -> constructeur de trame.
SIMPLE_COMMANDS = {
    "measure": mt.frame_measure,
    "remote_trigger": mt.frame_remote_trigger_measure,
    "laser_on": mt.frame_laser_on,
    "laser_off": mt.frame_laser_off,
    "buzzer_on": mt.frame_buzzer_on,
    "buzzer_off": mt.frame_buzzer_off,
    "backlight_on": mt.frame_backlight_on,
    "backlight_off": mt.frame_backlight_off,
    "get_device_name": mt.frame_get_device_name,
    "get_device_info": mt.frame_get_device_info,
    "get_rtc": mt.frame_get_rtc,
    "get_battery_soc": mt.frame_get_battery_soc,
    "check_laser_enable": mt.frame_check_laser_enable,
    "get_laser_class": mt.frame_get_laser_class,
    "get_measurement_info": mt.frame_get_measurement_info,
    "get_comm_info": mt.frame_get_comm_info,
    "echo": mt.frame_echo,
    "ping": mt.frame_ping,
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
        self.last_command: int | None = None
        self.last_rx_time: float | None = None
        self.response_ready = asyncio.Event()
        self.continuous_task: asyncio.Task | None = None
        self.continuous_lock = asyncio.Lock()

    async def send_json(self, payload: dict):
        await self.websocket.send_text(json.dumps(payload))

    async def send_status(self, status: str, message: str = ""):
        await self.send_json({"type": "status", "status": status, "message": message})
        logger.info(f"[status] {status}: {message}")

    async def send_frame_log(self, direction: str, data: bytes, extra: dict | None = None):
        now = time.monotonic()
        elapsed_ms = None
        if direction == "rx":
            if self.last_rx_time is not None:
                elapsed_ms = round((now - self.last_rx_time) * 1000)
            self.last_rx_time = now
        await self.send_json({
            "type": "frame",
            "direction": direction,
            "hex": data.hex(" "),
            "extra": extra,
            "elapsed_ms": elapsed_ms,
            "fields": mt.breakdown_frame(data),
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        })
        logger.info(f"[{direction.upper()}] {data.hex(' ')}  extra={extra}  elapsed_ms={elapsed_ms}")

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
                decoder = mt.PAYLOAD_DECODERS.get(self.last_command)
                decoded = None
                if decoder is not None and resp["ok"]:
                    try:
                        decoded = decoder(resp["payload"])
                    except Exception:
                        decoded = None
                extra = {
                    "kind": "response",
                    "status": resp["status"],
                    "ok": resp["ok"],
                    "comm_status_label": resp["comm_status_label"],
                    "payload": resp["payload"].hex(" "),
                    "crc_ok": resp["crc_ok"],
                    "decoded": decoded,
                    "command": f"0x{self.last_command:02x}" if self.last_command is not None else None,
                }
                self.loop.call_soon_threadsafe(self.response_ready.set)
            elif data and data[0] == mt.MODE_REQUEST_LONG:
                # Evenement spontane du GLM sur une commande qu'on ne decode pas
                # encore (ex: 0x11, semble periodique, role inconnu).
                extra = {"kind": "event_unknown", "cmd": f"0x{data[1]:02x}" if len(data) > 1 else "?"}
        asyncio.run_coroutine_threadsafe(self.send_frame_log("rx", data, extra), self.loop)

    async def connect(self, scan_timeout: float = 15.0) -> bool:
        await self.send_status("scanning", f"Recherche du GLM {ADDRESS} (Bluetooth actif a l'ecran ?)...")
        device = await BleakScanner.find_device_by_address(ADDRESS, timeout=scan_timeout)
        if device is None:
            await self.send_status("error", "GLM introuvable. Active le Bluetooth sur son ecran et reessaie.")
            return False

        await self.send_status("scanning", f"GLM trouve ({device.name or 'sans nom'}), connexion BLE en cours...")
        try:
            self.client = BleakClient(device, disconnected_callback=self._on_disconnected)
            await self.client.connect()

            await self.send_status("scanning", "Connecte, abonnement aux notifications de la caracteristique...")
            await self.client.start_notify(mt.CHAR_UUID, self.on_notify)

            await self.send_status("scanning", "Activation du mode AutoSync (necessaire pour recevoir les mesures)...")
            await self.send_command_frame(mt.frame_enable_autosync())
        except Exception as exc:
            logger.info(f"[connect] echec: {exc}")
            await self.send_status(
                "error",
                "Connexion au GLM impossible (le Bluetooth s'est peut-etre desactive entre-temps sur l'appareil).",
            )
            self.client = None
            return False

        await self.send_status("connected", "Connecte et pret.")
        return True

    def _on_disconnected(self, _client: BleakClient):
        """bleak callback (sync) fired when the BLE link drops unexpectedly."""
        asyncio.run_coroutine_threadsafe(self._handle_disconnect(), self.loop)

    async def _handle_disconnect(self):
        await self._cancel_continuous_task()
        await self.send_status("error", "Connexion Bluetooth perdue, tentative de reconnexion...")

        for attempt in range(1, 4):
            await asyncio.sleep(2)
            await self.send_status("scanning", f"Reconnexion (essai {attempt}/3)...")
            try:
                if await self.connect(scan_timeout=10.0):
                    return
            except Exception as exc:
                logger.info(f"[reconnect] tentative {attempt} echouee: {exc}")

        await self.send_status(
            "error",
            "Reconnexion impossible. Verifie que le Bluetooth du GLM est actif et recharge la page.",
        )

    async def send_command_frame(self, frame: bytes):
        if self.client is None or not self.client.is_connected:
            await self.send_status("error", "Non connecte.")
            return
        self.last_command = frame[1]
        await self.send_frame_log("tx", frame)
        try:
            await self.client.write_gatt_char(mt.CHAR_UUID, frame, response=True)
        except Exception as exc:
            await self.send_status("error", f"Echec d'envoi (connexion Bluetooth perdue ?) : {exc}")

    async def start_continuous(self, interval_ms: int):
        # Le mode "continu" natif de la commande 0x40 (bit mode=1) s'est avere
        # instable (le GLM cesse de repondre au bout de quelques secondes,
        # independamment du rythme des requetes). "Mesurer (un coup)" (mode
        # single, laser on -> mesure -> laser off a chaque appel), lui,
        # fonctionne de facon fiable meme repete rapidement -- on simule donc
        # simplement des appuis repetes sur ce bouton a intervalle regulier,
        # plutot que d'utiliser le mode continu du protocole.
        async with self.continuous_lock:
            await self._cancel_continuous_task()
            await self.send_status("continuous", f"Mesure repetee (intervalle demande {interval_ms} ms)...")

            async def poll_loop():
                # Le GLM peut avoir une coupure Bluetooth furtive (visible a
                # l'ecran : il coupe puis rallume tout seul) sans que bleak la
                # detecte comme une vraie deconnexion. Plutot qu'attendre
                # longtemps puis abandonner definitivement, on utilise un delai
                # d'attente plus court par tentative et on retente automatiquement
                # tant que la connexion reste valide, avant de renoncer.
                per_attempt_timeout_s = 3.0
                max_attempts = 5
                consecutive_failures = 0
                try:
                    while True:
                        if self.client is None or not self.client.is_connected:
                            await self.send_status("error", "Connexion Bluetooth perdue : mesure repetee arretee.")
                            self.continuous_task = None
                            return
                        self.response_ready.clear()
                        t0 = time.monotonic()
                        await self.send_command_frame(mt.frame_measure(mode=mt.MEAS_MODE_SINGLE))
                        try:
                            await asyncio.wait_for(self.response_ready.wait(), timeout=per_attempt_timeout_s)
                            consecutive_failures = 0
                        except asyncio.TimeoutError:
                            consecutive_failures += 1
                            if self.client is None or not self.client.is_connected:
                                await self.send_status("error", "Connexion Bluetooth perdue : mesure repetee arretee.")
                                self.continuous_task = None
                                return
                            if consecutive_failures >= max_attempts:
                                await self.send_status(
                                    "error",
                                    f"Pas de reponse du GLM apres {max_attempts} tentatives : mesure repetee arretee.",
                                )
                                self.continuous_task = None
                                await self.send_status("connected", "Connexion toujours active.")
                                return
                            await self.send_status(
                                "continuous",
                                f"Pas de reponse (tentative {consecutive_failures}/{max_attempts}), on reessaie...",
                            )
                            continue
                        elapsed = time.monotonic() - t0
                        remaining = max(0.0, interval_ms / 1000 - elapsed)
                        await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    pass

            self.continuous_task = asyncio.create_task(poll_loop())

    async def _cancel_continuous_task(self):
        if self.continuous_task is not None:
            self.continuous_task.cancel()
            try:
                await self.continuous_task
            except (asyncio.CancelledError, Exception):
                pass
            self.continuous_task = None

    async def stop_continuous(self):
        async with self.continuous_lock:
            was_running = self.continuous_task is not None
            await self._cancel_continuous_task()
            if was_running:
                await self.send_status("connected", "Mesure repetee arretee.")

    async def disconnect(self):
        await self.stop_continuous()
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
            cmd = message.get("cmd")

            if cmd in SIMPLE_COMMANDS:
                await session.send_command_frame(SIMPLE_COMMANDS[cmd]())
            elif cmd == "set_mode":
                dev_mode = int(message.get("dev_mode", mt.DEVMODE_SINGLE_DISTANCE))
                await session.send_command_frame(mt.frame_set_dev_app_mode(dev_mode))
            elif cmd == "continuous_start":
                interval_ms = int(message.get("interval_ms", DEFAULT_CONTINUOUS_INTERVAL_MS))
                await session.start_continuous(interval_ms)
            elif cmd == "continuous_stop":
                await session.stop_continuous()
            else:
                await session.send_status("error", f"Commande inconnue: {cmd}")
    except WebSocketDisconnect:
        pass
    finally:
        await session.disconnect()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
