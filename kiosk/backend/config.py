"""
NFSU Central Library Self-Service Kiosk - Configuration Module
National Forensic Sciences University, Gandhinagar
Integrated with LIVE Koha 26 ILMS (PS-2)
"""

import os
from pydantic import BaseModel
from typing import Optional, Dict

class KohaConfig(BaseModel):
    # LIVE Koha 26 Server Connection Settings (PS-2 Competition Server)
    sip_host: str = os.getenv("KOHA_SIP_HOST", "117.239.182.15")
    sip_port: int = int(os.getenv("KOHA_SIP_PORT", "6001"))
    sip_user: str = os.getenv("KOHA_SIP_USER", "rfid1")
    sip_pass: str = os.getenv("KOHA_SIP_PASS", "Rfid1@123")
    sip_location: str = os.getenv("KOHA_SIP_LOCATION", "NFSUGNR")
    institution_id: str = os.getenv("KOHA_INSTITUTION_ID", "NFSUGNR")
    terminal_password: str = os.getenv("KOHA_TERMINAL_PASSWORD", "")
    
    # Available Live Service Accounts (from competition projector screen)
    available_accounts: Dict[str, str] = {
        "rfid": "Rfid@123",
        "rfid1": "Rfid1@123",
        "rfid2": "Rfid2@123"
    }

    # Security & Least-Privilege Policy:
    # Service account MUST have ONLY circulate permissions, NEVER superlibrarian
    required_permission: str = "circulate"
    superlibrarian_allowed: bool = False
    
    # Timeout and retry parameters
    timeout_seconds: float = float(os.getenv("KOHA_SIP_TIMEOUT", "5.0"))
    max_retries: int = 3
    
    # Circulation Rules
    max_books_allowed: int = 2  # Strict 2 books at a time limit per patron

class KioskSettings:
    APP_NAME: str = "NFSU Central Library Self-Service Kiosk"
    INSTITUTION_NAME: str = "National Forensic Sciences University"
    CAMPUS: str = "Gandhinagar (HQ)"
    TAGLINE: str = "The World's First and Only University Dedicated to Forensic & Allied Sciences"
    SUBTAG: str = "An Institution of National Importance (Ministry of Home Affairs, Government of India)"
    
    # AFI (Application Family Identifier) RFID Tag Security States (ISO 28560 / NXP ICODE SLIX2)
    AFI_ARMED: str = "0x07"     # In-Library / On-Shelf -> Triggers Exit Gate Buzzer
    AFI_DISARMED: str = "0xC2"  # Checked-Out / Issued -> Passes Exit Gate Clear
    
    # Biometric Liveness Settings
    LIVENESS_CHALLENGE_TIMEOUT: int = 15  # seconds
    ZERO_RETENTION_RAM_ONLY: bool = True  # Strict privacy mandate

config = KohaConfig()
settings = KioskSettings()
