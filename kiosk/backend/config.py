"""
NFSU Central Library Self-Service Kiosk - Configuration Module
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

All values are environment-overridable so the kiosk can be deployed on the
real circulation desk without editing code.
"""

import os
from typing import Dict, List
from pydantic import BaseModel


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class KohaConfig(BaseModel):
    """Live Koha 26 SIP2 connection settings."""

    sip_host: str = _env_str("KOHA_SIP_HOST", "127.0.0.1")
    sip_port: int = _env_int("KOHA_SIP_PORT", 6001)
    sip_user: str = _env_str("KOHA_SIP_USER", "")
    sip_pass: str = _env_str("KOHA_SIP_PASS", "")
    sip_location: str = _env_str("KOHA_SIP_LOCATION", "NFSUGNR")
    institution_id: str = _env_str("KOHA_INSTITUTION_ID", "NFSUGNR")
    terminal_password: str = _env_str("KOHA_TERMINAL_PASSWORD", "")

    # Timeout and retry parameters
    timeout_seconds: float = _env_float("KOHA_SIP_TIMEOUT", 5.0)
    max_retries: int = _env_int("KOHA_SIP_MAX_RETRIES", 2)
    reconnect_delay_seconds: float = _env_float("KOHA_RECONNECT_DELAY", 5.0)

    # Circulation policy
    max_books_allowed: int = _env_int("KOHA_MAX_BOOKS", 2)


class HardwareConfig(BaseModel):
    """
    PC/SC contactless reader configuration.

    Reader roles are selected by case-insensitive substring match against the
    PC/SC reader name reported by the operating system. Run
    ``python diagnose_hardware.py`` to list the exact names available on the
    kiosk.
    """

    # ISO 14443A patron MIFARE reader (HID OMNIKEY / ACR1252 etc.)
    card_reader_match: str = _env_str("KIOSK_CARD_READER", "")

    # ISO 15693 book pad reader (Avery Dennison Smartrac / ICODE SLIX2)
    book_reader_match: str = _env_str("KIOSK_BOOK_READER", "")

    # Exit security gate antenna reader
    gate_reader_match: str = _env_str("KIOSK_GATE_READER", "")

    # Polling / debounce tuning
    poll_interval_seconds: float = _env_float("KIOSK_POLL_INTERVAL", 0.4)
    removal_debounce_polls: int = _env_int("KIOSK_REMOVAL_DEBOUNCE", 3)
    gate_cooldown_seconds: float = _env_float("KIOSK_GATE_COOLDOWN", 4.0)
    gate_alarm_auto_silence_seconds: float = _env_float("KIOSK_GATE_SILENCE", 8.0)

    # ISO 15693 transparent-mode behaviour (reader specific)
    iso15693_append_crc: bool = _env_str("KIOSK_ISO15693_CRC", "1") != "0"

    # Optional serial / USB-serial barcode scanner (most scanners are HID
    # keyboard-wedge devices and need no backend configuration at all).
    serial_barcode_port: str = _env_str("KIOSK_SERIAL_BARCODE_PORT", "")
    serial_barcode_baud: int = _env_int("KIOSK_SERIAL_BARCODE_BAUD", 9600)

    # Tag UID -> account mapping table (see kiosk/backend/hardware_map.json)
    hardware_map_file: str = _env_str("KIOSK_HARDWARE_MAP", "")

    # WebSocket telemetry broadcast interval
    telemetry_interval_seconds: float = _env_float("KIOSK_TELEMETRY_INTERVAL", 20.0)


class KioskSettings:
    """Institutional branding and RFID security parameters."""

    APP_NAME: str = "NFSU Central Library Self-Service Kiosk"
    INSTITUTION_NAME: str = "National Forensic Sciences University"
    CAMPUS: str = "Gandhinagar (HQ)"
    TAGLINE: str = "The World's First and Only University Dedicated to Forensic & Allied Sciences"
    SUBTAG: str = "An Institution of National Importance (Ministry of Home Affairs, Government of India)"

    # AFI (Application Family Identifier) RFID tag security states
    # (ISO 28560 / NXP ICODE SLIX2)
    AFI_ARMED: str = "0x07"     # In-library / on-shelf -> triggers exit gate alarm
    AFI_DISARMED: str = "0xC2"  # Checked-out / issued -> passes exit gate clear

    # Biometric liveness
    LIVENESS_CHALLENGE_TIMEOUT: int = _env_int("KIOSK_LIVENESS_TIMEOUT", 25)

    # Zero-retention privacy mandate: nothing biometric is ever written to disk.
    ZERO_RETENTION_RAM_ONLY: bool = True


config = KohaConfig()
hardware = HardwareConfig()
settings = KioskSettings()


def _default_map_path() -> str:
    if hardware.hardware_map_file:
        return os.path.abspath(hardware.hardware_map_file)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "hardware_map.json"))


# Resolved once at import; the bridge reloads it on demand.
HARDWARE_MAP_PATH: str = _default_map_path()


# Reader role labels used by the UI/telemetry
READER_ROLE_CARD: str = "card"
READER_ROLE_BOOK: str = "book"
READER_ROLE_GATE: str = "gate"

READER_ROLES: List[str] = [READER_ROLE_CARD, READER_ROLE_BOOK, READER_ROLE_GATE]
