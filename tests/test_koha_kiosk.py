"""
Test suite for the NFSU Self-Service Library Kiosk (PS-2).

Covers the SIP2 protocol engine, the SIP2 client transport (against a local
throw-away stub - NOT a shipped emulator), hardware reader role resolution,
the hardware UID mapping helpers and the liveness validation rules.

Run:
    python tests/test_koha_kiosk.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kiosk.backend.sip2_protocol import (  # noqa: E402
    SIP2MessageBuilder,
    SIP2MessageParser,
    calculate_sip2_checksum,
    verify_sip2_checksum,
)
from kiosk.backend.pcsc_reader import resolve_reader_roles, crc16_iso15693  # noqa: E402
from kiosk.backend.biometrics import biometrics  # noqa: E402


def _finalize(body: str, seq: str = "1") -> str:
    if not body.endswith("|"):
        body += "|"
    msg = f"{body}AY{seq}AZ"
    return f"{msg}{calculate_sip2_checksum(msg)}\r"


# ----------------------------------------------------------------------
def test_sip2_protocol_checksum():
    builder = SIP2MessageBuilder(sequence=3)
    msg = builder.build_99_sc_status()
    assert "AY" in msg and "AZ" in msg
    valid, calc, prov = verify_sip2_checksum(msg)
    assert valid is True and calc == prov

    # Corrupt one byte and the checksum must fail.
    tampered = msg.replace("990030", "990031", 1)
    valid2, _, _ = verify_sip2_checksum(tampered)
    assert valid2 is False


def test_sip2_builder_shapes():
    b = SIP2MessageBuilder(sequence=1)
    login = b.build_93_login(user="rfid1", pwd="secret", location="NFSUGNR")
    assert "CNrfid1|" in login and "COsecret|" in login
    assert login.endswith("\r") and "AZ" in login

    patron = b.build_63_patron_info("ABC123", institution_id="NFSUGNR")
    # 63 + language(3) + date(18) + summary(10) then AO...
    assert patron.startswith("63001")
    assert "AONFSUGNR|AAABC123|" in patron
    summary = patron[2 + 3 + 18: 2 + 3 + 18 + 10]
    assert len(summary) == 10 and summary[2] == "Y"


def test_sip2_parser_patron_info():
    builder = SIP2MessageBuilder()
    # Craft a realistic 64 response by hand (charged count = 1, one AU field).
    now = "20260101    120000"
    body = (
        f"64              001{now}000000000001000000000000"
        f"AONFSUGNR|AAABC123|AEDr. Meera Nair|"
        f"BLY|CQY|BV0.00|AUB008925|AFWelcome|"
    )
    parsed = SIP2MessageParser.parse(_finalize(body, "1"))
    assert parsed["command"] == "64"
    assert parsed["charged_items_count"] == 1
    assert parsed["patron_name"] == "Dr. Meera Nair"
    assert parsed["charged_items"] == ["B008925"]
    assert parsed["checksum_valid"] is True


def test_sip2_parser_checkout_response():
    now = "20260101    120000"
    ok_body = f"1211NU{now}AONFSUGNR|AAABC123|ABB008925|AJSome Title|AH20260115    235900|OK|"
    parsed = SIP2MessageParser.parse(_finalize(ok_body, "5"))
    assert parsed["command"] == "12" and parsed["ok"] is True
    assert parsed["due_date"] == "20260115    235900"

    no_body = f"1200NU{now}AONFSUGNR|AAABC123|ABB008925|AFItem already checked out|"
    parsed_no = SIP2MessageParser.parse(_finalize(no_body, "6"))
    assert parsed_no["ok"] is False


# ----------------------------------------------------------------------
def test_reader_role_resolution():
    readers = ["HID OMNIKEY 5022 CL 0", "ACS ACR1252 1S CL Reader PICC 0",
               "ACS ACR1252 1S CL Reader PICC Gate 0"]
    roles = resolve_reader_roles(
        readers,
        card_match="OMNIKEY",
        book_match="PICC 0",
        gate_match="Gate",
    )
    assert roles["card"] == "HID OMNIKEY 5022 CL 0"
    assert roles["gate"] == "ACS ACR1252 1S CL Reader PICC Gate 0"
    assert roles["book"] is not None

    # With no explicit match, readers are assigned deterministically.
    auto = resolve_reader_roles(readers, "", "", "")
    assert auto["card"] == readers[0]
    assert len({v for v in auto.values() if v}) == 3


def test_iso15693_crc():
    # Known ISO 15693 inventory frame CRC for flags 0x26, cmd 0x01.
    frame = bytes([0x26, 0x01])
    crc = crc16_iso15693(frame)
    assert len(crc) == 2
    # CRC of the frame including its CRC must be zero.
    assert crc16_iso15693(frame + crc) == b"\x00\x00"


# ----------------------------------------------------------------------
def test_liveness_engine():
    challenge = biometrics.create_liveness_challenge()
    assert challenge["session_id"] and challenge["nonce"]

    # A bare "passed" boolean (no measurements) must NEVER authenticate.
    bare = biometrics.verify_liveness_and_authenticate(
        session_id=challenge["session_id"],
        challenge_passed=True,
        claimed_patron_id="ABC123",
    )
    assert bare["authenticated"] is False

    # A second chance with genuine, plausible measurements.
    challenge2 = biometrics.create_liveness_challenge()
    good_metrics = {
        "face_detected_frames": 40,
        "duration_ms": 3000,
        "motion_energy": 0.05,
        "blink_detected": True,
        "eye_closure_ratio": 0.2,
        "horizontal_shift": 0.2,   # generous for the "turn" challenges
    }
    # Force a challenge that any single turn satisfies for the assertion.
    for cid in ("blink", "turn_left", "turn_right", "blink_and_turn"):
        rec = biometrics.active_challenges.get(challenge2["session_id"])
        if rec:
            rec["challenge_id"] = cid
            rec["challenge"] = next(c for c in biometrics.CHALLENGES if c["id"] == cid)
            break

    metrics = dict(good_metrics)
    c = biometrics.active_challenges[challenge2["session_id"]]["challenge"]
    if c["requires"].get("turn") == "left":
        metrics["horizontal_shift"] = -0.2
    good = biometrics.verify_liveness_and_authenticate(
        session_id=challenge2["session_id"],
        nonce=challenge2["nonce"],
        claimed_patron_id="ABC123",
        metrics=metrics,
    )
    assert good["authenticated"] is True
    assert good["patron_id"] == "ABC123"

    # A static photo (no motion) must fail.
    challenge3 = biometrics.create_liveness_challenge()
    static = biometrics.verify_liveness_and_authenticate(
        session_id=challenge3["session_id"],
        nonce=challenge3["nonce"],
        claimed_patron_id="ABC123",
        metrics={"face_detected_frames": 40, "duration_ms": 3000, "motion_energy": 0.0},
    )
    assert static["authenticated"] is False


# ----------------------------------------------------------------------
async def _stub_sip_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """A minimal SIP2 responder used only to exercise the client transport."""
    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            req = data.decode("ascii", errors="replace").strip("\r\n")
            if req.startswith("93"):
                resp = _finalize("941", "1")
            elif req.startswith("99"):
                resp = _finalize("98YYYYNN030003202601011200002.00AONFSUGNR|BXYYYYYN|", "2")
            elif req.startswith("63"):
                now = "20260101    120000"
                resp = _finalize(
                    f"64              001{now}000000000001000000000000"
                    f"AONFSUGNR|AAABC123|AEDr. Meera Nair|BLY|CQY|BV0.00|AUB008925|AFWelcome|",
                    "3",
                )
            else:
                resp = _finalize("96", "4")
            writer.write(resp.encode("ascii"))
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def test_sip2_client_transport():
    from kiosk.backend.sip2_client import SIP2Client

    server = await asyncio.start_server(_stub_sip_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    client = SIP2Client(host="127.0.0.1", port=port)
    client.user = "rfid1"
    client.password = "secret"

    ok = await client.connect()
    assert ok is True and client.is_logged_in is True

    patron = await client.get_patron_info("ABC123")
    assert patron["command"] == "64"
    assert patron["charged_items_count"] == 1
    assert patron["patron_name"] == "Dr. Meera Nair"

    await client.disconnect()
    server.close()
    await server.wait_closed()


# ----------------------------------------------------------------------
def test_server_routes_registered():
    from kiosk.backend.server import app

    paths = {route.path for route in app.routes}
    for expected in (
        "/api/health",
        "/api/circulation/patron-info",
        "/api/circulation/checkout",
        "/api/circulation/checkin",
        "/api/circulation/renew",
        "/api/hardware/status",
        "/api/hardware/pad-state",
        "/api/hardware/scan-book",
        "/api/biometrics/challenge",
        "/api/biometrics/verify",
        "/api/sip2/send-raw",
    ):
        assert expected in paths, f"missing route {expected}"

    # The old simulation endpoints must be gone.
    for banned in ("/api/emulator/reset", "/api/hardware/place-book",
                   "/api/hardware/place-two-books", "/api/hardware/tap-card",
                   "/api/hardware/pass-gate", "/api/hardware/write-afi",
                   "/api/sip2/transactions"):
        assert banned not in paths, f"simulation endpoint still present: {banned}"


# ----------------------------------------------------------------------
async def main():
    tests = [
        ("SIP2 checksum", test_sip2_protocol_checksum),
        ("SIP2 builder shapes", test_sip2_builder_shapes),
        ("SIP2 patron info parser", test_sip2_parser_patron_info),
        ("SIP2 checkout parser", test_sip2_parser_checkout_response),
        ("PC/SC reader role resolution", test_reader_role_resolution),
        ("ISO 15693 CRC", test_iso15693_crc),
        ("Liveness validation", test_liveness_engine),
        ("SIP2 client transport", test_sip2_client_transport),
        ("Server routes", test_server_routes_registered),
    ]

    failures = 0
    for name, fn in tests:
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
            print(f"  [PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  [FAIL] {name}: {exc!r}")

    print("\n" + "=" * 60)
    if failures == 0:
        print(" ALL TESTS PASSED")
    else:
        print(f" {failures} TEST(S) FAILED")
    print("=" * 60)
    return failures


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
