# NFSU Central Library Self-Service Kiosk — Module Guide
### Integrated with Koha 26 ILMS (PS-2)

[![Koha Status](https://img.shields.io/badge/KOHA%2026-SIP2%20v2.00-emerald?style=for-the-badge)](https://koha-community.org/)
[![RFID](https://img.shields.io/badge/RFID-PC%2FSC%20%28pyscard%29-002147?style=for-the-badge)](https://pyscard.sourceforge.io/)
[![Protocol](https://img.shields.io/badge/Protocol-ISO%2014443A%20%7C%20ISO%2015693-d97706?style=for-the-badge)](#hardware-zones)
[![Security Gate](https://img.shields.io/badge/Security%20Gate-AFI%200x07%20%7C%200xC2-red?style=for-the-badge)](#rfid-security-gate--buzzer)

This directory contains the kiosk application itself: a FastAPI backend that speaks
SIP2 to the live Koha 26 server and drives the physical RFID readers over PC/SC, plus
a vanilla-JS touch front-end.

> **No simulation.** There is no emulator, no simulated pad and no demo data. Every
> patron, item and tag value comes from the real Koha server or a real reader.

---

## 📁 Layout

```
kiosk/
├─ backend/
│  ├─ config.py          # Env-driven Koha + hardware settings
│  ├─ sip2_protocol.py   # AY/AZ builder + parser for all PS-2 message pairs
│  ├─ sip2_client.py     # Async TCP SIP2 client (login, heartbeat, reconnect)
│  ├─ pcsc_reader.py     # Cross-platform PC/SC reader layer (pyscard)
│  ├─ rfid_bridge.py     # Card / book-pad / gate zones, AFI two-phase commit
│  ├─ biometrics.py      # RAM-only liveness challenge + metric validation
│  ├─ hardware_map.json  # UID → Koha identifier mapping (cards, book tags)
│  └─ server.py          # FastAPI app: REST + WebSocket + static frontend
└─ frontend/
   ├─ index.html         # Kiosk UI shell
   ├─ css/
   │  ├─ bundle.css      # NFSU institutional stylesheet
   │  └─ nfsu-theme.css  # Kiosk component theme
   ├─ js/
   │  ├─ kiosk-app.js    # Main controller (workflows, receipt, scanner)
   │  ├─ face-liveness.js# Browser-side camera liveness analysis
   │  ├─ gate-buzzer.js  # Exit-gate siren / chime
   │  └─ sip2-console.js # SIP2 diagnostics drawer
   └─ assets/            # NFSU emblem + favicon
```

---

## 🔌 Hardware Zones

| Zone | Standard | Reader | How it is used |
| :--- | :--- | :--- | :--- |
| **Book pad** | ISO 15693 | Avery Dennison Smartrac / NXP ICODE SLIX2 over a PC/SC reader | Multi-tag inventory + AFI security byte read/write (`0x07` armed / `0xC2` disarmed) |
| **Patron card** | ISO 14443A | HID OMNIKEY / ACS ACR1252 | MIFARE UID → Koha account via `hardware_map.json` |
| **Exit gate** | ISO 15693 | Gate antenna reader | A tag leaving with an armed AFI raises the alarm |
| **Barcode** | HID / RS-232 | USB keyboard-wedge or COM-port scanner | Patron / item barcode capture |

Reader roles are matched by case-insensitive substring against the OS reader name
(`KIOSK_CARD_READER`, `KIOSK_BOOK_READER`, `KIOSK_GATE_READER`). Any unassigned role
falls back to the first free reader, so a single dual-protocol ACR1252 can serve a
bench setup.

---

## 🏆 Key PS-2 Requirements Implemented

### 1. Institutional UI
- Official NFSU emblem, institutional navy (`#002147`) and gold (`#ddb55e` / `#d97706`).
- Top utility strip with Ministry of Home Affairs wording, email, phone and a live
  **Koha** telemetry pill.
- The UI ships only the stylesheets and scripts it needs; there are no unused
  scraped bundles and no demo buttons.

### 2. Dual-Zone Mat & Multi-Tag Anti-Collision
- **Book zone**: ISO 15693 inventory resolves the tags actually present on the pad
  (up to the configured borrowing limit).
- **Card zone**: ISO 14443A MIFARE reader maps the card UID to a Koha patron.

### 3. Strict 2-Books-At-A-Time Limit
- Enforces `KOHA_MAX_BOOKS` (default `2`).
- Queries SIP2 `63` (summary position 3 = `Y`) and parses the Koha `64` charged count
  and `AU` barcodes. Excess checkout is blocked with a clear warning.

### 4. RFID Security Gate & Audible Siren (Web Audio API)
- Armed tag (`0x07`) → alternating 850/1150 Hz siren + crimson strobe banner.
- Disarmed tag (`0xC2`) → soft major-triad chime.
- **Two-phase commit**: AFI is written to `0xC2` only *after* Koha returns `OK=1`, and
  re-armed to `0x07` only after a confirmed check-in.

### 5. Camera Liveness (Zero Retention)
- Browser samples the camera, measures motion energy, eye-region closure and
  horizontal face drift.
- Only the anonymous metrics + a one-time nonce are sent; the server validates them
  against the challenge it issued and never accepts a bare boolean.
- Nothing biometric is written to disk.

### 6. Built-In SIP2 Testing Tool
- Packet builders for `99/98`, `93/94`, `63/64`, `17/18`, `11/12`, `09/10`, `29/30`.
- Raw ASCII inspector with `AY` sequence and `AZ` checksum validation.
- Live Koha SIP2 endpoint switcher.

---

## ⚡ Quick Start

```bash
# From the repository root
python diagnose_hardware.py                 # list real reader names
python run_kiosk.py --port 8000 \
    --sip-host <koha-host> --sip-port 6001 \
    --sip-user <sip2-user> --sip-pass <sip2-pass> \
    --card-reader OMNIKEY --book-reader ACR1252 --gate-reader Gate

# Run the verification tests
python tests/test_koha_kiosk.py
```

Then open `http://localhost:8000`.

---

## 🌐 API Surface

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Aggregated Koha + hardware health |
| `GET` | `/api/hardware/status` | pyscard availability, reader roles, map counts |
| `GET` | `/api/hardware/pad-state` | Live pad / card / gate snapshot |
| `POST` | `/api/hardware/scan-book` | Queue a barcode-scanned book (verified against Koha) |
| `POST` | `/api/hardware/scan-patron` | Authenticate a scanned patron barcode |
| `POST` | `/api/hardware/clear-scanned` | Clear barcode-scanner queue entries |
| `POST` | `/api/hardware/reload-map` | Hot-reload `hardware_map.json` |
| `POST` | `/api/circulation/patron-info` | SIP2 `63 → 64` patron lookup |
| `GET` | `/api/circulation/item-info` | SIP2 `17 → 18` item lookup |
| `POST` | `/api/circulation/checkout` | SIP2 `11 → 12` + tag disarm |
| `POST` | `/api/circulation/checkin` | SIP2 `09 → 10` + tag re-arm |
| `POST` | `/api/circulation/renew` | SIP2 `29 → 30` renewal |
| `POST` | `/api/biometrics/challenge` | Issue a one-time liveness challenge |
| `POST` | `/api/biometrics/verify` | Validate metrics + bind to patron |
| `POST` | `/api/sip2/send-raw` | Send an arbitrary SIP2 frame |
| `POST` | `/api/sip2/reconnect` | Switch the Koha SIP2 endpoint |
| `WS` | `/ws` | Live telemetry + pad / gate events |

The retired simulation endpoints (`/api/emulator/reset`, `/api/sip2/transactions`,
`/api/hardware/tap-card`, `/api/hardware/place-book`, `/api/hardware/place-two-books`,
`/api/hardware/pass-gate`, `/api/hardware/write-afi`) no longer exist and are asserted
absent by the test suite.
