"""
NFSU Central Library Self-Service Kiosk - SIP2 Client Engine
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Asynchronous TCP/TLS SIP2 client with:
- Login (93/94) handshake and SC Status (99/98) heartbeat
- Sequence numbers (AY) and 16-bit two's-complement checksums (AZ)
- Round-trip latency tracking and automatic reconnect
- Thread/task-safe request serialisation

This client only ever talks to a real SIP2 server.  There is no emulator or
offline fallback: when Koha is unreachable the kiosk reports it honestly.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from .sip2_protocol import SIP2MessageBuilder, SIP2MessageParser
from .config import config


class SIP2Client:
    """Async TCP client communicating with the Koha 26 SIP2 server."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or config.sip_host
        self.port = port or config.sip_port
        self.user = config.sip_user
        self.password = config.sip_pass
        self.location = config.sip_location
        self.institution = config.institution_id

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.builder = SIP2MessageBuilder(sequence=1)

        self.is_connected = False
        self.is_logged_in = False
        self.last_latency_ms: float = 0.0
        self.last_heartbeat: Optional[datetime] = None
        self.last_status: Dict[str, Any] = {}
        self.last_error: Optional[str] = None

        self._lock = asyncio.Lock()
        self.on_state_change_callbacks: list = []

    # -- observers ---------------------------------------------------------
    def register_state_callback(self, cb: Callable):
        self.on_state_change_callbacks.append(cb)

    async def _notify_state(self):
        state = self.get_telemetry()
        for cb in self.on_state_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(state)
                else:
                    cb(state)
            except Exception:
                pass

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry for the KOHA status badge and the SIP testing tool."""
        return {
            "is_connected": self.is_connected,
            "is_logged_in": self.is_logged_in,
            "host": self.host,
            "port": self.port,
            "latency_ms": round(self.last_latency_ms, 2),
            "institution_id": self.institution,
            "location": self.location,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "account": self.user or "(not configured)",
            "configured": bool(self.user and self.password),
            "last_error": self.last_error,
            "supported_messages": self.last_status.get("fields", {}).get("BX", ""),
            "online_status": self.last_status.get("online_status", ""),
        }

    # -- connection --------------------------------------------------------
    async def _connect_locked(self, timeout: float = 4.0) -> bool:
        if self.is_connected and self.writer:
            return True

        if not self.user or not self.password:
            self.last_error = (
                "Koha SIP2 credentials are not configured. Set KOHA_SIP_USER and "
                "KOHA_SIP_PASS (or pass them on the command line)."
            )
            self.is_connected = False
            self.is_logged_in = False
            await self._notify_state()
            return False

        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=timeout
            )
        except Exception as exc:
            self.last_error = f"TCP connect to {self.host}:{self.port} failed: {exc}"
            self.is_connected = False
            self.is_logged_in = False
            await self._notify_state()
            return False

        self.is_connected = True

        try:
            login_msg = self.builder.build_93_login(
                user=self.user, pwd=self.password, location=self.location
            )
            login_res = await self._send_raw_locked(login_msg, timeout=config.timeout_seconds)
            if not login_res or not login_res.get("ok"):
                self.last_error = f"93 Login rejected by Koha: {login_res.get('screen_message') or login_res}"
                await self._teardown_locked()
                self.is_connected = False
                self.is_logged_in = False
                await self._notify_state()
                return False

            self.is_logged_in = True

            status_res = await self._send_raw_locked(
                self.builder.build_99_sc_status(), timeout=config.timeout_seconds
            )
            if status_res and status_res.get("command") == "98":
                self.last_status = status_res
                self.last_heartbeat = datetime.now()

            self.last_error = None
            await self._notify_state()
            return True
        except Exception as exc:
            self.last_error = f"SIP2 handshake failed: {exc}"
            await self._teardown_locked()
            self.is_connected = False
            self.is_logged_in = False
            await self._notify_state()
            return False

    async def connect(self, timeout: float = 4.0) -> bool:
        async with self._lock:
            return await self._connect_locked(timeout=timeout)

    async def _teardown_locked(self):
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.writer = None
        self.reader = None

    async def disconnect(self):
        async with self._lock:
            await self._teardown_locked()
            self.is_connected = False
            self.is_logged_in = False
            await self._notify_state()

    # -- transport ---------------------------------------------------------
    async def _send_raw_locked(self, raw_msg: str, timeout: float = 3.0) -> Dict[str, Any]:
        if not self.writer or not self.reader:
            return {"error": "Not connected to Koha server", "ok": False}

        t_start = time.perf_counter()
        try:
            self.writer.write(raw_msg.encode("ascii", errors="replace"))
            await self.writer.drain()

            response_data = bytearray()
            while True:
                chunk = await asyncio.wait_for(self.reader.read(1024), timeout=timeout)
                if not chunk:
                    break
                response_data.extend(chunk)
                if b"\r" in chunk or b"\n" in chunk:
                    break

            if not response_data:
                await self._teardown_locked()
                self.is_connected = False
                self.is_logged_in = False
                return {"error": "Koha closed the connection", "ok": False}

            t_elapsed = (time.perf_counter() - t_start) * 1000.0
            self.last_latency_ms = t_elapsed

            response_str = response_data.decode("ascii", errors="replace")
            parsed = SIP2MessageParser.parse(response_str)
            parsed["latency_ms"] = round(t_elapsed, 2)
            parsed["request_sent"] = raw_msg.strip("\r\n")
            return parsed

        except asyncio.TimeoutError:
            self.last_error = "Timed out waiting for a Koha SIP2 response"
            self.is_connected = False
            self.is_logged_in = False
            await self._teardown_locked()
            return {"error": self.last_error, "ok": False}
        except Exception as exc:
            self.last_error = f"Socket transmission error: {exc}"
            self.is_connected = False
            self.is_logged_in = False
            await self._teardown_locked()
            return {"error": self.last_error, "ok": False}

    async def send_raw(self, raw_msg: str) -> Dict[str, Any]:
        """Send an arbitrary SIP2 message and parse the response."""
        async with self._lock:
            if not self.is_connected:
                if not await self._connect_locked():
                    return {"error": self.last_error or "Koha server unreachable", "ok": False}
            res = await self._send_raw_locked(raw_msg)
            if "error" in res and self.writer is None:
                # Connection dropped: reconnect once and retry.
                if await self._connect_locked():
                    res = await self._send_raw_locked(raw_msg)
            return res

    # -- circulation -------------------------------------------------------
    async def get_patron_info(self, patron_id: str, patron_pwd: str = "") -> Dict[str, Any]:
        msg = self.builder.build_63_patron_info(
            patron_id=patron_id,
            institution_id=self.institution,
            patron_pwd=patron_pwd,
            terminal_pwd=config.terminal_password,
        )
        return await self.send_raw(msg)

    async def get_item_info(self, barcode: str) -> Dict[str, Any]:
        msg = self.builder.build_17_item_info(
            item_barcode=barcode,
            institution_id=self.institution,
            terminal_pwd=config.terminal_password,
        )
        return await self.send_raw(msg)

    async def checkout(self, patron_id: str, barcode: str) -> Dict[str, Any]:
        msg = self.builder.build_11_checkout(
            patron_id=patron_id,
            item_barcode=barcode,
            institution_id=self.institution,
            terminal_pwd=config.terminal_password,
        )
        return await self.send_raw(msg)

    async def checkin(self, barcode: str) -> Dict[str, Any]:
        msg = self.builder.build_09_checkin(
            item_barcode=barcode,
            institution_id=self.institution,
            location=self.location,
            terminal_pwd=config.terminal_password,
        )
        return await self.send_raw(msg)

    async def renew(self, patron_id: str, barcode: str) -> Dict[str, Any]:
        msg = self.builder.build_29_renew(
            patron_id=patron_id,
            item_barcode=barcode,
            institution_id=self.institution,
            terminal_pwd=config.terminal_password,
        )
        return await self.send_raw(msg)

    async def heartbeat(self) -> Dict[str, Any]:
        msg = self.builder.build_99_sc_status()
        res = await self.send_raw(msg)
        if res.get("command") == "98":
            self.last_status = res
            self.last_heartbeat = datetime.now()
        await self._notify_state()
        return res


# Singleton client instance
sip_client = SIP2Client()
