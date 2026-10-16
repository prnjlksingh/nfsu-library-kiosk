"""
NFSU Central Library Self-Service Kiosk - SIP2 Protocol Engine
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Implements 3M Standard Interchange Protocol Version 2.0 (SIP2) with:
- Strict 16-bit Two's-Complement Checksum (AZ)
- Sequence Numbering (AY)
- Delimiter: '|' (0x7C)
- Message Terminator: '\r' (0x0D) or '\r\n'
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# AY<seq>AZ<checksum> trailer emitted at the very end of every SIP2 message.
_TRAILER_RE = re.compile(r"AY\dAZ[0-9A-Fa-f]{0,4}$")

def sip_timestamp(dt: Optional[datetime] = None) -> str:
    """Format datetime to standard SIP2 format: YYYYMMDD    HHMMSS (18 chars)"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y%m%d    %H%M%S")

def calculate_sip2_checksum(msg_without_chk: str) -> str:
    """
    Calculate 16-bit two's complement checksum for SIP2 message.
    The checksum includes all bytes from index 0 up to and including 'Z' of 'AZ'.
    Sum(bytes) + Checksum = 0 (mod 65536).
    """
    s = sum(ord(c) for c in msg_without_chk)
    chk = (-s) & 0xFFFF
    return f"{chk:04X}"

def verify_sip2_checksum(raw_msg: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Verify if the message contains a valid AZ checksum.
    Returns (is_valid, calculated_checksum, provided_checksum)
    """
    raw_clean = raw_msg.strip("\r\n")
    if "AZ" not in raw_clean:
        return (True, None, None)  # Checksum is optional in basic SIP2, but verified when present
    
    az_idx = raw_clean.rfind("AZ")
    msg_part = raw_clean[:az_idx + 2]
    provided = raw_clean[az_idx + 2: az_idx + 6]
    
    s = sum(ord(c) for c in msg_part)
    calc = (-s) & 0xFFFF
    calc_hex = f"{calc:04X}"
    
    is_valid = (calc_hex.upper() == provided.upper())
    return (is_valid, calc_hex, provided)

def _int_field(raw: str, default: int = 0) -> int:
    """Parse a fixed-width SIP2 numeric field, tolerating spaces/blank fields."""
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        try:
            return int("".join(ch for ch in text if ch.isdigit()) or default)
        except ValueError:
            return default


def parse_variable_fields(var_part: str) -> Dict[str, Any]:
    """
    Parse pipe-delimited variable fields.
    Handles repeated fields like 'AU' (charged items) by aggregating them into lists.
    """
    fields: Dict[str, Any] = {}
    tokens = var_part.split("|")
    for token in tokens:
        if len(token) >= 2:
            tag = token[:2]
            val = token[2:]
            if tag in ("AU", "AV", "AS", "AT"):  # Repeated field tags (AU=charged items, AV=fine items)
                if tag not in fields:
                    fields[tag] = []
                fields[tag].append(val)
            else:
                fields[tag] = val
    return fields

class SIP2MessageBuilder:
    """Constructs valid SIP2 messages with AY sequence numbers and AZ checksums."""
    
    def __init__(self, sequence: int = 1):
        self.seq = sequence % 10

    def next_seq(self) -> int:
        current = self.seq
        self.seq = (self.seq + 1) % 10
        return current

    def finalize(self, msg_body: str, include_checksum: bool = True) -> str:
        """Append AY sequence and AZ checksum, terminated with carriage return."""
        seq_tag = f"AY{self.next_seq()}"
        # Message 99 (SC Status) has no variable fields, so no trailing pipe
        if not msg_body.startswith("99") and not msg_body.endswith("|"):
            msg_body += "|"
        msg_with_seq = f"{msg_body}{seq_tag}AZ"
        if include_checksum:
            chk = calculate_sip2_checksum(msg_with_seq)
            return f"{msg_with_seq}{chk}\r"
        return f"{msg_with_seq}\r"

    def build_99_sc_status(self, status_code: str = "0", max_width: str = "030", protocol: str = "2.00") -> str:
        """99 SC Status Handshake request"""
        body = f"99{status_code}{max_width}{protocol}"
        return self.finalize(body)

    def build_93_login(self, uid_alg: str = "0", pwd_alg: str = "0", user: str = "nfsu_kiosk", pwd: str = "Kiosk@NFSU2026#", location: str = "NFSU_MAIN") -> str:
        """93 Login request"""
        body = f"93{uid_alg}{pwd_alg}CN{user}|CO{pwd}|CP{location}|"
        return self.finalize(body)

    def build_63_patron_info(self, patron_id: str, institution_id: str = "NFSU", summary: str = "  Y       ", terminal_pwd: str = "", patron_pwd: str = "") -> str:
        """
        63 Patron Information request.
        Position 3 of the 10-character summary set to 'Y' requests the
        currently charged items (the AU fields in the 64 response).
        """
        now = sip_timestamp()
        summary = (summary + " " * 10)[:10]
        body = f"63001{now}{summary}AO{institution_id}|AA{patron_id}|AC{terminal_pwd}|AD{patron_pwd}|"
        return self.finalize(body)

    def build_17_item_info(self, item_barcode: str, institution_id: str = "NFSU", terminal_pwd: str = "") -> str:
        """17 Item Information lookup request"""
        now = sip_timestamp()
        body = f"17{now}AO{institution_id}|AB{item_barcode}|AC{terminal_pwd}|"
        return self.finalize(body)

    def build_11_checkout(self, patron_id: str, item_barcode: str, institution_id: str = "NFSU", terminal_pwd: str = "", nb_due_date: str = "                  ") -> str:
        """11 Checkout / Issue request with AY sequence and AZ checksum"""
        now = sip_timestamp()
        body = f"11YN{now}{nb_due_date}AO{institution_id}|AA{patron_id}|AB{item_barcode}|AC{terminal_pwd}|CH|BIN|"
        return self.finalize(body)

    def build_09_checkin(self, item_barcode: str, institution_id: str = "NFSU", location: str = "NFSU_MAIN", terminal_pwd: str = "") -> str:
        """09 Check-in / Return request"""
        now = sip_timestamp()
        return_date = now
        body = f"09N{now}{return_date}AP{location}|AO{institution_id}|AB{item_barcode}|AC{terminal_pwd}|CH|BIN|"
        return self.finalize(body)

    def build_29_renew(self, patron_id: str, item_barcode: str, institution_id: str = "NFSU", terminal_pwd: str = "", nb_due_date: str = "                  ") -> str:
        """29 Renew request"""
        now = sip_timestamp()
        body = f"29NN{now}{nb_due_date}AO{institution_id}|AA{patron_id}|AB{item_barcode}|AC{terminal_pwd}|CH|BIN|"
        return self.finalize(body)

class SIP2MessageParser:
    """Parses incoming SIP2 responses and extracts structured data."""

    @staticmethod
    def parse(raw_msg: str) -> Dict[str, Any]:
        raw_clean = raw_msg.strip("\r\n")
        if len(raw_clean) < 2:
            return {"error": "Message too short", "raw": raw_msg}

        cmd_code = raw_clean[:2]
        result: Dict[str, Any] = {
            "command": cmd_code,
            "raw": raw_clean,
            "timestamp": datetime.now().isoformat(),
        }

        # Verify Checksum
        valid_chk, calc_chk, prov_chk = verify_sip2_checksum(raw_clean)
        result["checksum_valid"] = valid_chk
        result["checksum_calculated"] = calc_chk
        result["checksum_provided"] = prov_chk

        # Drop the trailing AY<seq>AZ<checksum> envelope so it can never leak
        # into the variable-field dictionary.  ``result["raw"]`` above keeps
        # the untouched message.
        raw_clean = _TRAILER_RE.sub("", raw_clean)

        try:
            if cmd_code == "94":  # Login Response
                # Format: 94<ok: 1 char>
                result["type"] = "Login Response"
                result["ok"] = (raw_clean[2:3] == "1") if len(raw_clean) >= 3 else False
                var_start = 3
                if len(raw_clean) > var_start:
                    result["fields"] = parse_variable_fields(raw_clean[var_start:])
                else:
                    result["fields"] = {}

            elif cmd_code == "98":  # ACS Status Response
                # Format: 98<online:1><checkin_ok:1><checkout_ok:1><renew_ok:1><status_ok:1><offline_ok:1><timeout:3><retries:3><date:18><protocol:4>
                result["type"] = "ACS Status Response"
                if len(raw_clean) >= 33:
                    result["online_status"] = raw_clean[2:3]
                    result["checkin_ok"] = (raw_clean[3:4] == "Y")
                    result["checkout_ok"] = (raw_clean[4:5] == "Y")
                    result["renewal_ok"] = (raw_clean[5:6] == "Y")
                    result["status_update_ok"] = (raw_clean[6:7] == "Y")
                    result["offline_ok"] = (raw_clean[7:8] == "Y")
                    result["timeout"] = raw_clean[8:11]
                    result["retries"] = raw_clean[11:14]
                    result["date_time"] = raw_clean[14:32].strip()
                    result["protocol_version"] = raw_clean[32:36]
                    result["fields"] = parse_variable_fields(raw_clean[36:])
                else:
                    result["fields"] = parse_variable_fields(raw_clean[2:])

            elif cmd_code == "64":  # Patron Information Response
                # Format: 64<status:14><lang:3><date:18><hold:4><overdue:4><charged:4><fine:4><recall:4><unavail_hold:4>
                result["type"] = "Patron Information Response"
                if len(raw_clean) >= 61:
                    result["patron_status"] = raw_clean[2:16]
                    result["language"] = raw_clean[16:19]
                    result["transaction_date"] = raw_clean[19:37].strip()
                    result["hold_items_count"] = _int_field(raw_clean[37:41])
                    result["overdue_items_count"] = _int_field(raw_clean[41:45])
                    result["charged_items_count"] = _int_field(raw_clean[45:49])
                    result["fine_items_count"] = _int_field(raw_clean[49:53])
                    result["recall_items_count"] = _int_field(raw_clean[53:57])
                    result["unavailable_holds_count"] = _int_field(raw_clean[57:61])
                    result["fields"] = parse_variable_fields(raw_clean[61:])
                else:
                    result["fields"] = parse_variable_fields(raw_clean[2:])
                
                # Convenience mappings
                f = result.get("fields", {})
                result["patron_id"] = f.get("AA", "")
                result["patron_name"] = f.get("AE", "")
                result["valid_patron"] = (f.get("BL", "Y") == "Y")
                result["valid_password"] = (f.get("CQ", "Y") == "Y")
                result["fee_amount"] = f.get("BV", "0.00")
                result["charged_items"] = f.get("AU", []) if isinstance(f.get("AU"), list) else ([f.get("AU")] if f.get("AU") else [])

            elif cmd_code == "18":  # Item Information Response
                # Format: 18<circ_status:2><sec_marker:2><fee_type:2><date:18>
                result["type"] = "Item Information Response"
                if len(raw_clean) >= 26:
                    result["circulation_status"] = raw_clean[2:4]
                    result["security_marker"] = raw_clean[4:6]
                    result["fee_type"] = raw_clean[6:8]
                    result["transaction_date"] = raw_clean[8:26].strip()
                    result["fields"] = parse_variable_fields(raw_clean[26:])
                else:
                    result["fields"] = parse_variable_fields(raw_clean[2:])
                
                f = result.get("fields", {})
                result["item_barcode"] = f.get("AB", "")
                result["title"] = f.get("AJ", "")
                result["author"] = f.get("CF", "")  # or screen message AF
                result["media_type"] = f.get("CK", "")
                result["permanent_location"] = f.get("AQ", "")
                result["current_location"] = f.get("AP", "")
                result["screen_message"] = f.get("AF", "")

            elif cmd_code == "12":  # Checkout Response
                # Format: 12<ok:1><renewal_ok:1><magnetic_media:1><desensitize:1><date:18>
                result["type"] = "Checkout Response"
                if len(raw_clean) >= 24:
                    result["ok"] = (raw_clean[2:3] == "1")
                    result["renewal_ok"] = (raw_clean[3:4] == "1")
                    result["magnetic_media"] = raw_clean[4:5]
                    result["desensitize"] = (raw_clean[5:6] == "Y")
                    result["transaction_date"] = raw_clean[6:24].strip()
                    result["fields"] = parse_variable_fields(raw_clean[24:])
                else:
                    result["ok"] = False
                    result["fields"] = parse_variable_fields(raw_clean[2:])

                f = result.get("fields", {})
                result["patron_id"] = f.get("AA", "")
                result["item_barcode"] = f.get("AB", "")
                result["title"] = f.get("AJ", "")
                result["due_date"] = f.get("AH", "")
                result["screen_message"] = f.get("AF", "")

            elif cmd_code == "10":  # Checkin Response
                # Format: 10<ok:1><resensitize:1><magnetic_media:1><alert:1><date:18>
                result["type"] = "Checkin Response"
                if len(raw_clean) >= 24:
                    result["ok"] = (raw_clean[2:3] == "1")
                    result["resensitize"] = (raw_clean[3:4] == "Y")
                    result["magnetic_media"] = raw_clean[4:5]
                    result["alert"] = (raw_clean[5:6] == "Y")
                    result["transaction_date"] = raw_clean[6:24].strip()
                    result["fields"] = parse_variable_fields(raw_clean[24:])
                else:
                    result["ok"] = False
                    result["fields"] = parse_variable_fields(raw_clean[2:])

                f = result.get("fields", {})
                result["item_barcode"] = f.get("AB", "")
                result["title"] = f.get("AJ", "")
                result["permanent_location"] = f.get("AQ", "")
                result["screen_message"] = f.get("AF", "")

            elif cmd_code == "30":  # Renew Response
                # Format: 30<ok:1><renewal_ok:1><magnetic_media:1><desensitize:1><date:18>
                result["type"] = "Renew Response"
                if len(raw_clean) >= 24:
                    result["ok"] = (raw_clean[2:3] == "1")
                    result["renewal_ok"] = (raw_clean[3:4] == "1")
                    result["magnetic_media"] = raw_clean[4:5]
                    result["desensitize"] = (raw_clean[5:6] == "Y")
                    result["transaction_date"] = raw_clean[6:24].strip()
                    result["fields"] = parse_variable_fields(raw_clean[24:])
                else:
                    result["ok"] = False
                    result["fields"] = parse_variable_fields(raw_clean[2:])

                f = result.get("fields", {})
                result["patron_id"] = f.get("AA", "")
                result["item_barcode"] = f.get("AB", "")
                result["title"] = f.get("AJ", "")
                result["due_date"] = f.get("AH", "")
                result["screen_message"] = f.get("AF", "")
            else:
                result["type"] = f"Generic Message ({cmd_code})"
                result["fields"] = parse_variable_fields(raw_clean[2:])
        except Exception as e:
            result["parse_error"] = str(e)

        return result
