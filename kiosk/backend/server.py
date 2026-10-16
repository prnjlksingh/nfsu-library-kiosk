"""
NFSU Central Library Self-Service Kiosk - FastAPI Full-Stack Server
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Serves the kiosk UI and exposes the circulation + hardware APIs.  All
circulation work is delegated to the live Koha 26 SIP2 server and all
hardware work to the real PC/SC readers - there is no emulator and no
simulated pad.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import config, settings
from .sip2_client import sip_client
from .rfid_bridge import rfid_bridge
from .biometrics import biometrics


# ----------------- WebSocket connection manager ----------------- #
class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = WebSocketManager()


# ----------------- Background workers ----------------- #
async def heartbeat_worker():
    """Poll Koha for SC Status so the header badge reflects real health."""
    while True:
        try:
            await asyncio.sleep(config.reconnect_delay_seconds)
            if not sip_client.is_connected:
                await sip_client.connect()
            else:
                await sip_client.heartbeat()
            await ws_manager.broadcast({
                "type": "SIP2_TELEMETRY",
                "data": sip_client.get_telemetry(),
            })
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def hardware_status_worker():
    """Push periodic hardware + Koha telemetry to connected kiosk UIs."""
    while True:
        try:
            await asyncio.sleep(15)
            await ws_manager.broadcast({
                "type": "HARDWARE_STATUS",
                "data": rfid_bridge.get_hardware_status(),
            })
        except asyncio.CancelledError:
            break
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[INIT] Connecting SIP2 client to Koha at {config.sip_host}:{config.sip_port} ...")
    await sip_client.connect()

    async def bridge_event_handler(event: Dict[str, Any]):
        await ws_manager.broadcast(event)

    rfid_bridge.add_listener(bridge_event_handler)

    hb_task = asyncio.create_task(heartbeat_worker())
    hw_status_task = asyncio.create_task(hardware_status_worker())
    monitor_task = asyncio.create_task(rfid_bridge.hardware_monitor_loop())

    yield

    for task in (hb_task, hw_status_task, monitor_task):
        task.cancel()
    await sip_client.disconnect()
    print("[SHUTDOWN] Kiosk services terminated.")


app = FastAPI(
    title="NFSU Central Library Self-Service Kiosk API",
    description="Koha 26 SIP2 + RFID hardware integration (Problem Statement 2)",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------- Request models ----------------- #
class PatronQuery(BaseModel):
    patron_id: str


class CheckoutRequest(BaseModel):
    patron_id: str
    item_barcode: str


class CheckinRequest(BaseModel):
    item_barcode: str


class RenewRequest(BaseModel):
    patron_id: str
    item_barcode: str


class RawSIPRequest(BaseModel):
    raw_packet: str


class ConfigSwitchRequest(BaseModel):
    host: str
    port: int


class VerifyFaceRequest(BaseModel):
    session_id: str
    nonce: Optional[str] = None
    claimed_patron_id: Optional[str] = None
    metrics: Dict[str, Any] = {}


# ----------------- WebSocket ----------------- #
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({
            "type": "INIT_STATE",
            "telemetry": sip_client.get_telemetry(),
            "pad_state": rfid_bridge.get_pad_state(),
            "hardware": rfid_bridge.get_hardware_status(),
            "timestamp": datetime.now().isoformat(),
        })
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "PING":
                await websocket.send_json({
                    "type": "PONG",
                    "timestamp": datetime.now().isoformat(),
                })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ----------------- Health ----------------- #
@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "koha": sip_client.get_telemetry(),
        "hardware": rfid_bridge.get_hardware_status(),
        "max_books_allowed": config.max_books_allowed,
    }


# ----------------- Circulation (SIP2) ----------------- #
@app.post("/api/circulation/patron-info")
async def api_patron_info(payload: PatronQuery):
    """SIP2 63 -> 64 patron lookup: charged count and AU barcodes."""
    res = await sip_client.get_patron_info(payload.patron_id)
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return res


@app.get("/api/circulation/item-info")
async def api_item_info(barcode: str = Query(..., description="Item barcode")):
    """SIP2 17 -> 18 item lookup from live Koha."""
    return await sip_client.get_item_info(barcode)


@app.post("/api/circulation/checkout")
async def api_checkout(payload: CheckoutRequest):
    """
    SIP2 11 -> 12 issue.

    Two-phase commit: the book tag AFI is disarmed (0xC2) only *after* Koha
    confirms the checkout with OK=1.
    """
    sip_resp = await sip_client.checkout(payload.patron_id, payload.item_barcode)

    if sip_resp.get("ok"):
        afi_res = await rfid_bridge.write_book_afi(
            payload.item_barcode, settings.AFI_DISARMED
        )
        sip_resp["rfid_afi_update"] = afi_res
        if afi_res.get("success"):
            sip_resp["two_phase_commit"] = "SUCCESS: tag disarmed (AFI 0xC2 / EAS off)"
        else:
            sip_resp["two_phase_commit"] = (
                f"CHECKOUT OK, TAG WRITE FAILED: {afi_res.get('error')}"
            )
    else:
        sip_resp["two_phase_commit"] = "BLOCKED: tag remains armed (AFI 0x07 / EAS on)"

    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp


@app.post("/api/circulation/checkin")
async def api_checkin(payload: CheckinRequest):
    """
    SIP2 09 -> 10 check-in.

    Two-phase commit: the book tag AFI is re-armed (0x07) after Koha confirms.
    """
    sip_resp = await sip_client.checkin(payload.item_barcode)

    if sip_resp.get("ok"):
        afi_res = await rfid_bridge.write_book_afi(
            payload.item_barcode, settings.AFI_ARMED
        )
        sip_resp["rfid_afi_update"] = afi_res
        if afi_res.get("success"):
            sip_resp["two_phase_commit"] = "SUCCESS: tag re-armed (AFI 0x07 / EAS on)"
        else:
            sip_resp["two_phase_commit"] = (
                f"RETURN OK, TAG WRITE FAILED: {afi_res.get('error')}"
            )
    else:
        sip_resp["two_phase_commit"] = "FAILED: return rejected by Koha"

    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp


@app.post("/api/circulation/renew")
async def api_renew(payload: RenewRequest):
    """SIP2 29 -> 30 renewal."""
    sip_resp = await sip_client.renew(payload.patron_id, payload.item_barcode)
    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp


# ----------------- Hardware ----------------- #
@app.get("/api/hardware/status")
async def api_hardware_status():
    return rfid_bridge.get_hardware_status()


@app.get("/api/hardware/pad-state")
async def api_get_pad_state():
    return rfid_bridge.get_pad_state()


@app.post("/api/hardware/scan-book")
async def api_scan_book(barcode: str = Body(..., embed=True)):
    """Register a book barcode read by the HID/serial barcode scanner."""
    res = await rfid_bridge.scan_book(barcode)
    await ws_manager.broadcast({"type": "PAD_BOOKS_UPDATED", "data": rfid_bridge.get_pad_state()})
    return res


@app.post("/api/hardware/scan-patron")
async def api_scan_patron(barcode: str = Body(..., embed=True)):
    """Register a patron card barcode read by the HID/serial barcode scanner."""
    return await rfid_bridge.scan_patron(barcode)


@app.post("/api/hardware/clear-scanned")
async def api_clear_scanned():
    """Clear barcode-scanner queue entries (RFID pad state follows live hardware)."""
    return await rfid_bridge.clear_scanned()


@app.post("/api/hardware/reload-map")
async def api_reload_map():
    """Reload hardware_map.json without restarting the kiosk."""
    return rfid_bridge.reload_hardware_map()


# ----------------- Biometrics ----------------- #
@app.post("/api/biometrics/challenge")
async def api_bio_challenge():
    """Issue a one-time liveness challenge (nonce + thresholds)."""
    return biometrics.create_liveness_challenge()


@app.post("/api/biometrics/verify")
async def api_bio_verify(payload: VerifyFaceRequest):
    """
    Validate the measurements reported by the browser's camera analysis and,
    if they pass, bind the liveness check to the claimed patron.
    """
    res = biometrics.verify_liveness_and_authenticate(
        session_id=payload.session_id,
        nonce=payload.nonce,
        claimed_patron_id=payload.claimed_patron_id,
        metrics=payload.metrics,
    )
    if res.get("authenticated"):
        await rfid_bridge.authenticate_patron(res["patron_id"], method="face")
    return res


# ----------------- SIP2 diagnostics / testing tool ----------------- #
@app.get("/api/sip2/telemetry")
async def api_sip_telemetry():
    return sip_client.get_telemetry()


@app.post("/api/sip2/send-raw")
async def api_sip_send_raw(payload: RawSIPRequest):
    """Send an arbitrary SIP2 frame (AY/AZ are finalised automatically)."""
    raw = payload.raw_packet.strip()
    if "AZ" not in raw:
        raw = sip_client.builder.finalize(raw)
    elif not raw.endswith("\r"):
        raw += "\r"
    return await sip_client.send_raw(raw)


@app.post("/api/sip2/reconnect")
async def api_sip_reconnect(payload: ConfigSwitchRequest):
    """Point the kiosk at a different Koha SIP2 endpoint."""
    await sip_client.disconnect()
    sip_client.host = payload.host
    sip_client.port = payload.port
    ok = await sip_client.connect()
    return {"success": ok, "telemetry": sip_client.get_telemetry()}


# ----------------- Static frontend ----------------- #
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
