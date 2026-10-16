"""
NFSU Central Library Self-Service Kiosk - RFID & Smart Card Hardware Bridge
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Controls:
1. Top Large Zone: Avery Dennison Smartrac RaceTrack 13.56 MHz HF (ISO 15693 / NXP ICODE SLIX2)
   - Multi-tag Anti-Collision (2 Books Simultaneously on Pad)
   - AFI Security Byte Read/Write (0x07 Armed / 0xC2 Disarmed)
2. Bottom-Right Compact Zone: HID OMNIKEY MIFARE Contactless Reader (ISO 14443A)
   - Patron ID Card Tap
3. Library Exit Security Gate Reader Zone
   - Pass-through detection triggering Web Audio API hardware siren if AFI == 0x07
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from .config import settings
from .sip2_emulator import emulator

class RFIDHardwareBridge:
    """Manages Dual-Zone Self-Check Station Pad, Card Reader, and Gate Sensors"""
    
    def __init__(self):
        # Current Physical / Simulated State
        self.books_on_pad: List[Dict[str, Any]] = []
        self.patron_card_on_pad: Optional[Dict[str, Any]] = None
        self.gate_event: Optional[Dict[str, Any]] = None
        
        self.listeners: List[Callable] = []
        self.physical_reader_active = False
        self._lock = asyncio.Lock()

    def add_listener(self, cb: Callable):
        self.listeners.append(cb)

    async def _broadcast(self, event_type: str, data: Dict[str, Any]):
        payload = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        for cb in self.listeners:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception:
                pass

    def get_pad_state(self) -> Dict[str, Any]:
        """Returns full snapshot of both zones on the physical mat"""
        return {
            "books_zone": {
                "count": len(self.books_on_pad),
                "books": self.books_on_pad,
                "multi_collision_resolved": len(self.books_on_pad) > 1,
                "max_allowed_on_pad": 2
            },
            "card_zone": {
                "card_present": self.patron_card_on_pad is not None,
                "patron": self.patron_card_on_pad
            },
            "gate_zone": self.gate_event
        }

    # Zone 1: Books Pad Actions (Smartrac RaceTrack ISO 15693)
    async def place_book(self, barcode_or_uid: str) -> Dict[str, Any]:
        """Place a single book on the HF RFID pad"""
        async with self._lock:
            book = emulator.find_book_by_barcode_or_tag(barcode_or_uid)
            if not book:
                # Dynamically register unlisted scanned physical book
                book = {
                    "barcode": barcode_or_uid,
                    "tag_uid": f"E00401{abs(hash(barcode_or_uid)) % 100000000000:012d}",
                    "title": f"Forensic Sciences Textbook ({barcode_or_uid})",
                    "author": "NFSU Library Collection",
                    "call_number": "FS-LIB-2026",
                    "status": "available",
                    "afi": settings.AFI_ARMED,
                    "eas": True,
                    "chip": "Smartrac RaceTrack ISO 15693"
                }
                emulator.books[barcode_or_uid] = book

            # Avoid duplicate on pad
            existing = [b for b in self.books_on_pad if b["barcode"] == book["barcode"]]
            if existing:
                return {"success": True, "message": "Book already on pad", "state": self.get_pad_state()}

            if len(self.books_on_pad) >= 2:
                return {
                    "success": False,
                    "error": "Dual-zone pad capacity reached (Maximum 2 books at a time)",
                    "state": self.get_pad_state()
                }

            book_entry = {
                "barcode": book["barcode"],
                "tag_uid": book["tag_uid"],
                "title": book["title"],
                "author": book["author"],
                "call_number": book["call_number"],
                "status": book["status"],
                "afi": book["afi"],
                "eas": book["eas"],
                "due_date": book.get("due_date"),
                "detected_at": datetime.now().isoformat()
            }
            self.books_on_pad.append(book_entry)
            await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())
            return {"success": True, "book": book_entry, "state": self.get_pad_state()}

    async def place_two_books(self, barcode1: str = "NFSU-BK-104", barcode2: str = "NFSU-BK-105") -> Dict[str, Any]:
        """Simulate placing 2 books simultaneously on the pad (ISO 15693 Anti-collision)"""
        async with self._lock:
            self.books_on_pad.clear()
            for bc in [barcode1, barcode2]:
                book = emulator.find_book_by_barcode_or_tag(bc)
                if not book:
                    book = {
                        "barcode": bc,
                        "tag_uid": f"E00401{abs(hash(bc)) % 100000000000:012d}",
                        "title": f"Forensic Sciences Textbook ({bc})",
                        "author": "NFSU Library Collection",
                        "call_number": "FS-LIB-2026",
                        "status": "available",
                        "afi": settings.AFI_ARMED,
                        "eas": True,
                        "chip": "Smartrac RaceTrack ISO 15693"
                    }
                    emulator.books[bc] = book
                self.books_on_pad.append({
                    "barcode": book["barcode"],
                    "tag_uid": book["tag_uid"],
                    "title": book["title"],
                    "author": book["author"],
                    "call_number": book["call_number"],
                    "status": book["status"],
                    "afi": book["afi"],
                    "eas": book["eas"],
                    "due_date": book.get("due_date"),
                    "detected_at": datetime.now().isoformat()
                })
            await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())
            return {"success": True, "count": len(self.books_on_pad), "state": self.get_pad_state()}

    async def remove_books(self) -> Dict[str, Any]:
        """Clear book pad"""
        async with self._lock:
            self.books_on_pad.clear()
            await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())
            return {"success": True, "state": self.get_pad_state()}

    # Zone 2: Patron Card Zone (HID OMNIKEY MIFARE Reader)
    async def tap_patron_card(self, card_or_uid: str) -> Dict[str, Any]:
        """Tap patron MIFARE card or scan barcode"""
        async with self._lock:
            patron = emulator.find_patron_by_card_or_uid(card_or_uid)
            if not patron:
                # Dynamically register unlisted patron card / barcode
                patron = {
                    "card_number": card_or_uid,
                    "mifare_uid": f"04:{abs(hash(card_or_uid)) % 256:02X}:{abs(hash(card_or_uid) >> 8) % 256:02X}:1A",
                    "name": f"NFSU Patron ({card_or_uid})",
                    "role": "Forensic Sciences Student",
                    "status": "active",
                    "charged_items": []
                }
                emulator.patrons[card_or_uid] = patron

            self.patron_card_on_pad = {
                "card_number": patron["card_number"],
                "mifare_uid": patron["mifare_uid"],
                "name": patron["name"],
                "role": patron["role"],
                "status": patron["status"],
                "charged_items": patron["charged_items"],
                "charged_count": len(patron["charged_items"]),
                "tapped_at": datetime.now().isoformat()
            }
            await self._broadcast("PATRON_CARD_TAPPED", self.get_pad_state())
            return {"success": True, "patron": self.patron_card_on_pad, "state": self.get_pad_state()}

    async def remove_patron_card(self) -> Dict[str, Any]:
        """Remove patron card from reader zone"""
        async with self._lock:
            self.patron_card_on_pad = None
            await self._broadcast("PATRON_CARD_REMOVED", self.get_pad_state())
            return {"success": True, "state": self.get_pad_state()}

    # Two-Phase Commit AFI Security Byte Write
    async def write_book_afi(self, barcode: str, new_afi: str) -> Dict[str, Any]:
        """
        Hardware AFI write:
        - During Issue: 0x07 -> 0xC2 (Disarmed) AFTER Koha responds with 121 (OK=1).
        - During Return: 0xC2 -> 0x07 (Armed) immediately after Koha responds with 101.
        """
        async with self._lock:
            book = emulator.find_book_by_barcode_or_tag(barcode)
            if not book:
                return {"success": False, "error": "Book not found"}

            old_afi = book["afi"]
            book["afi"] = new_afi
            book["eas"] = (new_afi == settings.AFI_ARMED)

            # Update book in books_on_pad list if present
            for b in self.books_on_pad:
                if b["barcode"] == book["barcode"]:
                    b["afi"] = new_afi
                    b["eas"] = book["eas"]

            event_data = {
                "barcode": book["barcode"],
                "title": book["title"],
                "old_afi": old_afi,
                "new_afi": new_afi,
                "state": "ARMED (EAS ON)" if new_afi == settings.AFI_ARMED else "DISARMED (EAS OFF)",
                "timestamp": datetime.now().isoformat()
            }
            await self._broadcast("AFI_STATE_CHANGED", event_data)
            return {"success": True, "data": event_data}

    # Zone 3: Exit Security Gate Simulator
    async def pass_book_through_gate(self, barcode_or_uid: str) -> Dict[str, Any]:
        """
        Simulates an RFID tag passing through the library exit security gate antennas.
        If AFI == 0x07: Triggers gate buzzer hardware siren!
        If AFI == 0xC2: Gate clear chime.
        """
        book = emulator.find_book_by_barcode_or_tag(barcode_or_uid)
        if not book:
            return {"success": False, "error": "Unknown tag at gate"}

        is_alarm = (book["afi"] == settings.AFI_ARMED)
        gate_result = {
            "barcode": book["barcode"],
            "title": book["title"],
            "afi": book["afi"],
            "alarm": is_alarm,
            "status_text": (
                "SECURITY GATE ALARM TRIGGERED — UNISSUED BOOK DETECTED [AFI: 0x07 ARMED]"
                if is_alarm else
                "GATE CLEAR — VERIFIED KOHA ISSUE [AFI: 0xC2 DISARMED]"
            ),
            "timestamp": datetime.now().isoformat()
        }
        self.gate_event = gate_result
        await self._broadcast("GATE_WALKTHROUGH", gate_result)
        return gate_result

# Singleton instance
rfid_bridge = RFIDHardwareBridge()
