"""
NFSU Central Library Self-Service Kiosk - PC/SC Contactless Reader Layer
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

A thin, cross-platform (Windows / Linux / macOS) abstraction over PC/SC using
``pyscard``.  It exposes exactly the primitives the kiosk needs:

* ``list_readers()``            - enumerate installed PC/SC readers
* ``PCSCReader.get_uid()``      - ISO 14443A MIFARE UID (patron cards)
* ``PCSCReader.inventory()``    - ISO 15693 inventory (book tags)
* ``PCSCReader.get_system_info()`` - ISO 15693 DSFID / AFI
* ``PCSCReader.write_afi()``    - ISO 15693 Write AFI (security re-arm/disarm)

If ``pyscard`` is not installed or no reader matches, every operation fails
loudly with :class:`PCSCReaderError`.  There is deliberately **no** simulated
or fallback card data anywhere in this module.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:  # pragma: no cover - import guard, exercised on every platform
    from smartcard.System import readers as _sc_readers
    from smartcard.util import toHexString as _to_hex
    from smartcard.Exceptions import (
        NoReadersException,
        NoCardException,
        CardConnectionException,
        CardRequestTimeoutException,
    )

    PYSCARD_AVAILABLE = True
    PYSCARD_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover
    _sc_readers = None  # type: ignore
    _to_hex = None  # type: ignore

    class NoReadersException(Exception):  # type: ignore
        pass

    class NoCardException(Exception):  # type: ignore
        pass

    class CardConnectionException(Exception):  # type: ignore
        pass

    class CardRequestTimeoutException(Exception):  # type: ignore
        pass

    PYSCARD_AVAILABLE = False
    PYSCARD_IMPORT_ERROR = str(exc)


class PCSCReaderError(RuntimeError):
    """Raised whenever a physical reader operation cannot be completed."""


# --------------------------------------------------------------------------
# ISO 14443A
# --------------------------------------------------------------------------
# "GET DATA" pseudo-APDU supported by all PC/SC contactless readers.
_GET_DATA_APDU: List[int] = [0xFF, 0xCA, 0x00, 0x00, 0x00]
_SW_SUCCESS: Tuple[int, int] = (0x90, 0x00)


# --------------------------------------------------------------------------
# ISO 15693 (NXP ICODE SLIX2 / Avery Dennison Smartrac)
# --------------------------------------------------------------------------
_ISO15693_INVENTORY = 0x01
_ISO15693_WRITE_AFI = 0x27
_ISO15693_LOCK_AFI = 0x28
_ISO15693_GET_SYSTEM_INFO = 0x2B

# Request flags
_FLAG_HIGH_DATA_RATE = 0x02
_FLAG_INVENTORY_SINGLE_SLOT = 0x26
_FLAG_ADDRESSED = 0x20
_FLAG_ERROR = 0x01


def crc16_iso15693(data: bytes) -> bytes:
    """
    CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over ``data``.

    Returns the 16-bit value as two bytes in *value* order (most significant
    byte first), which is the order in which the CRC belongs when appended to
    the message to obtain the classic zero residue.  ISO 15693 transmits the
    CRC **least significant byte first** on the wire - use
    :func:`iso15693_append_crc` to build a real frame.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return bytes([(crc >> 8) & 0xFF, crc & 0xFF])


def iso15693_append_crc(frame: bytes) -> bytes:
    """Append the CRC-16/CCITT to ``frame`` in ISO 15693 wire order (LSB first)."""
    crc = crc16_iso15693(frame)
    return frame + bytes(reversed(crc))


def _format_uid(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in raw)


@dataclass
class BookTag:
    """A live ISO 15693 tag read from the book pad."""

    uid: str
    afi: Optional[int] = None
    dsfid: Optional[int] = None

    @property
    def afi_hex(self) -> Optional[str]:
        return None if self.afi is None else f"0x{self.afi:02X}"

    @property
    def eas_on(self) -> Optional[bool]:
        return None if self.afi is None else (self.afi == 0x07)


@dataclass
class ReaderSnapshot:
    """Telemetry-safe description of a single PC/SC reader."""

    name: str
    role: str
    card_present: bool = False
    last_error: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)


def list_readers() -> List[str]:
    """Return the names of all PC/SC readers currently attached."""
    if not PYSCARD_AVAILABLE:
        return []
    try:
        return [str(r) for r in _sc_readers()]
    except NoReadersException:
        return []
    except Exception:
        return []


class PCSCReader:
    """A single PC/SC contactless reader bound by name."""

    def __init__(self, name: str, role: str = "generic"):
        self.name = name
        self.role = role
        self._lock = threading.Lock()

    # -- internal helpers --------------------------------------------------
    def _connect(self):
        if not PYSCARD_AVAILABLE:
            raise PCSCReaderError(
                f"pyscard is not installed ({PYSCARD_IMPORT_ERROR}). "
                "Install it with: pip install pyscard"
            )
        for reader in _sc_readers():
            if str(reader) == self.name:
                try:
                    connection = reader.createConnection()
                    connection.connect()
                    return connection
                except (NoCardException, CardRequestTimeoutException) as exc:
                    raise PCSCReaderError(f"No card on reader '{self.name}'") from exc
                except (CardConnectionException, Exception) as exc:
                    raise PCSCReaderError(
                        f"Cannot connect to reader '{self.name}': {exc}"
                    ) from exc
        raise PCSCReaderError(f"Reader '{self.name}' is no longer connected")

    @staticmethod
    def _transmit(connection, apdu: List[int]) -> Tuple[List[int], int, int]:
        return connection.transmit(apdu)

    # -- ISO 14443A --------------------------------------------------------
    def get_uid(self) -> Optional[str]:
        """
        Read the ISO 14443A UID of the card on this reader.

        Returns ``None`` when the reader is empty or the card does not answer
        to the GET DATA command (never a fabricated value).
        """
        with self._lock:
            connection = None
            try:
                connection = self._connect()
            except PCSCReaderError:
                return None
            try:
                data, sw1, sw2 = self._transmit(connection, _GET_DATA_APDU)
                if (sw1, sw2) != _SW_SUCCESS or not data:
                    return None
                return _format_uid(bytes(data))
            except Exception:
                return None
            finally:
                self._safe_disconnect(connection)

    def get_atr(self) -> Optional[str]:
        """Return the ISO 14443A ATR of the connected card, if any."""
        with self._lock:
            try:
                connection = self._connect()
            except PCSCReaderError:
                return None
            try:
                atr = connection.getATR()
                return _format_uid(bytes(atr)) if atr else None
            except Exception:
                return None
            finally:
                self._safe_disconnect(connection)

    # -- ISO 15693 ---------------------------------------------------------
    def _iso15693_frame(self, payload: bytes, append_crc: bool = True) -> List[int]:
        frame = iso15693_append_crc(payload) if append_crc else payload
        return list(frame)

    def transparent_exchange(
        self, frame: List[int], append_crc: bool = True
    ) -> bytes:
        """
        Send an ISO 15693 frame using the standard PC/SC transparent
        pseudo-APDU (``FF 00 00 00 <Lc> <frame>``) used by transparent-mode
        readers such as the ACS ACR1252 / ACR122U.
        """
        if append_crc:
            frame = list(iso15693_append_crc(bytes(frame)))
        apdu = [0xFF, 0x00, 0x00, 0x00, len(frame)] + frame
        with self._lock:
            connection = None
            try:
                connection = self._connect()
            except PCSCReaderError:
                return b""
            try:
                data, sw1, sw2 = self._transmit(connection, apdu)
                if (sw1, sw2) != _SW_SUCCESS:
                    return b""
                return bytes(data)
            except Exception:
                return b""
            finally:
                self._safe_disconnect(connection)

    def inventory(self, append_crc: bool = True) -> Optional[str]:
        """ISO 15693 inventory -> tag UID (or ``None`` when no tag is present)."""
        frame = self._iso15693_frame(
            bytes([_FLAG_INVENTORY_SINGLE_SLOT, _ISO15693_INVENTORY]), append_crc
        )
        resp = self.transparent_exchange(frame, append_crc=False)
        if len(resp) < 10:
            return None
        # resp = [flags, DSFID, UID(8), ...] -> UID follows the DSFID byte.
        uid = resp[2:10]
        return _format_uid(uid)

    def get_system_info(
        self, uid: str, append_crc: bool = True
    ) -> Optional[Dict[str, Optional[int]]]:
        """Read DSFID + AFI for a specific ISO 15693 tag (addressed mode)."""
        uid_bytes = bytes(int(b, 16) for b in uid.split(":"))
        payload = bytes([_FLAG_HIGH_DATA_RATE | _FLAG_ADDRESSED, _ISO15693_GET_SYSTEM_INFO]) + uid_bytes
        frame = self._iso15693_frame(payload, append_crc)
        resp = self.transparent_exchange(frame, append_crc=False)
        # resp = [flags, infoFlags, DSFID, AFI, memHi, memLo, ICref, ...]
        if len(resp) < 4 or (resp[0] & _FLAG_ERROR):
            return None
        return {"dsfid": resp[2], "afi": resp[3]}

    def read_book_tag(self, append_crc: bool = True) -> Optional[BookTag]:
        """Complete ISO 15693 read: inventory the tag, then read DSFID/AFI."""
        uid = self.inventory(append_crc=append_crc)
        if not uid:
            return None
        info = self.get_system_info(uid, append_crc=append_crc)
        if not info:
            return BookTag(uid=uid)
        return BookTag(uid=uid, afi=info.get("afi"), dsfid=info.get("dsfid"))

    def write_afi(self, uid: str, afi: int, append_crc: bool = True) -> bool:
        """ISO 15693 Write AFI (0x27) for a specific tag. Returns success."""
        if not 0 <= afi <= 0xFF:
            raise PCSCReaderError(f"Invalid AFI value: {afi}")
        uid_bytes = bytes(int(b, 16) for b in uid.split(":"))
        payload = (
            bytes([_FLAG_HIGH_DATA_RATE | _FLAG_ADDRESSED, _ISO15693_WRITE_AFI, afi])
            + uid_bytes
        )
        frame = self._iso15693_frame(payload, append_crc)
        resp = self.transparent_exchange(frame, append_crc=False)
        if not resp:
            return False
        return (resp[0] & _FLAG_ERROR) == 0

    # -- lifecycle ---------------------------------------------------------
    @staticmethod
    def _safe_disconnect(connection) -> None:
        try:
            connection.disconnect()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Role resolution
# --------------------------------------------------------------------------
def match_reader(readers: List[str], pattern: str) -> Optional[str]:
    """Case-insensitive substring match, falling back to ``None``."""
    if not pattern:
        return None
    needle = pattern.strip().lower()
    for name in readers:
        if needle in name.lower():
            return name
    return None


def resolve_reader_roles(
    readers: List[str],
    card_match: str,
    book_match: str,
    gate_match: str,
) -> Dict[str, Optional[str]]:
    """
    Map physical readers to kiosk roles.

    Explicit substring matches always win.  Any unassigned role falls back to
    the first reader that is not already claimed, which lets a single
    dual-protocol reader (ACR1252) serve the kiosk on a bench setup.
    """
    roles: Dict[str, Optional[str]] = {"card": None, "book": None, "gate": None}
    claimed: set = set()

    for role, pattern in (
        ("card", card_match),
        ("book", book_match),
        ("gate", gate_match),
    ):
        matched = match_reader(readers, pattern)
        if matched and matched not in claimed:
            roles[role] = matched
            claimed.add(matched)

    # Fallbacks: card reader is the most critical, book pad next.
    for role in ("card", "book", "gate"):
        if roles[role] is None:
            for name in readers:
                if name not in claimed:
                    roles[role] = name
                    claimed.add(name)
                    break

    return roles
