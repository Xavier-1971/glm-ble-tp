# Bosch MT protocol — reference des commandes (GLM 50 C)

Source : `MT_connectivity_protocol_1_2_9.pdf` (commandes generiques MT) et
`MT_connectivity_protocol_LRF_command_set_2_5_0.pdf` (commandes specifiques telemetre laser).
Toutes les trames sont au format LONG : `[0xC0][Cmd][DataLen N][Data*N][CRC-8]`
(voir `bosch_mt.py` pour `build_frame()` / `crc8()`).

Colonne "dec/hex" : le numero de commande du tableau Bosch est en **decimal**, la colonne
donne l'octet hexa correspondant a envoyer sur le fil.

## Deja implementees dans `bosch_mt.py`

| Cmd (dec/hex) | Nom | Request data | Response data | Statut |
|---|---|---|---|---|
| 64 / 0x40 | Mesure simple/continue | 1 octet parametre (voir plus bas) | uint32 distance [50µm] | implementee, mode continu non teste |
| 65 / 0x41 | Laser on | - | - | implementee |
| 66 / 0x42 | Laser off | - | - | implementee |
| 69 / 0x45 | Buzzer on | - | - | implementee |
| 70 / 0x46 | Buzzer off | - | - | implementee |
| 85 / 0x55 | Exchange data container (AutoSync/RemoteCtrl) | voir plus bas | - | implementee (AutoSync only) |
| 86 / 0x56 | Declenchement bouton a distance | uint8 ButtonNumber (0=mesure) | evenement async via cmd 85 | implementee, non testee |

## Pas encore implementees mais utiles pour le TP

| Cmd (dec/hex) | Nom | Request | Response | Interet pedagogique |
|---|---|---|---|---|
| 0 / 0x00 | Get communication info | - | mode, frame modes, baudrates, taille max payload | debug/diagnostic |
| 4 / 0x04 | Get version commandes MT | - | 3+3 octets version | debug |
| 5 / 0x05 | Get device name | - | string 18 car. + EOS | identification appareil |
| 6 / 0x06 | Get device info | - | date code, n° serie, versions SW/HW, ref Bosch | identification appareil |
| 15 / 0x0F | Get RTC timestamp | - | uint32 secondes depuis 1970 | horodatage mesures |
| 16 / 0x10 | Set RTC timestamp | uint32 secondes | - | synchro horloge |
| 71 / 0x47 | LCD backlight on | - | - | confort visuel demo |
| 72 / 0x48 | LCD backlight off | - | - | confort visuel demo |
| 75 / 0x4B | Get battery pack SOC | - | uint8 % batterie | affichage etat pile |
| 76 / 0x4C | Check laser enable pin | - | uint8 statut laser | verifier etat laser |
| 77 / 0x4D | Get laser class | - | uint8 classe laser | securite |
| 83 / 0x53 | Get user settings | - | struct settings (unites, luminosite, ...) | lire config appareil |
| 84 / 0x54 | Set user settings | struct settings | - | changer unites (m/cm/mm/inch), etc. |
| 115 / 0x73 | Get measurement info | - | SNR, SNR*, VHV, DAC, temperature (floats) | mesures physiques annexes (temperature du capteur, bruit du signal) — bon pour un TP niveau physique |
| 81 / 0x51 | Get measurement list entries | start/stop index | n mesures (33 octets chacune) | recuperer l'historique de mesures stocke dans l'appareil |
| 82 / 0x52 | Clear measurement list entries | start/stop index | - | vider l'historique |
| 61 / 0x3D | CMD_DO_ECHO | payload | meme payload | tester la fiabilite de la liaison BLE (bon pour montrer le CRC aux eleves : corrompre un octet et voir l'erreur "Checksum error") |
| 63 / 0x3F | CMD_DO_PING | - | - | test de presence |

## Commandes non disponibles sur ce modele (GLM 50 C = plateforme SPAD)

- 67/68 (VCSEL on/off), 73/74 (keypad backlight) : "-" dans la colonne SPAD, pas implementees sur cet appareil.
- 176/177 (capteur 9 axes, orientation/fusion) : reserve aux modeles avec centrale inertielle (GLMCam), pas le GLM 50 C.
- 78/79 (classe laser reglable) : reserve a la plateforme GLM80, pas SPAD.

## Commande 85 (Exchange data container) — sous-commandes RemoteCtrlCmd

La commande 85 sert de "commande generique" : l'octet `DevModeSync` encode dans ses bits 7..2 un
`RemoteCtrlCmd` different selon ce qu'on veut faire. C'est la table la plus riche du protocole
pour un TP — elle permet en particulier de changer le **type de mesure** (pas seulement la
distance) :

| RemoteCtrlCmd | Nom | Resultat renvoye (evenement cmd 85) |
|---|---|---|
| 0 | NoAction | - |
| 1 | SingleDistance | Longueur [m] |
| 2 | ContinDistance | Longueur courante / min / max [m] |
| 3-4 | Area (partie 1 / finale) | Aire [m²] + 2 longueurs |
| 5-7 | Volume (parties 1/2/finale) | Volume [m³] + longueurs |
| 8 | SingleAngle | Angle [°] |
| 9 | ContinAngle | Angle courant / min / max [°] |
| 10 | IndirectHeight | Hauteur, longueur, angle |
| 11 | IndirectLength | Longueur, hauteur, angle |
| 12-13 | DoubleIndirectHeight (partie/finale) | Hauteur, hauteurs, angle total |
| 14-15 | WallArea (partie/consecutif) | Aire, longueurs |
| 16-21 | Calculs +/- (Distance/Aire/Volume) | resultat + 2 composantes |
| 22-23 | Level / Contin Level | Roll/Pitch [°] (niveau a bulle) |
| 58 | GetMeasListEntryByIndex | recupere une entree de l'historique |
| 59 | TemperatureAndSOC | SOC [%], temperature [°C] |
| 60 | SetDevAppMode | change le mode de l'appareil (ecrire un des DevMode ci-dessus dans RemoteCtrlData) |
| 61 | SetAngleReference | 0=back, 1=side, 2=rail |
| 62 | SetDistanceReference | 0=front, 1=tripod, 2=rear, 3=pin |
| 63 | ErrorMessage | code d'erreur (evenement automatique en cas de probleme) |

Pour changer de mode de mesure a distance (ex: passer en mode "Angle" ou "Aire"), on envoie la
commande 85 avec `DevModeSync = (60 << 2) | bit_autosync` et `RemoteCtrlData = <DevMode voulu>`
(ex: 8 pour SingleAngle), puis on utilise le bouton distant (commande 86) ou le bouton physique
pour lancer la mesure — le resultat revient comme evenement commande 85 avec ce DevMode.

## Parametre de la commande 64 (mesure)

Octet unique :
- Bits [7:6] reference : 0=avant, 1=trepied, 2=arriere, 3=broche
- Bits [4:3] frequence de mesure (OEM uniquement) : 0=5Hz, 1=10Hz, 2=20Hz, 3=30Hz
- Bit [2] temps de mesure (plateforme SPAD uniquement) : 0=auto, 1=fixe
- Bits [1:0] mode : 0=simple, 1=continu, 2=stop continu

## Format des trames generales (rappel)

- Requete LONG : `Mode(0xC0) | Cmd | DataLen N | Data*N | CRC-8`
- Reponse LONG : `Status | DataLen N | Data*N | CRC-8` (Status bits 7..6 = 00)
- Evenement LRF->App (ex apres appui bouton ou AutoSync) : meme forme qu'une requete, `Mode=0xC0`.
- CRC-8 : poly `0xA6`, init `0xAA`, MSB-first, sans reflexion ni XOR final — voir `bosch_mt.py::crc8()`.
