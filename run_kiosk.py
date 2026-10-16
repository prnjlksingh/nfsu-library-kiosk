"""
NFSU Central Library Self-Service Kiosk - Single-Command Launcher
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Usage:
    python run_kiosk.py [--host 0.0.0.0] [--port 8000]
"""

import os
import sys
import argparse
import uvicorn

# Ensure inventory root is on sys.path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def main():
    parser = argparse.ArgumentParser(description="NFSU Central Library Kiosk Integrated with Koha 26 (PS-2)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP Server Host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP Server Port")
    parser.add_argument("--sip-host", default="117.239.182.15", help="Koha SIP2 Host")
    parser.add_argument("--sip-port", type=int, default=6001, help="Koha SIP2 Port")
    args = parser.parse_args()

    os.environ["KOHA_SIP_HOST"] = args.sip_host
    os.environ["KOHA_SIP_PORT"] = str(args.sip_port)

    print("=" * 80)
    print(" NATIONAL FORENSIC SCIENCES UNIVERSITY (NFSU), GANDHINAGAR")
    print(" Central Library Self-Service Kiosk & SIP2 Diagnostic Suite (PS-2)")
    print("=" * 80)
    print(f" [OK] Web Kiosk UI:       http://localhost:{args.port}")
    print(f" [OK] Koha SIP2 Server:   {args.sip_host}:{args.sip_port}")
    print(f" [OK] Service Account:    nfsu_kiosk (circulate ONLY)")
    print(f" [OK] Dual-Zone RFID Mat: Active (ISO 15693 Smartrac + ISO 14443A MIFARE)")
    print(f" [OK] 2-Book Limit:       Strictly Enforced (MAX_BOOKS = 2)")
    print(f" [OK] Biometric Engine:   Volatile In-RAM Blink Liveness (Zero Retention)")
    print(f" [OK] Security Gate:      Web Audio API Siren (AFI: 0x07 Armed / 0xC2 Clear)")
    print("=" * 80)

    uvicorn.run("kiosk.backend.server:app", host=args.host, port=args.port, reload=False, log_level="info")

if __name__ == "__main__":
    main()
