# National Forensic Sciences University (NFSU), Gandhinagar
## Central Library Self-Service Kiosk & SIP2 Diagnostic Suite
**Integrated with Koha 26 ILMS — Problem Statement 2 (PS-2)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Koha 26 SIP2](https://img.shields.io/badge/Koha_26-SIP2_v2.00-orange.svg)](https://koha-community.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests Passing](https://img.shields.io/badge/Tests-100%25_Passing-brightgreen.svg)](tests/test_koha_kiosk.py)

---

## 🏛️ Executive Summary

This repository contains the complete, hardware-ready **Self-Service Library Kiosk & SIP2 Diagnostic Suite** engineered specifically for the **National Forensic Sciences University (NFSU), Gandhinagar**, integrated directly with the live competition **Koha 26 Integrated Library Management System (ILMS)** (`117.239.182.15:6001`, Institution: `NFSUGNR`).

The interface replicates the live institutional design language of `https://www.nfsu.ac.in/` featuring the official emblem, Ministry of Home Affairs banner, campus facade background, and **3 giant touch action tiles**: **`[ ISSUE ]`**, **`[ RETURN ]`**, and **`[ RENEW ]`**.

---

## 📸 Presentation Kiosk Interface

```
+---------------------------------------------------------------------------------------------------+
|  [Tricolor Strip]                                                                                  |
|  info@nfsu.ac.in | (079) 239 77100 | An Institution of National Importance | [KOHA 26 LIVE (137 ms)]|
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
|      [1-Click Live Patrons]: [ rfid (0/2) ]  [ rfid1 (1/2) ]  [ rfid2 (2/2) ]  [ Face Liveness ]   |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|  Gandhinagar-382007, Gujarat | Connected to Koha 26 ILMS | Host: 117.239.182.15:6001 | Inst: NFSUGNR|
+---------------------------------------------------------------------------------------------------+
```

---

## ⚡ Core Architecture & Engineering Highlights

```
+---------------------------------------------------------------------------------------------+
|                                    TOUCH KIOSK WEB UI                                       |
|  React/Vanilla JS + Scraped NFSU Theme + Web Audio Siren + WebRTC Liveness + SIP Console   |
+---------------------------------------------------------------------------------------------+
                                       |              ^
             REST / WebSocket (/ws)   |              |  Real-Time State Broadcasts
                                       v              |
+---------------------------------------------------------------------------------------------+
|                                   FASTAPI KIOSK BACKEND                                     |
|  - Circulation Orchestrator (Issue, Return, Renewal, Receipts)                              |
|  - Strict 2-Books-At-A-Time Policy Engine (MAX_BOOKS = 2)                                   |
|  - Dual-Zone RFID & OMNIKEY Bridge (Two-Phase Commit AFI Security)                          |
|  - In-RAM Ephemeral Biometric Liveness Engine (Zero Disk Retention)                         |
+---------------------------------------------------------------------------------------------+
               |                                              |
               v                                              v
+-----------------------------+               +-------------------------------+
|      SIP2 CLIENT ENGINE     |               |    BUILT-IN KOHA 26 EMULATOR  |
|  - Async TCP (Socket)       |  (Fallback)   |  - Hot-Standby on :6001       |
|  - AY Seq + AZ Checksum     | ------------> |  - Preloaded NFSU Patrons     |
|  - Auto-Reconnect & Latency |               |  - Full SIP2 Protocol Stack   |
+-----------------------------+               +-------------------------------+
               |
               | TCP (Port 6001)
               v
+-------------------------------------------------------------+
|                 LIVE KOHA 26 ILMS SERVER                    |
|      117.239.182.15:6001 (Institution: NFSUGNR)             |
|  Accounts: rfid (0/2), rfid1 (1/2), rfid2 (2/2 - Full)      |
+-------------------------------------------------------------+
```

---

## 🏆 PS-2 Expected Outcomes Checklist

| Feature | PS-2 Judge Requirement | Implementation Detail | Status |
| :--- | :--- | :--- | :--- |
| **A. Core Circulation** | Issue (`11 -> 12`), Return (`09 -> 10`), Renew (`29 -> 30`) | Full asynchronous TCP SIP2 engine verifying Koha `OK=1` flags before updating RFID security bytes. | ✅ Complete |
| **B. 3-Way Authentication** | MIFARE Card, Barcode Scanner, AI Facial Recognition | Integrated into Self-Check Station: MIFARE tap zone, USB keyboard-wedge barcode auto-capture, WebRTC blink/head-turn challenge. | ✅ Complete |
| **C. 2-Books Limit Rule** | Strict limit of 2 books at a time per patron | Parses Koha `64` bytes 45:49 and `AU` barcodes. If patron has 1 book and places 2 on pad, blocks checkout with alert banner. | ✅ Complete |
| **D. Issued Books Counter** | Live metric showing `Books Currently Issued: X / 2` | Prominently rendered at the top of the patron dashboard with dynamic status ring (Green = 0, Amber = 1, Red = 2). | ✅ Complete |
| **E. Dual-Zone Mat** | Large Book Zone + Bottom-Right Patron Card Zone | Replicates physical lab mat with Avery Dennison Smartrac HF (ISO 15693) and HID OMNIKEY MIFARE (ISO 14443A). | ✅ Complete |
| **F. Multi-Tag Anti-Collision** | Place 2 books simultaneously on the pad | Concurrently resolves two Avery Dennison Smartrac RaceTrack ICODE SLIX2 tags on the pad with 1-click test control. | ✅ Complete |
| **G. Security Gate & Siren** | Web Audio API buzzer for unissued books | Armed tags (`AFI: 0x07`) trigger alternating 850/1150Hz loud siren. Disarmed tags (`AFI: 0xC2`) pass clear with harmonic chime. | ✅ Complete |
| **H. Zero-Retention Biometrics** | RAM-only ephemeral facial processing | Blink + head-pose challenge-response. All embeddings purged from volatile RAM immediately upon authentication. | ✅ Complete |
| **I. Printable Receipts** | Official NFSU Circulation Receipts | Displays transaction timestamp, patron details, book barcode, due date, AFI tag security state, and print button. | ✅ Complete |
| **J. SIP Testing Tool** | Built-in diagnostics console | Slide-out drawer with 1-click test packets, raw socket terminal, round-trip latency, and 16-bit 2's complement checksum parser. | ✅ Complete |

---

## 🚀 Quickstart & Single-Command Launch

### 1. Prerequisites
- Python 3.10 or higher
- Modern Web Browser (Chrome, Edge, Firefox)

### 2. Installation
```bash
git clone https://github.com/prnjlksingh/nfsu-library-kiosk.git
cd nfsu-library-kiosk
pip install -r requirements.txt
```

### 3. Launching the Kiosk
```bash
python run_kiosk.py --port 8000 --sip-host 117.239.182.15 --sip-port 6001
```

Access the kiosk in your browser at:
👉 **`http://localhost:8000`**

---

## 🧪 Running Automated Tests

Run the integration test suite covering SIP2 protocol correctness, Koha 26 handshake, 2-book limit rule, two-phase commit AFI transitions, and zero-retention biometrics:

```bash
python tests/test_koha_kiosk.py
```

**Output:**
```
Running test_sip2_protocol_checksum()...
  [PASS] SIP2 Checksum and Sequence calculation verified.
Running test_koha_emulator_circulation_and_quota()...
  [PASS] Koha 26 Handshake, Login, 63/64 AU parser, and 2-book limit verified.
Running test_two_phase_commit_and_gate_buzzer()...
  [PASS] 2-Phase Commit AFI 0x07/0xC2 transitions and Gate Buzzer verified.
Running test_biometric_liveness_challenge()...
  [PASS] Ephemeral in-RAM liveness detection and zero-retention verified.

============================================================
 ALL 4 PS-2 CORE TEST SUITES PASSED FLAWLESSLY (100% SUCCESS)
============================================================
```

---

## ⚙️ Koha 26 Least-Privilege `SIPconfig.xml`

Under NFSU institutional security guidelines, the kiosk service account is strictly restricted to circulation permissions only (`superlibrarian = false`):

```xml
<!-- Koha 26 SIPconfig.xml - NFSU Central Library Kiosk Integration -->
<server-params>
    <institution id="NFSUGNR" implementation="Koha">
        <policy checkin="true" checkout="true" renewal="true" status="true" />
        <user id="rfid" password="Rfid@123">
            <!-- Least-Privilege Koha Security Group: circulate_remaining_permissions ONLY -->
            <permissions circulate="true" parameters="false" superlibrarian="false" tools="false" />
        </user>
    </institution>
    <service host="0.0.0.0" port="6001" transport="tcp" max-clients="20" timeout="30" />
</server-params>
```

---

## 🏛️ Institutional Attribution

Developed for the **National Forensic Sciences University (NFSU), Gandhinagar-382007, Gujarat-India**.
An Institution of National Importance (Ministry of Home Affairs, Government of India).
Central Library Automation & Koha 26 ILMS Integration.
