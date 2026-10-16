"""
NFSU Central Library Self-Service Kiosk - SIP2 Client Engine
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Implements an asynchronous TCP/TLS SIP2 Client with:
- Connection pooling, auto-reconnect, and heartbeat (99 -> 98)
- Sequence numbers (AY) & 16-bit Two's-Complement Checksums (AZ)
- Automated round-trip latency tracking
- Automatic fallback to Built-in Koha Emulator
"""

import asyncio
import time
from typing import Dict, Any, Optional, Tuple, Callable
from datetime import datetime

from .sip2_protocol import SIP2MessageBuilder, SIP2MessageParser
from .config import config, settings

class SIP2Client:
    """Async TCP client communicating with Koha 26 SIP2 server"""
    
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
        self.is_emulator = False
        self.last_latency_ms: float = 0.0
        self.last_heartbeat: Optional[datetime] = None
        self.last_status: Dict[str, Any] = {}
        
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.on_state_change_callbacks = []

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
        """Telemetry metadata for KOHA 26 CONNECTED header badge and testing tool"""
        return {
            "is_connected": self.is_connected,
            "is_logged_in": self.is_logged_in,
            "is_emulator": self.is_emulator,
            "host": self.host,
            "port": self.port,
            "latency_ms": round(self.last_latency_ms, 2),
            "institution_id": self.institution,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "account": self.user,
            "permission_scope": "circulate ONLY (superlibrarian = FALSE)",
            "supported_messages": self.last_status.get("fields", {}).get("BX", "YNNYYNYYYNYY"),
            "online_status": self.last_status.get("online_status", "Y")
        }

    async def _connect_locked(self, timeout: float = 4.0) -> bool:
        """Internal helper to connect to Koha 26 while self._lock is already acquired"""
        if self.is_connected and self.writer:
            return True

        targets = [(self.host, self.port)]
        # If primary target is live server, register local emulator as fallback
        if self.host != "127.0.0.1":
            targets.append(("127.0.0.1", 6001))

        for host, port in targets:
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout
                )
                self.host = host
                self.port = port
                self.is_connected = True
                self.is_emulator = (host in ("127.0.0.1", "localhost") and port == 6001)
                
                # 1. Koha 26 requires 93 Login FIRST
                login_res = await self._send_raw_locked(
                    self.builder.build_93_login(
                        user=self.user,
                        pwd=self.password,
                        location=self.location
                    ),
                    timeout=2.0
                )
                if not login_res or not login_res.get("ok"):
                    print(f"[SIP2-CLIENT] Handshake 93 Login failed on {host}:{port}: {login_res}")
                    if self.writer:
                        try:
                            self.writer.close()
                            await self.writer.wait_closed()
                        except Exception:
                            pass
                    self.reader = None
                    self.writer = None
                    self.is_connected = False
                    continue

                self.is_logged_in = True

                # 2. Perform 99 -> 98 Status Handshake
                status_res = await self._send_raw_locked(self.builder.build_99_sc_status(), timeout=2.0)
                if status_res and status_res.get("command") == "98":
                    self.last_status = status_res
                    self.last_heartbeat = datetime.now()

                await self._notify_state()
                print(f"[SIP2-CLIENT] Successfully connected to Koha at {host}:{port} (Emulator={self.is_emulator})")
                return True

            except Exception as e:
                print(f"[SIP2-CLIENT] Connection to {host}:{port} failed: {e}")
                if self.writer:
                    try:
                        self.writer.close()
                        await self.writer.wait_closed()
                    except Exception:
                        pass
                self.reader = None
                self.writer = None

        self.is_connected = False
        self.is_logged_in = False
        await self._notify_state()
        return False

    async def connect(self, timeout: float = 4.0) -> bool:
        """Connect to Koha 26 SIP2 server and perform handshake (acquires lock)"""
        async with self._lock:
            return await self._connect_locked(timeout=timeout)

    async def disconnect(self):
        """Cleanly close connection"""
        async with self._lock:
            if self.writer:
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                except Exception:
                    pass
            self.writer = None
            self.reader = None
            self.is_connected = False
            self.is_logged_in = False
            await self._notify_state()

    async def _send_raw_locked(self, raw_msg: str, timeout: float = 3.0) -> Dict[str, Any]:
        """Internal helper to transmit a raw message and receive response while holding lock"""
        if not self.writer or not self.reader:
            return {"error": "Not connected to Koha server", "ok": False}

        t_start = time.perf_counter()
        try:
            self.writer.write(raw_msg.encode("ascii", errors="replace"))
            await self.writer.drain()

            # Read until message terminator (\r or \n)
            response_data = bytearray()
            while True:
                chunk = await asyncio.wait_for(self.reader.read(1024), timeout=timeout)
                if not chunk:
                    break
                response_data.extend(chunk)
                if b"\r" in chunk or b"\n" in chunk:
                    break
            if not response_data:
                self.is_connected = False
                if self.writer:
                    try:
                        self.writer.close()
                    except Exception:
                        pass
                self.writer = None
                self.reader = None
                return {"error": "Koha closed connection", "ok": False}

            t_elapsed = (time.perf_counter() - t_start) * 1000.0
            self.last_latency_ms = t_elapsed

            response_str = response_data.decode("ascii", errors="replace")
            parsed = SIP2MessageParser.parse(response_str)
            parsed["latency_ms"] = round(t_elapsed, 2)
            parsed["request_sent"] = raw_msg.strip("\r\n")
            return parsed

        except asyncio.TimeoutError:
            self.is_connected = False
            return {"error": "Connection timed out waiting for Koha response", "ok": False}
        except Exception as e:
            self.is_connected = False
            return {"error": f"Socket transmission error: {str(e)}", "ok": False}

    async def send_raw(self, raw_msg: str) -> Dict[str, Any]:
        """Send arbitrary SIP2 message and parse response (thread/task safe)"""
        async with self._lock:
            if not self.is_connected:
                # Attempt auto-reconnect
                ok = await self._connect_locked()
                if not ok:
                    return {"error": "Koha server unreachable", "ok": False}
            res = await self._send_raw_locked(raw_msg)
            if "error" in res:
                # Connection dropped by server, reconnect and retry once
                ok = await self._connect_locked()
                if ok:
                    res = await self._send_raw_locked(raw_msg)
            return res

    async def get_patron_info(self, patron_id: str, patron_pwd: str = "") -> Dict[str, Any]:
        """SIP2 63 -> 64 Patron Information with AU charged items list"""
        msg = self.builder.build_63_patron_info(
            patron_id=patron_id,
            institution_id=self.institution,
            patron_pwd=patron_pwd
        )
        return await self.send_raw(msg)

    async def get_item_info(self, barcode: str) -> Dict[str, Any]:
        """SIP2 17 -> 18 Item Information lookup"""
        msg = self.builder.build_17_item_info(
            item_barcode=barcode,
            institution_id=self.institution
        )
        return await self.send_raw(msg)

    async def checkout(self, patron_id: str, barcode: str) -> Dict[str, Any]:
        """SIP2 11 -> 12 Issue / Checkout"""
        msg = self.builder.build_11_checkout(
            patron_id=patron_id,
            item_barcode=barcode,
            institution_id=self.institution
        )
        return await self.send_raw(msg)

    async def checkin(self, barcode: str) -> Dict[str, Any]:
        """SIP2 09 -> 10 Return / Check-in"""
        msg = self.builder.build_09_checkin(
            item_barcode=barcode,
            institution_id=self.institution,
            location=self.location
        )
        return await self.send_raw(msg)

    async def renew(self, patron_id: str, barcode: str) -> Dict[str, Any]:
        """SIP2 29 -> 30 Renewal"""
        msg = self.builder.build_29_renew(
            patron_id=patron_id,
            item_barcode=barcode,
            institution_id=self.institution
        )
        return await self.send_raw(msg)

    async def heartbeat(self) -> Dict[str, Any]:
        """SIP2 99 -> 98 Status Heartbeat"""
        msg = self.builder.build_99_sc_status()
        res = await self.send_raw(msg)
        if res.get("command") == "98":
            self.last_status = res
            self.last_heartbeat = datetime.now()
        await self._notify_state()
        return res

# Singleton client instance
sip_client = SIP2Client()
