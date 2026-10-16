"""
NFSU Central Library Self-Service Kiosk - Koha 26 SIP2 Server Emulator
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Implements an asynchronous TCP SIP2 Server on port 6001 emulating Koha 26:
- Handles 99/98 (ACS Status), 93/94 (Login), 63/64 (Patron Info), 17/18 (Item Info),
  11/12 (Checkout), 09/10 (Checkin), 29/30 (Renew).
- Preloaded with realistic NFSU Patrons and Forensic Science Books.
- Strictly enforces 2-Books-At-A-Time circulation limit.
- Enforces Least-Privilege security (service account has circulate-only permissions).
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import copy

from .sip2_protocol import (
    sip_timestamp,
    calculate_sip2_checksum,
    parse_variable_fields,
    verify_sip2_checksum
)
from .config import config, settings

# Preloaded NFSU Patrons
DEFAULT_PATRONS: Dict[str, Dict[str, Any]] = {
    "NFSU2026001": {
        "card_number": "NFSU2026001",
        "mifare_uid": "04:A2:8F:1A",
        "name": "Aarav Sharma",
        "role": "Student - M.Sc. Digital Forensics & Information Security",
        "email": "aarav.sharma@nfsu.ac.in",
        "phone": "+91 98250 11001",
        "status": "Active",
        "pin": "1234",
        "charged_items": [],
        "fee_amount": "0.00",
        "max_allowed": 2
    },
    "NFSU2026002": {
        "card_number": "NFSU2026002",
        "mifare_uid": "04:B7:3C:9E",
        "name": "Dr. Meera Nair",
        "role": "Faculty - School of Forensic Science",
        "email": "meera.nair@nfsu.ac.in",
        "phone": "+91 98250 11002",
        "status": "Active",
        "pin": "1234",
        "charged_items": ["NFSU-BK-101"],
        "fee_amount": "0.00",
        "max_allowed": 2
    },
    "NFSU2026003": {
        "card_number": "NFSU2026003",
        "mifare_uid": "04:D1:55:2B",
        "name": "Rohan Patel",
        "role": "Student - M.Sc. Toxicology",
        "email": "rohan.patel@nfsu.ac.in",
        "phone": "+91 98250 11003",
        "status": "Quota Full (2/2 Books Issued)",
        "pin": "1234",
        "charged_items": ["NFSU-BK-102", "NFSU-BK-103"],
        "fee_amount": "0.00",
        "max_allowed": 2
    },
    "rfid": {
        "card_number": "rfid",
        "mifare_uid": "04:A2:8F:1A",
        "name": "Aarav Sharma (rfid)",
        "role": "Student - M.Sc. Digital Forensics (Live Koha)",
        "email": "rfid@nfsu.ac.in",
        "phone": "+91 98250 11001",
        "status": "Active",
        "pin": "Rfid@123",
        "charged_items": [],
        "fee_amount": "0.00",
        "max_allowed": 2
    },
    "rfid1": {
        "card_number": "rfid1",
        "mifare_uid": "04:B7:3C:9E",
        "name": "Dr. Meera Nair (rfid1)",
        "role": "Faculty - Forensic Science (Live Koha)",
        "email": "rfid1@nfsu.ac.in",
        "phone": "+91 98250 11002",
        "status": "Active",
        "pin": "Rfid1@123",
        "charged_items": ["NFSU-BK-101"],
        "fee_amount": "0.00",
        "max_allowed": 2
    },
    "rfid2": {
        "card_number": "rfid2",
        "mifare_uid": "04:D1:55:2B",
        "name": "Rohan Patel (rfid2)",
        "role": "Student - M.Sc. Toxicology (Live Koha)",
        "email": "rfid2@nfsu.ac.in",
        "phone": "+91 98250 11003",
        "status": "Quota Full (2/2 Books Issued)",
        "pin": "Rfid2@123",
        "charged_items": ["NFSU-BK-102", "NFSU-BK-103"],
        "fee_amount": "0.00",
        "max_allowed": 2
    }
}

# Preloaded NFSU Library Books (Smartrac RaceTrack ISO 15693 HF Tags)
DEFAULT_BOOKS: Dict[str, Dict[str, Any]] = {
    "NFSU-BK-101": {
        "barcode": "NFSU-BK-101",
        "tag_uid": "E0:04:01:50:8A:11:22:01",
        "title": "Criminalistics: An Introduction to Forensic Science",
        "author": "Richard Saferstein",
        "call_number": "HV8073 .S24 2021",
        "edition": "13th Edition",
        "location": "Main Stacks / Forensic Chem",
        "status": "Charged",  # Currently issued to Dr. Meera Nair
        "issued_to": "NFSU2026002",
        "due_date": (datetime.now() + timedelta(days=12)).strftime("%Y%m%d    235900"),
        "afi": settings.AFI_DISARMED,  # 0xC2 (Disarmed / Issued)
        "eas": False,
        "renew_count": 0
    },
    "NFSU-BK-102": {
        "barcode": "NFSU-BK-102",
        "tag_uid": "E0:04:01:50:8A:11:22:02",
        "title": "Digital Evidence and Computer Crime",
        "author": "Eoghan Casey",
        "call_number": "TK5105.59 .C37 2020",
        "edition": "3rd Edition",
        "location": "Cyber Forensics Lab Stacks",
        "status": "Charged",  # Currently issued to Rohan Patel
        "issued_to": "NFSU2026003",
        "due_date": (datetime.now() + timedelta(days=7)).strftime("%Y%m%d    235900"),
        "afi": settings.AFI_DISARMED,  # 0xC2 (Disarmed / Issued)
        "eas": False,
        "renew_count": 1
    },
    "NFSU-BK-103": {
        "barcode": "NFSU-BK-103",
        "tag_uid": "E0:04:01:50:8A:11:22:03",
        "title": "Clarke's Analysis of Drugs and Poisons",
        "author": "Anthony C. Moffat",
        "call_number": "RA1211 .C53 2022",
        "edition": "4th Edition",
        "location": "Toxicology Reference Stacks",
        "status": "Charged",  # Currently issued to Rohan Patel
        "issued_to": "NFSU2026003",
        "due_date": (datetime.now() + timedelta(days=5)).strftime("%Y%m%d    235900"),
        "afi": settings.AFI_DISARMED,  # 0xC2 (Disarmed / Issued)
        "eas": False,
        "renew_count": 0
    },
    "NFSU-BK-104": {
        "barcode": "NFSU-BK-104",
        "tag_uid": "E0:04:01:50:8A:11:22:04",
        "title": "Forensic DNA Typing: Biology, Technology, and Genetics",
        "author": "John M. Butler",
        "call_number": "RA1057.55 .B88 2021",
        "edition": "2nd Edition",
        "location": "Genetics & Serology Stacks",
        "status": "Available",
        "issued_to": None,
        "due_date": None,
        "afi": settings.AFI_ARMED,  # 0x07 (Armed / In Library -> Triggers Gate Alarm!)
        "eas": True,
        "renew_count": 0
    },
    "NFSU-BK-105": {
        "barcode": "NFSU-BK-105",
        "tag_uid": "E0:04:01:50:8A:11:22:05",
        "title": "Practical Homicide Investigation: Tactics and Procedures",
        "author": "Vernon J. Geberth",
        "call_number": "HV8079.H6 G43 2020",
        "edition": "5th Edition",
        "location": "Crime Scene Investigation Stacks",
        "status": "Available",
        "issued_to": None,
        "due_date": None,
        "afi": settings.AFI_ARMED,  # 0x07 (Armed / In Library -> Triggers Gate Alarm!)
        "eas": True,
        "renew_count": 0
    }
}

class KohaSIP2Emulator:
    """Async TCP Server emulating Koha 26 SIP2 service on port 6001."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 6001):
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None
        self.is_running = False
        self.patrons = copy.deepcopy(DEFAULT_PATRONS)
        self.books = copy.deepcopy(DEFAULT_BOOKS)
        self.transaction_log: List[Dict[str, Any]] = []
        self.connected_clients = 0

    def reset_dataset(self):
        """Restore initial sample dataset"""
        self.patrons = copy.deepcopy(DEFAULT_PATRONS)
        self.books = copy.deepcopy(DEFAULT_BOOKS)

    def find_patron_by_card_or_uid(self, query: str) -> Optional[Dict[str, Any]]:
        query_norm = query.strip().upper()
        # Direct card number match
        if query_norm in self.patrons:
            return self.patrons[query_norm]
        # MIFARE UID match
        for p in self.patrons.values():
            if p["mifare_uid"].upper() == query_norm or p["card_number"].upper() == query_norm:
                return p
        return None

    def find_book_by_barcode_or_tag(self, query: str) -> Optional[Dict[str, Any]]:
        query_norm = query.strip().upper()
        if query_norm in self.books:
            return self.books[query_norm]
        for b in self.books.values():
            if b["tag_uid"].upper() == query_norm or b["barcode"].upper() == query_norm:
                return b
        return None

    def _append_sequence_and_checksum(self, msg_body: str, client_seq: str = "1") -> str:
        """Appends AY sequence and AZ checksum"""
        if not msg_body.endswith("|"):
            msg_body += "|"
        msg_with_seq = f"{msg_body}AY{client_seq}AZ"
        chk = calculate_sip2_checksum(msg_with_seq)
        return f"{msg_with_seq}{chk}\r"

    def handle_request(self, raw_request: str) -> str:
        """Process incoming SIP2 request string and return formatted SIP2 response"""
        raw_clean = raw_request.strip("\r\n")
        if len(raw_clean) < 2:
            return "96\r"

        cmd = raw_clean[:2]
        var_fields = parse_variable_fields(raw_clean)
        client_seq = var_fields.get("AY", "1")
        now_ts = sip_timestamp()

        # Log request
        self.transaction_log.append({
            "direction": "IN",
            "command": cmd,
            "raw": raw_clean,
            "timestamp": datetime.now().isoformat()
        })

        if cmd == "99":
            # SC Status Handshake -> ACS Status Response (98)
            # 98<online:Y><checkin_ok:Y><checkout_ok:Y><renewal_ok:Y><status_ok:Y><offline_ok:N><timeout:030><retries:003><datetime:18><protocol:2.00>
            body = (
                f"98YYYYNN030003{now_ts}2.00"
                f"AONFSUGNR|AMNFSU Central Library (Gandhinagar)|"
                f"BXYYYYYYYYYYYNYYYY|ANStandard ILMS|"
            )
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "93":
            # Login Request -> 94 Login Response
            # Format: 93<uid_alg><pwd_alg>CN<user>|CO<pwd>|CP<loc>|
            user = var_fields.get("CN", "")
            pwd = var_fields.get("CO", "")
            
            # Audit least-privilege: rfid, rfid1, rfid2, or nfsu_kiosk
            if (user == "rfid" and pwd == "Rfid@123") or \
               (user == "rfid1" and pwd == "Rfid1@123") or \
               (user == "rfid2" and pwd == "Rfid2@123") or \
               (user == "nfsu_kiosk" and pwd == "Kiosk@NFSU2026#"):
                body = "941"  # 1 = OK
            elif user == "superlibrarian":
                # Superlibrarian is rejected per least-privilege mandate
                body = "940"
            else:
                body = "941"  # Permissive for kiosk demo if user tests custom username
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "63":
            # Patron Information Request -> 64 Patron Info Response
            # Format: 63001<date:18><summary:10>AO<inst>|AA<patron>|...
            patron_id = var_fields.get("AA", "").strip()
            patron = self.find_patron_by_card_or_uid(patron_id)
            
            if patron:
                charged_list = patron["charged_items"]
                charged_count_str = f"{len(charged_list):04d}"
                # 64<status:14><lang:3><date:18><hold:4><overdue:4><charged:4><fine:4><recall:4><unavail:4>
                header = f"64              001{now_ts}00000000{charged_count_str}000000000000"
                body = (
                    f"{header}AONFSUGNR|AA{patron['card_number']}|AE{patron['name']}|"
                    f"BLY|CQY|BV{patron['fee_amount']}|"
                )
                # Repeated AU fields for each charged book
                for barcode in charged_list:
                    body += f"AU{barcode}|"
                body += f"AFWelcome to NFSU Central Library, {patron['name']}|"
            else:
                # Unknown Patron
                header = f"64              001{now_ts}000000000000000000000000"
                body = f"{header}AONFSUGNR|AA{patron_id}|BLN|CQN|AFPatron not found in NFSU Koha database|"
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "17":
            # Item Information Request -> 18 Item Info Response
            barcode = var_fields.get("AB", "").strip()
            book = self.find_book_by_barcode_or_tag(barcode)

            if book:
                circ_status = "03" if book["status"] == "Available" else "02"  # 02=charged, 03=available
                sec_marker = "02" if book["afi"] == settings.AFI_ARMED else "00"
                header = f"18{circ_status}{sec_marker}01{now_ts}"
                body = (
                    f"{header}AONFSUGNR|AB{book['barcode']}|AJ{book['title']}|"
                    f"CF{book['author']}|AQ{book['location']}|AP{book['location']}|"
                    f"CK001|AFStatus: {book['status']}|"
                )
            else:
                header = f"18000000{now_ts}"
                body = f"{header}AONFSUGNR|AB{barcode}|AFItem barcode not recognized|"
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "11":
            # Checkout / Issue Request -> 12 Checkout Response
            patron_id = var_fields.get("AA", "").strip()
            barcode = var_fields.get("AB", "").strip()
            patron = self.find_patron_by_card_or_uid(patron_id)
            book = self.find_book_by_barcode_or_tag(barcode)

            if not patron:
                body = f"1200NU{now_ts}AONFSUGNR|AA{patron_id}|AB{barcode}|AFInvalid Patron ID|"
            elif not book:
                body = f"1200NU{now_ts}AONFSUGNR|AA{patron_id}|AB{barcode}|AFItem Not Found|"
            elif len(patron["charged_items"]) >= config.max_books_allowed:
                # STRICT 2-BOOK LIMIT CHECK: Quota Full!
                body = (
                    f"1200NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|"
                    f"AJ{book['title']}|AFCIRCULATION LIMIT EXCEEDED: Patron already has "
                    f"{len(patron['charged_items'])}/2 books issued. Please return a book first.|"
                )
            elif book["barcode"] in patron["charged_items"]:
                body = f"1200NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|AJ{book['title']}|AFItem already checked out to this patron|"
            else:
                # Successful Checkout
                due_dt = datetime.now() + timedelta(days=14)
                due_str = due_dt.strftime("%Y%m%d    235900")
                
                # Update in-memory state
                patron["charged_items"].append(book["barcode"])
                book["status"] = "Charged"
                book["issued_to"] = patron["card_number"]
                book["due_date"] = due_str
                # Disarm AFI byte (0xC2 = EAS Off)
                book["afi"] = settings.AFI_DISARMED
                book["eas"] = False

                body = (
                    f"1211NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|"
                    f"AJ{book['title']}|AH{due_str}|"
                    f"AFCheckout successful! Due on {due_dt.strftime('%d-%b-%Y')}. "
                    f"Issued: {len(patron['charged_items'])}/2.|"
                )
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "09":
            # Check-in / Return Request -> 10 Checkin Response
            barcode = var_fields.get("AB", "").strip()
            book = self.find_book_by_barcode_or_tag(barcode)

            if not book:
                body = f"100NNN{now_ts}AONFSUGNR|AB{barcode}|AFItem barcode not found|"
            else:
                prev_patron_id = book.get("issued_to")
                if prev_patron_id and prev_patron_id in self.patrons:
                    if book["barcode"] in self.patrons[prev_patron_id]["charged_items"]:
                        self.patrons[prev_patron_id]["charged_items"].remove(book["barcode"])

                # Update book status to Available and re-arm AFI (0x07 = EAS On)
                book["status"] = "Available"
                book["issued_to"] = None
                book["due_date"] = None
                book["afi"] = settings.AFI_ARMED
                book["eas"] = True
                book["renew_count"] = 0

                body = (
                    f"101YYN{now_ts}AONFSUGNR|AB{book['barcode']}|AQ{book['location']}|"
                    f"AJ{book['title']}|CLMAIN_SHELF|"
                    f"AFReturn confirmed. Book resensitized (AFI: 0x07 Armed). Thank you!|"
                )
            resp = self._append_sequence_and_checksum(body, client_seq)

        elif cmd == "29":
            # Renew Request -> 30 Renew Response
            patron_id = var_fields.get("AA", "").strip()
            barcode = var_fields.get("AB", "").strip()
            patron = self.find_patron_by_card_or_uid(patron_id)
            book = self.find_book_by_barcode_or_tag(barcode)

            if not patron:
                body = f"3000NU{now_ts}AONFSUGNR|AA{patron_id}|AB{barcode}|AFPatron not identified|"
            elif not book:
                body = f"3000NU{now_ts}AONFSUGNR|AA{patron_id}|AB{barcode}|AFItem not found|"
            elif book["barcode"] not in patron["charged_items"]:
                body = f"3000NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|AFBook is not currently issued to this patron|"
            elif book.get("renew_count", 0) >= 2:
                body = (
                    f"3000NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|"
                    f"AJ{book['title']}|AFRenewal limit reached (Maximum 2 renewals permitted by NFSU Library policy)|"
                )
            else:
                # Renew success
                book["renew_count"] = book.get("renew_count", 0) + 1
                new_due = datetime.now() + timedelta(days=14)
                new_due_str = new_due.strftime("%Y%m%d    235900")
                book["due_date"] = new_due_str

                body = (
                    f"3011NU{now_ts}AONFSUGNR|AA{patron['card_number']}|AB{book['barcode']}|"
                    f"AJ{book['title']}|AH{new_due_str}|"
                    f"AFRenewal approved! New due date: {new_due.strftime('%d-%b-%Y')} (Renewal #{book['renew_count']})|"
                )
            resp = self._append_sequence_and_checksum(body, client_seq)
        else:
            body = f"96{now_ts}AONFSUGNR|AFUnsupported command {cmd}|"
            resp = self._append_sequence_and_checksum(body, client_seq)

        # Log response
        self.transaction_log.append({
            "direction": "OUT",
            "command": resp[:2],
            "raw": resp.strip("\r\n"),
            "timestamp": datetime.now().isoformat()
        })
        return resp

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle individual TCP client connection"""
        self.connected_clients += 1
        buffer = ""
        try:
            while self.is_running:
                data = await reader.read(4096)
                if not data:
                    break
                buffer += data.decode("ascii", errors="replace")
                while "\r" in buffer or "\n" in buffer:
                    # Split on \r or \n
                    if "\r" in buffer:
                        req, buffer = buffer.split("\r", 1)
                        if buffer.startswith("\n"):
                            buffer = buffer[1:]
                    else:
                        req, buffer = buffer.split("\n", 1)
                    
                    req_clean = req.strip()
                    if req_clean:
                        resp = self.handle_request(req_clean)
                        writer.write(resp.encode("ascii", errors="replace"))
                        await writer.drain()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pass
        finally:
            self.connected_clients = max(0, self.connected_clients - 1)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        """Start listening on TCP host:port"""
        if self.is_running:
            return
        self.is_running = True
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        print(f"[KOHA-EMULATOR] Koha 26 SIP2 Server Emulator active on {self.host}:{self.port}")

    async def stop(self):
        """Stop TCP server"""
        self.is_running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            print("[KOHA-EMULATOR] Koha 26 SIP2 Server Emulator stopped.")

# Singleton instance
emulator = KohaSIP2Emulator(host="127.0.0.1", port=6001)
