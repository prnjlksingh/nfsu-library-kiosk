"""
NFSU Central Library Self-Service Kiosk - FastAPI Full-Stack Server
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)
"""

import os
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import config, settings
from .sip2_protocol import SIP2MessageBuilder, SIP2MessageParser
from .sip2_client import sip_client
from .rfid_bridge import rfid_bridge
from .biometrics import biometrics

# Global WebSocket connection manager
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

# Background Heartbeat Task
async def heartbeat_worker():
    while True:
        try:
            await asyncio.sleep(20)
            if sip_client.is_connected:
                await sip_client.heartbeat()
                telemetry = sip_client.get_telemetry()
                await ws_manager.broadcast({
                    "type": "SIP2_TELEMETRY",
                    "data": telemetry
                })
        except asyncio.CancelledError:
            break
        except Exception as e:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Connect SIP2 Client to Live Koha 26 Server
    print(f"[INIT] Connecting SIP2 Client to Live Koha at {config.sip_host}:{config.sip_port}...")
    await sip_client.connect()

    # 2. Hook RFID Bridge events to WebSocket broadcaster
    async def bridge_event_handler(event: Dict[str, Any]):
        await ws_manager.broadcast(event)
    rfid_bridge.add_listener(bridge_event_handler)

    # 3. Start Heartbeat & Hardware poller workers
    hb_task = asyncio.create_task(heartbeat_worker())
    hw_task = asyncio.create_task(rfid_bridge.hardware_monitor_loop())

    yield

    # Teardown
    hb_task.cancel()
    hw_task.cancel()
    await sip_client.disconnect()
    print("[SHUTDOWN] Kiosk services terminated.")

app = FastAPI(
    title="NFSU Central Library Self-Service Kiosk API",
    description="Koha 26 SIP2 Full-Stack Integration (Problem Statement 2)",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Models ----------------- #
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
    challenge_passed: bool
    claimed_patron_id: Optional[str] = None

# ----------------- WebSocket Endpoint ----------------- #
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial telemetry & pad state immediately
        await websocket.send_json({
            "type": "INIT_STATE",
            "telemetry": sip_client.get_telemetry(),
            "pad_state": rfid_bridge.get_pad_state(),
            "timestamp": datetime.now().isoformat()
        })
        while True:
            # Handle incoming ping / client actions if any
            data = await websocket.receive_json()
            msg_type = data.get("action")
            if msg_type == "PING":
                await websocket.send_json({"type": "PONG", "timestamp": datetime.now().isoformat()})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# ----------------- Circulation APIs (SIP2) ----------------- #
@app.post("/api/circulation/patron-info")
async def api_patron_info(payload: PatronQuery):
    """
    SIP2 63 -> 64 Patron Info
    Returns charged items count (How many Books issued) & AU barcodes.
    """
    res = await sip_client.get_patron_info(payload.patron_id)
    
    # Broadcast telemetry
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return res

@app.get("/api/circulation/item-info")
async def api_item_info(barcode: str = Query(..., description="Item Barcode or Tag UID")):
    """SIP2 17 -> 18 Item Information lookup from Live Koha 26"""
    res = await sip_client.get_item_info(barcode)
    return res

@app.post("/api/circulation/checkout")
async def api_checkout(payload: CheckoutRequest):
    """
    SIP2 11 -> 12 Issue / Checkout on Live Koha 26
    Strict 2-Phase Commit: Only disarms AFI to 0xC2 (EAS off) AFTER Koha responds with 121 (OK=1).
    """
    sip_resp = await sip_client.checkout(payload.patron_id, payload.item_barcode)
    
    # Check Koha response OK flag (121)
    if sip_resp.get("ok"):
        # TWO-PHASE COMMIT: Disarm RFID Tag AFI to 0xC2
        afi_res = await rfid_bridge.write_book_afi(payload.item_barcode, settings.AFI_DISARMED)
        sip_resp["rfid_afi_update"] = afi_res
        sip_resp["two_phase_commit"] = "SUCCESS: Tag Disarmed (AFI: 0xC2 / EAS OFF - Live Koha)"
    else:
        sip_resp["two_phase_commit"] = "BLOCKED: Tag Remains Armed (AFI: 0x07 / EAS ON)"

    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp

@app.post("/api/circulation/checkin")
async def api_checkin(payload: CheckinRequest):
    """
    SIP2 09 -> 10 Return / Check-in on Live Koha 26
    Strict 2-Phase Commit: Re-arms AFI to 0x07 (EAS on) immediately upon Koha 101 confirmation.
    """
    sip_resp = await sip_client.checkin(payload.item_barcode)
    
    if sip_resp.get("ok"):
        # TWO-PHASE COMMIT: Re-arm RFID Tag AFI to 0x07
        afi_res = await rfid_bridge.write_book_afi(payload.item_barcode, settings.AFI_ARMED)
        sip_resp["rfid_afi_update"] = afi_res
        sip_resp["two_phase_commit"] = "SUCCESS: Tag Re-armed (AFI: 0x07 / EAS ON - Live Koha)"
    else:
        sip_resp["two_phase_commit"] = "FAILED: Return Rejected by Koha"

    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp

@app.post("/api/circulation/renew")
async def api_renew(payload: RenewRequest):
    """SIP2 29 -> 30 Renewal on Live Koha 26"""
    sip_resp = await sip_client.renew(payload.patron_id, payload.item_barcode)
    await ws_manager.broadcast({"type": "CIRCULATION_TRANSACTION", "data": sip_resp})
    await ws_manager.broadcast({"type": "SIP2_TELEMETRY", "data": sip_client.get_telemetry()})
    return sip_resp

# ----------------- Hardware Pad & Simulator APIs ----------------- #
@app.get("/api/hardware/pad-state")
async def api_get_pad_state():
    return rfid_bridge.get_pad_state()

@app.post("/api/hardware/place-book")
async def api_place_book(
    barcode: str = Body(..., embed=True),
    title: Optional[str] = Body(None, embed=True)
):
    return await rfid_bridge.place_book(barcode, custom_title=title)

@app.post("/api/hardware/place-two-books")
async def api_place_two_books(
    barcode1: str = Body("NFSU-BK-104", embed=True),
    barcode2: str = Body("NFSU-BK-105", embed=True)
):
    """1-Click Multi-Tag Anti-Collision Demo (2 Books on Pad Simultaneously)"""
    return await rfid_bridge.place_two_books(barcode1, barcode2)

@app.post("/api/hardware/remove-books")
async def api_remove_books():
    return await rfid_bridge.remove_books()

@app.post("/api/hardware/tap-card")
async def api_tap_card(card_or_uid: str = Body(..., embed=True)):
    return await rfid_bridge.tap_patron_card(card_or_uid)

@app.post("/api/hardware/remove-card")
async def api_remove_card():
    return await rfid_bridge.remove_patron_card()

@app.post("/api/hardware/pass-gate")
async def api_pass_gate(barcode: str = Body(..., embed=True)):
    """Triggers Security Gate Walk-Through & Buzzer Evaluation"""
    return await rfid_bridge.pass_book_through_gate(barcode)

@app.post("/api/hardware/write-afi")
async def api_write_afi(barcode: str = Body(..., embed=True), afi: str = Body(..., embed=True)):
    return await rfid_bridge.write_book_afi(barcode, afi)

# ----------------- Biometric Face & Liveness APIs ----------------- #
@app.post("/api/biometrics/challenge")
async def api_bio_challenge():
    """Generates an interactive liveness challenge session"""
    return biometrics.create_liveness_challenge()

@app.post("/api/biometrics/verify")
async def api_bio_verify(payload: VerifyFaceRequest):
    """
    Ephemerally verifies liveness and matches face token in RAM.
    Zero biometric retention.
    """
    res = biometrics.verify_liveness_and_authenticate(
        session_id=payload.session_id,
        challenge_passed=payload.challenge_passed,
        claimed_patron_id=payload.claimed_patron_id
    )
    if res.get("authenticated"):
        # Auto-tap card into hardware pad
        await rfid_bridge.tap_patron_card(res["patron_id"])
    return res

# ----------------- Diagnostics & SIP2 Testing Tool APIs ----------------- #
@app.get("/api/sip2/telemetry")
async def api_sip_telemetry():
    return sip_client.get_telemetry()

@app.post("/api/sip2/send-raw")
async def api_sip_send_raw(payload: RawSIPRequest):
    """Send arbitrary raw SIP2 string with sequence & checksum calculation"""
    raw = payload.raw_packet.strip()
    # If the user did not include AY/AZ, automatically finalize it
    if "AZ" not in raw:
        raw = sip_client.builder.finalize(raw)
    else:
        if not raw.endswith("\r"):
            raw += "\r"
    resp = await sip_client.send_raw(raw)
    return resp

@app.post("/api/sip2/reconnect")
async def api_sip_reconnect(payload: ConfigSwitchRequest):
    """Switch Koha SIP2 target host and port"""
    await sip_client.disconnect()
    sip_client.host = payload.host
    sip_client.port = payload.port
    sip_client.is_emulator = (payload.host in ("127.0.0.1", "localhost") and payload.port == 6001)
    ok = await sip_client.connect()
    return {
        "success": ok,
        "telemetry": sip_client.get_telemetry()
    }

@app.get("/api/sip2/transactions")
async def api_sip_transactions():
    """Audit log of all inbound and outbound SIP2 packets"""
    return emulator.transaction_log[-100:]

@app.post("/api/emulator/reset")
async def api_emulator_reset():
    """Reset dataset to initial pristine demo state"""
    emulator.reset_dataset()
    await rfid_bridge.remove_books()
    await rfid_bridge.remove_patron_card()
    return {"success": True, "message": "NFSU sample patrons and books restored to default demo state"}

@app.get("/api/sip2/sipconfig-xml")
async def api_sipconfig_xml():
    """Official Koha 26 SIPconfig.xml least-privilege configuration template"""
    xml_content = f"""<!-- Koha 26 SIPconfig.xml - NFSU Central Library Kiosk Integration -->
<!-- MANDATORY LEAST-PRIVILEGE AUDIT: Only 'circulate' permission enabled. NEVER 'superlibrarian' -->
<server-params>
    <institution id="{config.institution_id}" implementation="Koha">
        <policy checkin="true" checkout="true" renewal="true" status="true" />
        <user id="{config.sip_user}" password="{config.sip_pass}">
            <!-- Least-Privilege Koha Security Group: circulate_remaining_permissions ONLY -->
            <permissions circulate="true" parameters="false" superlibrarian="false" tools="false" />
        </user>
    </institution>
    <service host="0.0.0.0" port="{config.sip_port}" transport="tcp" max-clients="20" timeout="30" />
</server-params>
"""
    return HTMLResponse(content=xml_content, media_type="application/xml")

# ----------------- Static Files & Frontend Mount ----------------- #
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
