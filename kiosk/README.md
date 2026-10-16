# NFSU Central Library Self-Service Kiosk Integrated with Koha 26 ILMS (PS-2)
### National Forensic Sciences University (राष्ट्रीय न्यायालयिक विज्ञान विश्वविद्यालय)
*(An Institution of National Importance under Ministry of Home Affairs, Government of India)*

[![Koha Status](https://img.shields.io/badge/KOHA%2026-LIVE%20CONNECTED-emerald?style=for-the-badge&logo=apache)](http://117.239.182.15:6001)
[![Kiosk UI](https://img.shields.io/badge/Kiosk%20Portal-http%3A%2F%2Flocalhost%3A8000-002147?style=for-the-badge)](http://localhost:8000)
[![SIP2 Protocol](https://img.shields.io/badge/Protocol-3M%20SIP2%20v2.00-d97706?style=for-the-badge)](#sip2-protocol-engine)
[![Security Gate](https://img.shields.io/badge/Security%20Gate-AFI%200x07%20%7C%200xC2-red?style=for-the-badge)](#rfid-security-gate--buzzer)

---

## 🚀 Live Connection Architecture

| Parameter | Live Competition Value | Built-In Standby Emulator |
| :--- | :--- | :--- |
| **Server Host** | `117.239.182.15` | `127.0.0.1` |
| **SIP2 Port** | `6001` | `6001` |
| **Institution ID (`AO`)** | `NFSUGNR` | `NFSUGNR` |
| **Primary Account** | `rfid` / `Rfid@123` | `rfid` / `Rfid@123` |
| **Secondary Account** | `rfid1` / `Rfid1@123` | `rfid1` / `Rfid1@123` |
| **Faculty Account** | `rfid2` / `Rfid2@123` | `rfid2` / `Rfid2@123` |
| **Privilege Scope** | `circulate ONLY` (Least-Privilege) | `circulate ONLY` |
| **Protocol Checksum** | 16-bit Two's-Complement (`AZ`) | 16-bit Two's-Complement (`AZ`) |

---

## 🏆 Key PS-2 Judge Requirements Implemented

### 1. Zero Generic UI — Scraped Directly from `nfsu.ac.in`
- Scraped and mirrored `bundle.css` (674 KB) and `bundle.js` (234 KB) directly from `https://www.nfsu.ac.in/`.
- Official NFSU Emblem (`assets/img/NFSU_logo.png`), favicon, institutional Navy (`#002147`), and Gold (`#ddb55e` / `#d97706`).
- Top utility strip with Ministry of Home Affairs badge, email, phone, and live **`KOHA 26 CONNECTED`** telemetry pill.

### 2. Dual-Zone Self-Check Mat & Multi-Tag Anti-Collision
- **Top Large Zone**: Avery Dennison Smartrac RaceTrack 13.56 MHz HF (ISO 15693 / NXP ICODE SLIX2).
  - Handles **2 books simultaneously on the pad** with anti-collision inventory resolution.
- **Bottom-Right Compact Zone**: HID OMNIKEY Contactless MIFARE Reader (ISO 14443A) with concentric RFID radar wave animations.

### 3. Strict 2-Books-At-A-Time Circulation Limit
- Enforces `MAX_BOOKS_ALLOWED = 2`.
- Queries SIP2 `63` with summary position 3 = `Y` to parse Koha `64` charged items count and `AU` barcodes.
- If patron already has 1 book issued and places 2 books on the pad (or has 2 books issued), excess checkout is strictly blocked with a clear warning modal.

### 4. RFID Security Gate & Audible Siren (Web Audio API)
- Tag Armed (`0x07`, EAS On): In-library / on-shelf books trigger a loud alternating 850Hz/1150Hz hardware gate siren + flashing crimson strobe alert banner.
- Tag Disarmed (`0xC2`, EAS Off): Properly issued books pass with a soft major triad chime.
- Strict **Two-Phase Commit**: AFI byte is written to `0xC2` only AFTER Koha returns `121` (`OK=1`). During check-in, rewritten to `0x07` immediately upon `101`.

### 5. AI Facial Recognition with Liveness Challenge
- Live WebRTC camera viewport framed in NFSU gold.
- Dynamic interactive challenge: *"Please blink once and turn slightly left"* verified before ephemeral matching.
- **Zero Biometric Retention**: Processed in volatile RAM and purged immediately.

### 6. Built-In SIP2 Testing Tool & Diagnostics Drawer
- 1-Click tests for all message pairs: `99/98`, `93/94`, `63/64`, `17/18`, `11/12`, `09/10`, `29/30`.
- Raw ASCII packet inspector showing `AY` sequence and `AZ` checksum validation.
- Live Koha connection switcher (117.239.182.15 <-> 127.0.0.1).

---

## ⚡ Quick Start Commands

```bash
# Launch Kiosk (Connected to Live Koha 26 at 117.239.182.15:6001)
python run_kiosk.py --port 8000 --sip-host 117.239.182.15 --sip-port 6001

# Open in Browser
http://localhost:8000

# Run All Verification Tests
python tests/test_koha_kiosk.py
```
