# National Forensic Sciences University (NFSU), Gandhinagar
## Central Library Self-Service Kiosk & SIP2 Diagnostic Suite
**Integrated with Koha 26 ILMS — Problem Statement 2 (PS-2)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Koha 26 SIP2](https://img.shields.io/badge/Koha_26-SIP2_v2.00-orange.svg)](https://koha-community.org/)
[![PC/SC](https://img.shields.io/badge/RFID-PC%2FSC_%28pyscard%29-2b6cb0.svg)](https://pyscard.sourceforge.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests Passing](https://img.shields.io/badge/Tests-9%2F9_Passing-brightgreen.svg)](tests/test_koha_kiosk.py)

---

## 🏛️ Executive Summary

A hardware-ready **Self-Service Library Kiosk** for the **National Forensic Sciences
University (NFSU), Gandhinagar**, integrated directly with the **Koha 26 Integrated
Library Management System (ILMS)** over SIP2 v2.00.

The kiosk drives **real hardware only**: real PC/SC contactless readers for patron
cards and book tags, a real exit-gate antenna, and a real Koha SIP2 server. There is
**no emulator, no simulated pad, and no demo fallback** anywhere in the codebase.
When Koha is unreachable or a reader is missing, the kiosk says so honestly instead
of inventing data.

The interface replicates the institutional design language of `https://www.nfsu.ac.in/`
featuring the official emblem, Ministry of Home Affairs banner and **3 giant touch
action tiles**: **`[ ISSUE ]`**, **`[ RETURN ]`**, and **`[ RENEW ]`**.

---

## 📸 Kiosk Interface

```
+---------------------------------------------------------------------------------------------------+
|  [Tricolor Strip]                                                                                  |
|  info@nfsu.ac.in | (079) 239 77100 | An Institution of National Importance | [ KOHA 26 LIVE ]      |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|                                [ NFSU Official Emblem ]                                           |
|                         राष्ट्रीय न्यायालयिक विज्ञान विश्वविद्यालय                                |
|                        National Forensic Sciences University                                      |
|                  Central Library Self-Check Circulation Kiosk (KOHA 26 ILMS)                      |
|                                                                                                   |
|             +-------------------+  +-------------------+  +-------------------+                   |
|             |    [ BOOK ICON ]  |  |   [ INBOX ICON ]  |  |    [ SYNC ICON ]  |                   |
|             |       ISSUE       |  |      RETURN       |  |       RENEW       |                   |
|             | Check Out Books   |  | Express Return    |  | Extend Due Dates  |                   |
|             |   (SIP2 11/12)    |  |   (SIP2 09/10)    |  |   (SIP2 29/30)    |                   |
|             +-------------------+  +-------------------+  +-------------------+                   |
|                                                                                                   |
|             Station Hardware panel  ·  live PC/SC reader readiness per role                       |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|  Gandhinagar-382007, Gujarat | Connected to Koha 26 ILMS | Host: <configured> | Inst: <configured>|
+---------------------------------------------------------------------------------------------------+
```

---

## ⚡ Core Architecture

```
+---------------------------------------------------------------------------------------------+
|                                    TOUCH KIOSK WEB UI                                       |
|   Vanilla JS: kiosk-app.js · face-liveness.js · gate-buzzer.js · sip2-console.js            |
|   NFSU institutional theme · Web Audio siren · browser camera liveness · SIP console        |
+---------------------------------------------------------------------------------------------+
                                       |              ^
             REST / WebSocket (/ws)    |              |  Real-time state broadcasts
                                       v              |
+---------------------------------------------------------------------------------------------+
|                                   FASTAPI KIOSK BACKEND                                     |
|  - Circulation orchestrator (issue, return, renewal, receipts)                              |
|  - Strict 2-books-at-a-time policy engine                                                   |
|  - PC/SC RFID bridge: card / book pad / gate (two-phase-commit AFI security)                |
|  - In-RAM ephemeral liveness validator (zero disk retention)                                |
+---------------------------------------------------------------------------------------------+
        |                          |                                    |
        | SIP2 (TCP)               | PC/SC (pyscard)                    | HID / serial
        v                          v                                    v
+---------------------+   +--------------------------------+   +-------------------------+
|  KOHA 26 ILMS       |   |  Contactless readers           |   |  Barcode scanner        |
|  SIP2 v2.00 server  |   |  ISO 14443A card reader        |   |  keyboard-wedge or      |
|  (99/98, 93/94,     |   |  ISO 15693 book pad            |   |  COM-port scanner       |
|   63/64, 17/18,     |   |  ISO 15693 exit-gate antenna   |   +-------------------------+
|   11/12, 09/10,     |   +--------------------------------+
|   29/30)            |
+---------------------+
```

---

## 🏆 PS-2 Expected Outcomes Checklist

| Feature | PS-2 Judge Requirement | Implementation Detail | Status |
| :--- | :--- | :--- | :--- |
| **A. Core Circulation** | Issue (`11 -> 12`), Return (`09 -> 10`), Renew (`29 -> 30`) | Asynchronous TCP SIP2 engine verifying Koha `OK=1` before updating RFID security bytes. | ✅ Complete |
| **B. 3-Way Authentication** | MIFARE Card, Barcode Scanner, AI Facial Recognition | MIFARE tap zone (PC/SC), USB keyboard-wedge / serial barcode auto-capture, browser camera blink/head-turn challenge validated server-side. | ✅ Complete |
| **C. 2-Books Limit Rule** | Strict limit of 2 books per patron | Parses Koha `64` charged-count and `AU` barcodes. If a patron holds 1 book and places 2 on the pad, checkout is blocked with an alert banner. | ✅ Complete |
| **D. Issued Books Counter** | Live metric `Books Currently Issued: X / 2` | Rendered at the top of the patron dashboard with a dynamic status ring (green = 0, amber = 1, red = 2). | ✅ Complete |
| **E. Dual-Zone Mat** | Large Book Zone + Bottom-Right Patron Card Zone | Real Avery Dennison Smartrac HF (ISO 15693) and HID OMNIKEY MIFARE (ISO 14443A) readers via PC/SC. | ✅ Complete |
| **F. Multi-Tag Anti-Collision** | Place 2 books simultaneously on the pad | Live ISO 15693 inventory resolves the tags present on the pad; no button-driven simulation. | ✅ Complete |
| **G. Security Gate & Siren** | Web Audio API buzzer for unissued books | A real armed tag (`AFI 0x07`) read by the gate antenna triggers the 850/1150 Hz siren; a disarmed tag (`AFI 0xC2`) passes with a chime. | ✅ Complete |
| **H. Zero-Retention Biometrics** | RAM-only ephemeral facial processing | Blink + head-pose challenge-response; only anonymous motion metrics leave the browser. Nothing is stored on device or server. | ✅ Complete |
| **I. Printable Receipts** | Official NFSU circulation receipts | Transaction timestamp, patron details, book barcode, due date, AFI tag state and a print button. | ✅ Complete |
| **J. SIP Testing Tool** | Built-in diagnostics console | Slide-out drawer with packet builders, raw socket terminal, round-trip latency and 16-bit two's-complement checksum parsing. | ✅ Complete |

---

## 🧰 Hardware Support

| Zone | Standard | Typical reader / tag | API |
| :--- | :--- | :--- | :--- |
| Patron card | ISO 14443A (MIFARE) | HID OMNIKEY 5022 CL / ACS ACR1252 | `PCSCReader.get_uid()` |
| Book pad | ISO 15693 | Avery Dennison Smartrac / NXP ICODE SLIX2 | `PCSCReader.read_book_tag()` |
| Exit gate | ISO 15693 | ACS ACR1252 antenna | `PCSCReader.read_book_tag()` |
| Barcode | HID keyboard-wedge or RS-232 | Any USB/COM barcode scanner | front-end capture / `pyserial` |

Reader roles are selected by **case-insensitive substring match** against the PC/SC
reader name reported by the OS (set `KIOSK_CARD_READER`, `KIOSK_BOOK_READER`,
`KIOSK_GATE_READER`, or the matching `run_kiosk.py` flags). Run
`python diagnose_hardware.py` first to list the exact names on your machine.

### Card / tag → Koha mapping (`kiosk/backend/hardware_map.json`)

Physical UIDs are mapped to Koha identifiers explicitly — the kiosk never
auto-registers or fabricates an account:

```json
{
  "patron_cards": {
    "04:A2:1B:7C:9E:00:00": "PATRON_BARCODE"
  },
  "book_tags": {
    "E0:04:01:23:45:67:89:AB": "ITEM_BARCODE"
  }
}
```

A card or tag whose UID is absent from the map is reported to the operator
(`UNKNOWN_CARD` / “unmapped tag”); it is never guessed. The map is hot-reloadable
via `POST /api/hardware/reload-map`.

---

## 🚀 Quickstart & Single-Command Launch

### 1. Prerequisites
- **Python 3.10 or higher** (see the `pyscard` wheel note below — 3.13 is safest)
- A modern browser (Chrome, Edge, Firefox) for the touch UI
- PC/SC contactless readers (the deployment desk uses HID OMNIKEY + ACS ACR1252)
- A reachable Koha 26 SIP2 endpoint with a circulating service account

> On Linux you also need the PC/SC daemon (`pcscd`) and `libpcsclite-dev`. On
> Windows the Smart Card service is built in. macOS uses the built-in PC/SC
> framework.

> **`pyscard` wheel note.** Prebuilt `pyscard` wheels are published for **Python
> 3.10–3.13** on Windows/macOS/Linux. On **Python 3.14** there is no wheel yet, so
> pip tries to compile it and fails without the **Microsoft C++ Build Tools**
> (`error: Microsoft Visual C++ 14.0 or greater is required`). For a zero-hassle
> install use **Python 3.13**.

### 2. Installation
```bash
git clone https://github.com/prnjlksingh/nfsu-library-kiosk.git
cd nfsu-library-kiosk
pip install -r requirements.txt
```

Windows (recommended — uses Python 3.13 so `pyscard` installs from a wheel):
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Then run everything through the venv interpreter, e.g.
`.\.venv\Scripts\python.exe run_kiosk.py --port 8000`.

`requirements.txt` installs `pyscard` (PC/SC reader access) and `pyserial`
(optional serial barcode scanner). Both are imported gracefully: the kiosk still
starts without them and reports the hardware as unavailable.

### 3. Configure Koha credentials (never hard-coded)
```bash
# Linux / macOS
export KOHA_SIP_HOST=117.239.182.15
export KOHA_SIP_PORT=6001
export KOHA_SIP_USER=<your-sip2-service-account>
export KOHA_SIP_PASS=<your-sip2-service-password>
export KOHA_INSTITUTION_ID=NFSUGNR
```
```powershell
# Windows PowerShell
$env:KOHA_SIP_HOST = "117.239.182.15"
$env:KOHA_SIP_PORT = "6001"
$env:KOHA_SIP_USER = "<your-sip2-service-account>"
$env:KOHA_SIP_PASS = "<your-sip2-service-password>"
$env:KOHA_INSTITUTION_ID = "NFSUGNR"
```

### 4. Launch the kiosk
```bash
python diagnose_hardware.py            # list the real reader names first
python run_kiosk.py --port 8000 \
    --sip-host 117.239.182.15 --sip-port 6001 \
    --sip-user "$KOHA_SIP_USER" --sip-pass "$KOHA_SIP_PASS" \
    --card-reader OMNIKEY --book-reader ACR1252 --gate-reader Gate
```

Open the kiosk at 👉 **`http://localhost:8000`**

---

## 🔧 Configuration Reference

Every setting is environment-overridable (see `kiosk/backend/config.py`).

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `KOHA_SIP_HOST` | `127.0.0.1` | SIP2 server host |
| `KOHA_SIP_PORT` | `6001` | SIP2 server port |
| `KOHA_SIP_USER` / `KOHA_SIP_PASS` | *(empty)* | SIP2 service account — **must be supplied** |
| `KOHA_SIP_LOCATION` | `NFSUGNR` | SIP2 login location (`CP`) |
| `KOHA_INSTITUTION_ID` | `NFSUGNR` | Institution (`AO`) |
| `KOHA_TERMINAL_PASSWORD` | *(empty)* | Optional SIP2 terminal password (`AC`) |
| `KOHA_MAX_BOOKS` | `2` | Borrowing limit enforced by the kiosk |
| `KIOSK_CARD_READER` | *(auto)* | Substring match for the ISO 14443A card reader |
| `KIOSK_BOOK_READER` | *(auto)* | Substring match for the ISO 15693 book pad |
| `KIOSK_GATE_READER` | *(auto)* | Substring match for the exit-gate antenna |
| `KIOSK_POLL_INTERVAL` | `0.4` | Reader polling interval (s) |
| `KIOSK_GATE_COOLDOWN` | `4.0` | Seconds between gate reads |
| `KIOSK_ISO15693_CRC` | `1` | Append the ISO 15693 CRC in transparent mode |
| `KIOSK_HARDWARE_MAP` | `kiosk/backend/hardware_map.json` | UID → Koha map file |
| `KIOSK_LIVENESS_TIMEOUT` | `25` | Liveness challenge validity window (s) |

---

## 🧪 Running Automated Tests

```bash
python tests/test_koha_kiosk.py
```

The suite covers the SIP2 protocol engine, the SIP2 client transport (against a
throw-away in-test stub socket — **not** a shipped emulator), PC/SC reader role
resolution, the ISO 15693 CRC, the hardware-map helpers and the liveness
validation rules.

```
  [PASS] SIP2 checksum
  [PASS] SIP2 builder shapes
  [PASS] SIP2 patron info parser
  [PASS] SIP2 checkout parser
  [PASS] PC/SC reader role resolution
  [PASS] ISO 15693 CRC
  [PASS] Liveness validation
  [PASS] SIP2 client transport
  [PASS] Server routes

============================================================
 ALL TESTS PASSED
============================================================
```

---

## 🩺 Diagnostics

| Tool / endpoint | Purpose |
| :--- | :--- |
| `python diagnose_hardware.py` | Lists PC/SC readers, reads a card UID, inventories an ISO 15693 tag, lists COM ports |
| `GET /api/health` | Aggregate Koha + hardware health |
| `GET /api/hardware/status` | pyscard availability, reader role assignment, map counts |
| `GET /api/hardware/pad-state` | Live book-pad / card-zone / gate-zone snapshot |
| `GET /api/sip2/telemetry` | Current SIP2 connection telemetry |
| SIP2 drawer in the UI | Packet builders + raw socket terminal |

---

## ⚙️ Koha 26 Least-Privilege `SIPconfig.xml`

The kiosk service account should be restricted to circulation only
(`superlibrarian = false`):

```xml
<!-- Koha 26 SIPconfig.xml - NFSU Central Library Kiosk integration -->
<server-params>
    <institution id="NFSUGNR" implementation="Koha">
        <policy checkin="true" checkout="true" renewal="true" status="true" />
        <user id="YOUR_SIP2_ACCOUNT" password="YOUR_SIP2_PASSWORD">
            <!-- Least-privilege: circulate permissions only -->
            <permissions circulate="true" parameters="false" superlibrarian="false" tools="false" />
        </user>
    </institution>
    <service host="0.0.0.0" port="6001" transport="tcp" max-clients="20" timeout="30" />
</server-params>
```

Supply the real account/password through the environment as shown above — do not
commit them to the repository.

---

## 🛡️ Security & Privacy

- **No credential defaults.** SIP2 logical credentials default to empty and must be
  provided through the environment or launch flags.
- **No simulation.** There is no emulator module and no fake-data endpoint; deleted
  paths such as `/api/emulator/reset`, `/api/sip2/transactions`,
  `/api/hardware/tap-card`, `/api/hardware/place-book`, `/api/hardware/pass-gate`
  and `/api/hardware/write-afi` are asserted absent by the test suite.
- **Zero biometric retention.** Camera frames are analysed in the browser; only
  anonymous motion metrics and a one-time nonce are sent, and the server discards
  the session on use.

---

## 🏛️ Institutional Attribution

Developed for the **National Forensic Sciences University (NFSU), Gandhinagar-382007,
Gujarat-India**.
An Institution of National Importance (Ministry of Home Affairs, Government of India).
Central Library Automation & Koha 26 ILMS Integration.
