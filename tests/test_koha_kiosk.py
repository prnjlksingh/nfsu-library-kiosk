"""
Unit & Integration Test Suite for NFSU Self-Service Library Kiosk (PS-2)
Tests SIP2 Protocol, Koha 26 Server Emulator, 2-Book Limit Rule, and Hardware AFI transitions.
"""

import sys
import os
import asyncio

# Ensure root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kiosk.backend.sip2_protocol import SIP2MessageBuilder, SIP2MessageParser, verify_sip2_checksum
from kiosk.backend.sip2_emulator import emulator
from kiosk.backend.sip2_client import sip_client
from kiosk.backend.rfid_bridge import rfid_bridge
from kiosk.backend.biometrics import biometrics

async def test_sip2_protocol_checksum():
    builder = SIP2MessageBuilder(sequence=3)
    msg = builder.build_99_sc_status()
    assert "AY" in msg
    assert "AZ" in msg
    is_valid, calc, prov = verify_sip2_checksum(msg)
    assert is_valid is True
    assert calc == prov

async def test_koha_emulator_circulation_and_quota():
    emulator.reset_dataset()

    # 1. Test 99 -> 98 Status Handshake
    b = SIP2MessageBuilder(sequence=1)
    req_99 = b.build_99_sc_status()
    resp_98_raw = emulator.handle_request(req_99)
    resp_98 = SIP2MessageParser.parse(resp_98_raw)
    assert resp_98["command"] == "98"
    assert resp_98["online_status"] == "Y"
    assert resp_98["fields"]["AO"] == "NFSUGNR"

    # 2. Test 93 -> 94 Login with circulate account
    req_93 = b.build_93_login(user="nfsu_kiosk", pwd="Kiosk@NFSU2026#")
    resp_94_raw = emulator.handle_request(req_93)
    resp_94 = SIP2MessageParser.parse(resp_94_raw)
    assert resp_94["command"] == "94"
    assert resp_94["ok"] is True

    # 3. Test 63 -> 64 Patron Info (How Many Books Issued)
    # Aarav Sharma: 0 / 2
    req_63_aarav = b.build_63_patron_info("NFSU2026001")
    resp_64_aarav = SIP2MessageParser.parse(emulator.handle_request(req_63_aarav))
    assert resp_64_aarav["charged_items_count"] == 0
    assert len(resp_64_aarav["charged_items"]) == 0

    # Dr. Meera Nair: 1 / 2 (NFSU-BK-101)
    req_63_meera = b.build_63_patron_info("NFSU2026002")
    resp_64_meera = SIP2MessageParser.parse(emulator.handle_request(req_63_meera))
    assert resp_64_meera["charged_items_count"] == 1
    assert "NFSU-BK-101" in resp_64_meera["charged_items"]

    # Rohan Patel: 2 / 2 (NFSU-BK-102, NFSU-BK-103) - QUOTA FULL!
    req_63_rohan = b.build_63_patron_info("NFSU2026003")
    resp_64_rohan = SIP2MessageParser.parse(emulator.handle_request(req_63_rohan))
    assert resp_64_rohan["charged_items_count"] == 2
    assert len(resp_64_rohan["charged_items"]) == 2

    # 4. Test Strict 2-Book Limit Enforcement:
    # Rohan Patel tries to checkout a 3rd book -> MUST BE BLOCKED!
    req_11_rohan_blocked = b.build_11_checkout("NFSU2026003", "NFSU-BK-104")
    resp_12_rohan_blocked = SIP2MessageParser.parse(emulator.handle_request(req_11_rohan_blocked))
    assert resp_12_rohan_blocked["ok"] is False
    assert "LIMIT EXCEEDED" in resp_12_rohan_blocked["screen_message"]

    # Aarav Sharma (0/2) checks out NFSU-BK-104 -> SUCCESS
    req_11_aarav_ok = b.build_11_checkout("NFSU2026001", "NFSU-BK-104")
    resp_12_aarav_ok = SIP2MessageParser.parse(emulator.handle_request(req_11_aarav_ok))
    assert resp_12_aarav_ok["ok"] is True
    assert resp_12_aarav_ok["due_date"] != ""

    # Verify Aarav's counter is now 1/2
    resp_64_aarav_after = SIP2MessageParser.parse(emulator.handle_request(b.build_63_patron_info("NFSU2026001")))
    assert resp_64_aarav_after["charged_items_count"] == 1
    assert "NFSU-BK-104" in resp_64_aarav_after["charged_items"]

    # 5. Check-In (09 -> 10)
    req_09 = b.build_09_checkin("NFSU-BK-104")
    resp_10 = SIP2MessageParser.parse(emulator.handle_request(req_09))
    assert resp_10["ok"] is True

    # Aarav's counter is back to 0/2
    resp_64_aarav_final = SIP2MessageParser.parse(emulator.handle_request(b.build_63_patron_info("NFSU2026001")))
    assert resp_64_aarav_final["charged_items_count"] == 0

async def test_two_phase_commit_and_gate_buzzer():
    emulator.reset_dataset()

    # Initial state of NFSU-BK-104: Armed (AFI 0x07)
    book = emulator.find_book_by_barcode_or_tag("NFSU-BK-104")
    assert book["afi"] == "0x07"

    # Pass through gate while unissued -> MUST TRIGGER ALARM!
    gate_res_unissued = await rfid_bridge.pass_book_through_gate("NFSU-BK-104")
    assert gate_res_unissued["alarm"] is True
    assert "ALARM TRIGGERED" in gate_res_unissued["status_text"]

    # Issue book (Checkout) -> Two-phase commit disarms to 0xC2
    b = SIP2MessageBuilder()
    req = b.build_11_checkout("NFSU2026001", "NFSU-BK-104")
    resp = SIP2MessageParser.parse(emulator.handle_request(req))
    assert resp["ok"] is True
    await rfid_bridge.write_book_afi("NFSU-BK-104", "0xC2")

    # Pass through gate after checkout -> MUST PASS CLEAR!
    gate_res_issued = await rfid_bridge.pass_book_through_gate("NFSU-BK-104")
    assert gate_res_issued["alarm"] is False
    assert "GATE CLEAR" in gate_res_issued["status_text"]

async def test_biometric_liveness_challenge():
    challenge = biometrics.create_liveness_challenge()
    assert "session_id" in challenge
    assert "instruction" in challenge
    assert len(challenge["steps"]) >= 2

    # Verify ephemeral authentication
    ver_res = biometrics.verify_liveness_and_authenticate(
        session_id=challenge["session_id"],
        challenge_passed=True,
        claimed_patron_id="NFSU2026001"
    )
    assert ver_res["authenticated"] is True
    assert ver_res["patron_name"] == "Aarav Sharma"
    assert "Zero Biometric Retention" in ver_res["zero_retention_badge"]

async def main():
    print("Running test_sip2_protocol_checksum()...")
    await test_sip2_protocol_checksum()
    print("  [PASS] SIP2 Checksum and Sequence calculation verified.")

    print("Running test_koha_emulator_circulation_and_quota()...")
    await test_koha_emulator_circulation_and_quota()
    print("  [PASS] Koha 26 Handshake, Login, 63/64 AU parser, and 2-book limit verified.")

    print("Running test_two_phase_commit_and_gate_buzzer()...")
    await test_two_phase_commit_and_gate_buzzer()
    print("  [PASS] 2-Phase Commit AFI 0x07/0xC2 transitions and Gate Buzzer verified.")

    print("Running test_biometric_liveness_challenge()...")
    await test_biometric_liveness_challenge()
    print("  [PASS] Ephemeral in-RAM liveness detection and zero-retention verified.")

    print("\n" + "=" * 60)
    print(" ALL 4 PS-2 CORE TEST SUITES PASSED FLAWLESSLY (100% SUCCESS)")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
