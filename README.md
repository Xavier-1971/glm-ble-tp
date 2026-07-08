# GLM 50 C — TP Bluetooth (lycee)

Controle a distance d'un telemetre laser Bosch GLM 50 C en Bluetooth Low Energy (BLE), pour un
TP Bluetooth niveau premiere. Interface web locale : declenchement de mesure, mode continu,
laser on/off, buzzer on/off, avec affichage en direct des trames envoyees/recues.

## Materiel necessaire

- Un telemetre Bosch GLM 50 C (ou compatible : GLM 100 C, PLR 30/50 C...) avec le Bluetooth
  active sur son ecran.
- Un PC avec Bluetooth (integre ou cle USB) sous Windows/Linux/macOS.

## Installation

```
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

## Utilisation

1. Active le Bluetooth sur l'ecran du GLM (il reste actif quelques minutes).
2. Modifie si besoin l'adresse BLE du GLM dans `server.py` (`ADDRESS = "..."`) — la sienne se
   trouve en lancant `scan_glm.py` a proximite de l'appareil.
3. Lance le serveur :
   ```
   python server.py
   ```
4. Ouvre http://127.0.0.1:8000/ dans n'importe quel navigateur.

Le navigateur ne fait que dialoguer avec ce serveur local (WebSocket) : c'est le serveur Python,
via `bleak`, qui gere la connexion BLE reelle. N'importe quel navigateur convient (pas besoin de
Chrome/Edge specifiquement, puisque le Web Bluetooth API du navigateur n'est pas utilise).

## Structure du projet

- `server.py` — serveur FastAPI + WebSocket : pilote la connexion BLE et relaie les trames vers
  la page web.
- `static/index.html` — interface web (boutons de commande + journal des trames TX/RX).
- `bosch_mt.py` — implementation du protocole Bosch MT (CRC-8, construction des trames,
  decodage des reponses/evenements).
- `docs/commands_reference.md` — reference de toutes les commandes du protocole, implementees
  ou non.
- `docs/SOURCES.md` — provenance des documents officiels Bosch utilises pour reverse-engineerer
  le protocole.
- `crc_bruteforce.py` — script ayant servi a determiner precisement la variante de CRC-8 utilisee
  (garde comme preuve/documentation, pas destine a etre relance en usage normal).
- `measure_glm.py`, `find_glm.py`, `scan_glm.py`, `control_glm.py` — scripts de decouverte/test
  anterieurs au serveur web, gardes pour reference et pour du debug en ligne de commande.

## Protocole

Voir `docs/commands_reference.md` pour le detail des commandes disponibles et `bosch_mt.py`
pour l'implementation (CRC-8 : poly `0xA6`, init `0xAA`, MSB-first, sans reflexion ni XOR final).
