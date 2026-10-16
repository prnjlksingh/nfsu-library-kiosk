"""
NFSU Central Library Self-Service Kiosk - RFID & Smart Card Hardware Bridge
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Drives the three physical zones of the self-check station through real PC/SC
readers (see :mod:`kiosk.backend.pcsc_reader`):

1. **Book pad** - ISO 15693 HF reader (Avery Dennison Smartrac / ICODE SLIX2).
   Multi-tag inventory so two books can sit on the pad at once, plus AFI
   security-byte read/write (0x07 armed / 0xC2 disarmed).
2. **Patron card** - ISO 14443A MIFARE reader (HID OMNIKEY / ACR1252). Card
   UIDs are mapped to Koha accounts through ``hardware_map.json``.
3. **Exit gate** - ISO 15693 antenna reader. A tag leaving with an armed AFI
   raises the alarm.

Every value surfaced here comes from real hardware or the live Koha SIP2
server.  There is no simulated pad, no fake patron data and no auto-registered
demo tags.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from .config import (
    config,
    hardware,
    settings,
    HARDWARE_MAP_PATH,
    READER_ROLE_BOOK,
    READER_ROLE_CARD,
    READER_ROLE_GATE,
)
from .pcsc_reader import (
    PCSCReader,
    PCSCReaderError,
    PYSCARD_AVAILABLE,
    PYSCARD_IMPORT_ERROR,
    list_readers,
    resolve_reader_roles,
)


class RFIDHardwareBridge:
    """Manages the book pad, patron card reader and exit gate."""

    def __init__(self):
        self.readers: Dict[str, Optional[str]] = {"card": None, "book": None, "gate": None}
        self._readers: Dict[str, Optional[PCSCReader]] = {"card": None, "book": None, "gate": None}

        self.books_on_pad: List[Dict[str, Any]] = []
        self.scanned_books: List[Dict[str, Any]] = []
        self.patron_card_on_pad: Optional[Dict[str, Any]] = None
        self.gate_event: Optional[Dict[str, Any]] = None

        self.listeners: List[Callable] = []
        self.hardware_map: Dict[str, Dict[str, str]] = {"patron_cards": {}, "book_tags": {}}

        self.reader_status: Dict[str, Dict[str, Any]] = {
            "card": {"name": None, "role": READER_ROLE_CARD, "present": False, "error": None},
            "book": {"name": None, "role": READER_ROLE_BOOK, "present": False, "error": None},
            "gate": {"name": None, "role": READER_ROLE_GATE, "present": False, "error": None},
        }
        self.last_error: Optional[str] = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

        # Debounce / edge-detection state
        self._card_uid: Optional[str] = None
        self._card_missing = 0
        self._book_seen: Dict[str, int] = {}
        self._gate_cooldown_until = 0.0

        self._load_hardware_map()
        self.refresh_readers()

    # ------------------------------------------------------------------
    # Mapping table
    # ------------------------------------------------------------------
    def _load_hardware_map(self) -> None:
        path = HARDWARE_MAP_PATH
        data: Dict[str, Any] = {"patron_cards": {}, "book_tags": {}}
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    for key in ("patron_cards", "book_tags"):
                        block = loaded.get(key)
                        if isinstance(block, dict):
                            data[key] = {
                                str(k).strip().upper(): str(v).strip()
                                for k, v in block.items()
                            }
        except Exception as exc:  # pragma: no cover - config error surfaced in status
            self.last_error = f"Failed to load hardware map '{path}': {exc}"
        self.hardware_map = data

    def reload_hardware_map(self) -> Dict[str, Any]:
        self._load_hardware_map()
        return self.get_hardware_status()

    def resolve_patron_id(self, card_uid: str) -> Optional[str]:
        return self.hardware_map.get("patron_cards", {}).get(card_uid.strip().upper())

    def resolve_book_barcode(self, tag_uid: str) -> Optional[str]:
        return self.hardware_map.get("book_tags", {}).get(tag_uid.strip().upper())

    # ------------------------------------------------------------------
    # Reader lifecycle
    # ------------------------------------------------------------------
    def refresh_readers(self) -> Dict[str, Any]:
        """Re-enumerate PC/SC readers and (re)assign kiosk roles."""
        names = list_readers()
        roles = resolve_reader_roles(
            names,
            hardware.card_reader_match,
            hardware.book_reader_match,
            hardware.gate_reader_match,
        )
        for role, name in roles.items():
            self.readers[role] = name
            self._readers[role] = PCSCReader(name, role=role) if name else None
            self.reader_status[role]["name"] = name
            self.reader_status[role]["present"] = bool(name)

        if not PYSCARD_AVAILABLE:
            self.last_error = (
                f"pyscard is not available: {PYSCARD_IMPORT_ERROR}. "
                "Install it with 'pip install pyscard'."
            )
        elif not names:
            self.last_error = "No PC/SC readers detected. Connect the RFID readers and restart."
        else:
            self.last_error = None
        return self.get_hardware_status()

    def get_hardware_status(self) -> Dict[str, Any]:
        return {
            "pyscard_available": PYSCARD_AVAILABLE,
            "pyscard_error": PYSCARD_IMPORT_ERROR,
            "readers": {
                role: {
                    "name": self.reader_status[role]["name"],
                    "present": self.reader_status[role]["present"],
                    "error": self.reader_status[role]["error"],
                }
                for role in ("card", "book", "gate")
            },
            "map_file": HARDWARE_MAP_PATH,
            "map_entries": {
                "patron_cards": len(self.hardware_map.get("patron_cards", {})),
                "book_tags": len(self.hardware_map.get("book_tags", {})),
            },
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------
    def add_listener(self, cb: Callable):
        self.listeners.append(cb)

    async def _broadcast(self, event_type: str, data: Dict[str, Any]):
        payload = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        for cb in self.listeners:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------
    def get_pad_state(self) -> Dict[str, Any]:
        books = list(self.books_on_pad) + list(self.scanned_books)
        return {
            "books_zone": {
                "count": len(books),
                "books": books,
                "multi_collision_resolved": len(self.books_on_pad) > 1,
                "max_allowed_on_pad": config.max_books_allowed,
            },
            "card_zone": {
                "card_present": self.patron_card_on_pad is not None,
                "patron": self.patron_card_on_pad,
            },
            "gate_zone": self.gate_event,
            "hardware": self.get_hardware_status(),
        }

    # ------------------------------------------------------------------
    # Book pad helpers
    # ------------------------------------------------------------------
    def _find_pad_book(self, barcode_or_uid: str) -> Optional[Dict[str, Any]]:
        needle = barcode_or_uid.strip().upper()
        for book in list(self.books_on_pad) + list(self.scanned_books):
            if (book.get("barcode") or "").upper() == needle:
                return book
            if (book.get("tag_uid") or "").upper() == needle:
                return book
        return None

    async def _build_book_entry(self, barcode: Optional[str], tag_uid: Optional[str],
                                afi_hex: Optional[str], source: str) -> Dict[str, Any]:
        """Fetch real catalogue metadata from Koha for a resolved barcode."""
        title = None
        author = None
        call_number = None
        location = None
        known = False

        if barcode:
            try:
                from .sip2_client import sip_client
                item = await sip_client.get_item_info(barcode)
                if item.get("command") == "18" and item.get("item_barcode"):
                    fields = item.get("fields", {})
                    title = (item.get("title") or "").strip() or None
                    author = (item.get("author") or fields.get("CF") or "").strip() or None
                    call_number = (fields.get("CS") or "").strip() or None
                    location = (item.get("permanent_location") or "").strip() or None
                    known = title is not None
            except Exception:
                pass

        return {
            "barcode": barcode,
            "tag_uid": tag_uid,
            "title": title or (f"Unknown item ({barcode})" if barcode else "Unmapped RFID tag"),
            "author": author or "—",
            "call_number": call_number or "—",
            "location": location or "—",
            "afi": afi_hex,
            "eas": (afi_hex == settings.AFI_ARMED) if afi_hex else None,
            "known_in_koha": known,
            "source": source,
            "detected_at": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Barcode scanner input (real HID keyboard-wedge or serial scanner)
    # ------------------------------------------------------------------
    async def scan_book(self, barcode: str) -> Dict[str, Any]:
        """Register a scanned book barcode; metadata is verified against Koha."""
        clean = barcode.strip()
        if not clean:
            return {"success": False, "error": "Empty barcode", "state": self.get_pad_state()}

        async with self._lock:
            if self._find_pad_book(clean):
                return {"success": True, "message": "Barcode already queued",
                        "state": self.get_pad_state()}

            total = len(self.books_on_pad) + len(self.scanned_books)
            if total >= config.max_books_allowed:
                return {
                    "success": False,
                    "error": f"Pad capacity reached (maximum {config.max_books_allowed} items)",
                    "state": self.get_pad_state(),
                }

            from .sip2_client import sip_client
            item = await sip_client.get_item_info(clean)
            if item.get("command") != "18" or not item.get("item_barcode"):
                # Reject unknown barcodes instead of inventing catalogue data.
                await self._broadcast("SCAN_REJECTED", {
                    "barcode": clean,
                    "reason": item.get("screen_message") or item.get("error") or "Item not found in Koha",
                })
                return {
                    "success": False,
                    "error": item.get("screen_message") or item.get("error")
                    or f"Barcode {clean} not found in Koha",
                    "state": self.get_pad_state(),
                }

            entry = await self._build_book_entry(clean, None, None, source="scanner")
            self.scanned_books.append(entry)
            await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())
            return {"success": True, "book": entry, "state": self.get_pad_state()}

    async def scan_patron(self, barcode: str) -> Dict[str, Any]:
        """Authenticate a patron from a scanned library-card barcode."""
        clean = barcode.strip()
        if not clean:
            return {"success": False, "error": "Empty patron barcode"}
        return await self.authenticate_patron(clean, method="barcode")

    async def authenticate_patron(self, card_number: str, method: str = "barcode") -> Dict[str, Any]:
        """Authenticate any patron identifier against live Koha (SIP2 63/64)."""
        clean = card_number.strip()
        if not clean:
            return {"success": False, "error": "Empty patron identifier"}
        return await self._set_patron(clean, card_uid=None, method=method)

    async def clear_scanned(self) -> Dict[str, Any]:
        """Drop barcode-scanner entries (RFID pad entries follow live hardware)."""
        async with self._lock:
            self.scanned_books.clear()
        await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())
        return {"success": True, "state": self.get_pad_state()}

    # ------------------------------------------------------------------
    # Patron session
    # ------------------------------------------------------------------
    async def _set_patron(self, card_number: str, card_uid: Optional[str],
                          method: str) -> Dict[str, Any]:
        from .sip2_client import sip_client
        response = await sip_client.get_patron_info(card_number)

        if response.get("command") != "64" or response.get("valid_patron") is False:
            reason = response.get("screen_message") or response.get("error") or "Unknown patron"
            await self._broadcast("PATRON_AUTH_FAILED", {
                "card_number": card_number,
                "card_uid": card_uid,
                "reason": reason,
            })
            return {"success": False, "error": reason, "patron_id": card_number}

        name = (response.get("patron_name") or "").strip() or card_number
        charged_items = response.get("charged_items") or []

        async with self._lock:
            self.patron_card_on_pad = {
                "card_number": response.get("patron_id") or card_number,
                "mifare_uid": card_uid,
                "name": name,
                "charged_items": charged_items,
                "charged_count": len(charged_items),
                "fee_amount": response.get("fee_amount", "0.00"),
                "method": method,
                "tapped_at": datetime.now().isoformat(),
            }

        await self._broadcast("PATRON_CARD_TAPPED", self.get_pad_state())
        return {"success": True, "patron": self.patron_card_on_pad, "state": self.get_pad_state()}

    async def remove_patron(self) -> Dict[str, Any]:
        async with self._lock:
            self.patron_card_on_pad = None
        await self._broadcast("PATRON_CARD_REMOVED", self.get_pad_state())
        return {"success": True, "state": self.get_pad_state()}

    # ------------------------------------------------------------------
    # AFI security byte write (real ISO 15693 tag)
    # ------------------------------------------------------------------
    async def write_book_afi(self, barcode_or_uid: str, new_afi: str) -> Dict[str, Any]:
        """
        Write the AFI byte on the physical book tag.

        The barcode is resolved to a tag UID via the pad snapshot or the
        hardware map.  The write is performed on the real reader; if the reader
        cannot perform it, the failure is returned verbatim (never masked).
        """
        afi_int = int(new_afi, 16) if isinstance(new_afi, str) else int(new_afi)

        book = self._find_pad_book(barcode_or_uid)
        tag_uid = (book or {}).get("tag_uid")
        barcode = (book or {}).get("barcode") or barcode_or_uid

        if not tag_uid:
            for uid, mapped_bc in self.hardware_map.get("book_tags", {}).items():
                if mapped_bc.upper() == barcode_or_uid.strip().upper():
                    tag_uid = uid
                    barcode = mapped_bc
                    break

        reader = self._readers.get("book")
        if not reader or not tag_uid:
            reason = (
                "No book-pad reader configured" if not reader
                else f"No tag UID known for '{barcode_or_uid}'"
            )
            self.reader_status["book"]["error"] = reason
            return {"success": False, "error": reason, "afi": new_afi}

        try:
            ok = await asyncio.to_thread(
                reader.write_afi, tag_uid, afi_int, hardware.iso15693_append_crc
            )
        except PCSCReaderError as exc:
            return {"success": False, "error": str(exc), "afi": new_afi}

        if not ok:
            return {
                "success": False,
                "error": "Tag refused the AFI write (tag may be locked or out of range)",
                "afi": new_afi,
            }

        # Reflect the confirmed hardware state in the pad snapshot.
        for entry in self.books_on_pad:
            if (entry.get("tag_uid") or "").upper() == tag_uid.upper():
                entry["afi"] = new_afi
                entry["eas"] = (new_afi == settings.AFI_ARMED)
        for entry in self.scanned_books:
            if (entry.get("tag_uid") or "").upper() == tag_uid.upper():
                entry["afi"] = new_afi
                entry["eas"] = (new_afi == settings.AFI_ARMED)

        event = {
            "barcode": barcode,
            "tag_uid": tag_uid,
            "new_afi": new_afi,
            "state": "ARMED (EAS ON)" if new_afi == settings.AFI_ARMED else "DISARMED (EAS OFF)",
            "timestamp": datetime.now().isoformat(),
        }
        await self._broadcast("AFI_STATE_CHANGED", event)
        return {"success": True, "data": event}

    # ------------------------------------------------------------------
    # Background monitor loops
    # ------------------------------------------------------------------
    async def hardware_monitor_loop(self):
        """Supervise the three independent hardware polling loops."""
        self._stop.clear()
        tasks = [
            asyncio.create_task(self._card_reader_loop()),
            asyncio.create_task(self._book_pad_loop()),
            asyncio.create_task(self._gate_reader_loop()),
            asyncio.create_task(self._reader_watchdog_loop()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

    async def stop(self):
        self._stop.set()

    async def _reader_watchdog_loop(self):
        """Re-enumerate readers periodically so hot-plugged hardware recovers."""
        while not self._stop.is_set():
            try:
                await asyncio.sleep(10)
                current = {r["name"] for r in self.reader_status.values() if r["name"]}
                attached = set(list_readers())
                if attached != current:
                    self.refresh_readers()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def _card_reader_loop(self):
        while not self._stop.is_set():
            reader = self._readers.get("card")
            if not reader:
                await asyncio.sleep(1.0)
                continue
            try:
                uid = await asyncio.to_thread(reader.get_uid)
            except Exception as exc:
                self.reader_status["card"]["error"] = str(exc)
                uid = None

            if uid:
                self._card_missing = 0
                self.reader_status["card"]["error"] = None
                if uid != self._card_uid:
                    self._card_uid = uid
                    await self._on_card_present(uid)
            else:
                if self._card_uid is not None:
                    self._card_missing += 1
                    if self._card_missing >= hardware.removal_debounce_polls:
                        self._card_uid = None
                        self._card_missing = 0
                        if self.patron_card_on_pad:
                            await self.remove_patron()

            await asyncio.sleep(hardware.poll_interval_seconds)

    async def _on_card_present(self, uid: str):
        patron_id = self.resolve_patron_id(uid)
        if not patron_id:
            await self._broadcast("UNKNOWN_CARD", {
                "card_uid": uid,
                "message": "Card UID is not registered in hardware_map.json",
            })
            return
        await self._set_patron(patron_id, card_uid=uid, method="mifare")

    async def _book_pad_loop(self):
        while not self._stop.is_set():
            reader = self._readers.get("book")
            if not reader:
                await asyncio.sleep(1.0)
                continue
            try:
                tag = await asyncio.to_thread(
                    reader.read_book_tag, hardware.iso15693_append_crc
                )
            except Exception as exc:
                self.reader_status["book"]["error"] = str(exc)
                tag = None

            if tag:
                self.reader_status["book"]["error"] = None
                self._book_seen[tag.uid] = 0
                if not any((b.get("tag_uid") or "").upper() == tag.uid.upper()
                           for b in self.books_on_pad):
                    await self._on_book_present(tag.uid, tag.afi_hex)
            else:
                # Age out tags that are no longer on the pad.
                stale: List[str] = []
                for uid in list(self._book_seen.keys()):
                    self._book_seen[uid] += 1
                    if self._book_seen[uid] >= hardware.removal_debounce_polls:
                        stale.append(uid)
                for uid in stale:
                    self._book_seen.pop(uid, None)
                if stale:
                    before = len(self.books_on_pad)
                    self.books_on_pad = [
                        b for b in self.books_on_pad
                        if (b.get("tag_uid") or "").upper() not in {u.upper() for u in stale}
                    ]
                    if len(self.books_on_pad) != before:
                        await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())

            await asyncio.sleep(hardware.poll_interval_seconds)

    async def _on_book_present(self, tag_uid: str, afi_hex: Optional[str]):
        barcode = self.resolve_book_barcode(tag_uid)
        entry = await self._build_book_entry(barcode, tag_uid, afi_hex, source="rfid")
        async with self._lock:
            # Guard against a duplicate arriving while we were fetching metadata.
            if any((b.get("tag_uid") or "").upper() == tag_uid.upper()
                   for b in self.books_on_pad):
                return
            self.books_on_pad.append(entry)
        await self._broadcast("PAD_BOOKS_UPDATED", self.get_pad_state())

    async def _gate_reader_loop(self):
        loop = asyncio.get_event_loop()
        while not self._stop.is_set():
            reader = self._readers.get("gate")
            if not reader:
                await asyncio.sleep(1.0)
                continue

            now = loop.time()
            if now < self._gate_cooldown_until:
                await asyncio.sleep(hardware.poll_interval_seconds)
                continue

            try:
                tag = await asyncio.to_thread(
                    reader.read_book_tag, hardware.iso15693_append_crc
                )
            except Exception as exc:
                self.reader_status["gate"]["error"] = str(exc)
                tag = None

            if tag:
                self.reader_status["gate"]["error"] = None
                self._gate_cooldown_until = now + hardware.gate_cooldown_seconds
                await self._on_gate_tag(tag.uid, tag.afi_hex)

            await asyncio.sleep(hardware.poll_interval_seconds)

    async def _on_gate_tag(self, tag_uid: str, afi_hex: Optional[str]):
        barcode = self.resolve_book_barcode(tag_uid)
        armed = (afi_hex == settings.AFI_ARMED) if afi_hex else None
        self.gate_event = {
            "tag_uid": tag_uid,
            "barcode": barcode,
            "afi": afi_hex,
            "alarm": bool(armed),
            "unknown_afi": afi_hex is None,
            "status_text": (
                "SECURITY GATE ALARM - UNISSUED BOOK DETECTED (AFI 0x07 ARMED)"
                if armed else
                ("GATE CLEAR - VERIFIED KOHA ISSUE (AFI 0xC2 DISARMED)"
                 if armed is False else
                 "RFID TAG AFI UNREADABLE - MANUAL CHECK REQUIRED")
            ),
            "timestamp": datetime.now().isoformat(),
        }
        await self._broadcast("GATE_WALKTHROUGH", self.gate_event)


# Singleton instance
rfid_bridge = RFIDHardwareBridge()
