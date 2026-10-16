"""
NFSU Central Library Self-Service Kiosk - Single-Command Launcher
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Usage:
    python run_kiosk.py --sip-host <koha-host> --sip-port 6001 \
        --sip-user rfid1 --sip-pass 'Rfid1@123' \
        --card-reader OMNIKEY --book-reader ACR1252 --gate-reader Gate

Run 'python diagnose_hardware.py' first to list the exact PC/SC reader names.
"""

import argparse
import os
import sys

import uvicorn

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="NFSU Central Library Kiosk integrated with Koha 26 (PS-2)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP server port")

    parser.add_argument("--sip-host", default=os.getenv("KOHA_SIP_HOST", "127.0.0.1"),
                        help="Koha SIP2 host")
    parser.add_argument("--sip-port", type=int, default=int(os.getenv("KOHA_SIP_PORT", "6001")),
                        help="Koha SIP2 port")
    parser.add_argument("--sip-user", default=os.getenv("KOHA_SIP_USER", ""),
                        help="Koha SIP2 service account (circulate scope)")
    parser.add_argument("--sip-pass", default=os.getenv("KOHA_SIP_PASS", ""),
                        help="Koha SIP2 service account password")
    parser.add_argument("--institution", default=os.getenv("KOHA_INSTITUTION_ID", "NFSUGNR"),
                        help="Koha institution / AO value")

    parser.add_argument("--card-reader", default=os.getenv("KIOSK_CARD_READER", ""),
                        help="PC/SC reader name substring for the patron card reader")
    parser.add_argument("--book-reader", default=os.getenv("KIOSK_BOOK_READER", ""),
                        help="PC/SC reader name substring for the ISO 15693 book pad")
    parser.add_argument("--gate-reader", default=os.getenv("KIOSK_GATE_READER", ""),
                        help="PC/SC reader name substring for the exit gate antenna")

    args = parser.parse_args()

    os.environ["KOHA_SIP_HOST"] = args.sip_host
    os.environ["KOHA_SIP_PORT"] = str(args.sip_port)
    os.environ["KOHA_SIP_USER"] = args.sip_user
    os.environ["KOHA_SIP_PASS"] = args.sip_pass
    os.environ["KOHA_INSTITUTION_ID"] = args.institution
    os.environ["KIOSK_CARD_READER"] = args.card_reader
    os.environ["KIOSK_BOOK_READER"] = args.book_reader
    os.environ["KIOSK_GATE_READER"] = args.gate_reader

    print("=" * 80)
    print(" NATIONAL FORENSIC SCIENCES UNIVERSITY (NFSU), GANDHINAGAR")
    print(" Central Library Self-Service Kiosk (Koha 26 / SIP2 v2.00) - PS-2")
    print("=" * 80)
    print(f" [OK] Web kiosk UI:      http://localhost:{args.port}")
    print(f" [OK] Koha SIP2 server:  {args.sip_host}:{args.sip_port} (inst {args.institution})")
    print(f" [OK] Service account:   {args.sip_user or '(not set - set KOHA_SIP_USER/PASS)'}")
    print(f" [OK] Card reader match: {args.card_reader or '(first available PC/SC reader)'}")
    print(f" [OK] Book pad match:    {args.book_reader or '(first available PC/SC reader)'}")
    print(f" [OK] Gate antenna:      {args.gate_reader or '(not configured)'}")
    print(f" [OK] Borrowing limit:   {os.getenv('KOHA_MAX_BOOKS', '2')} books per patron")
    print("=" * 80)

    uvicorn.run("kiosk.backend.server:app", host=args.host, port=args.port,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
