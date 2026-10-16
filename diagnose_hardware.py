"""
NFSU Central Library Self-Service Kiosk - Hardware Diagnostic Tool
National Forensic Sciences University, Gandhinagar

Run this on the circulation desk to:
  * list every PC/SC contactless reader the OS can see,
  * read the ISO 14443A UID of a card currently on a reader,
  * inventory ISO 15693 book tags and read their AFI security byte,
  * list serial / COM ports for a serial barcode scanner.

Usage:
    python diagnose_hardware.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from kiosk.backend.pcsc_reader import (  # noqa: E402
    PYSCARD_AVAILABLE,
    PYSCARD_IMPORT_ERROR,
    PCSCReader,
    list_readers,
)


def section(title: str) -> None:
    print("\n" + "-" * 68)
    print(title)
    print("-" * 68)


def main() -> None:
    print("=" * 68)
    print("NFSU KIOSK HARDWARE DIAGNOSTIC")
    print("=" * 68)

    # 1. PC/SC readers -------------------------------------------------
    section("[1] PC/SC contactless readers")
    if not PYSCARD_AVAILABLE:
        print(f"  [!] pyscard is not installed ({PYSCARD_IMPORT_ERROR}).")
        print("      Install it with:  pip install pyscard")
    else:
        readers = list_readers()
        print(f"  Found {len(readers)} reader(s):")
        for idx, name in enumerate(readers, 1):
            print(f"    {idx}. {name}")

        for name in readers:
            print(f"\n  Reader: {name}")
            reader = PCSCReader(name)

            uid = reader.get_uid()
            if uid:
                print(f"    [ISO 14443A] card UID = {uid}")
            else:
                print("    [ISO 14443A] no card present / not answering GET DATA")

            tag = reader.read_book_tag()
            if tag:
                print(f"    [ISO 15693] tag UID = {tag.uid}  AFI = {tag.afi_hex or 'unreadable'}  DSFID = "
                      f"{('0x%02X' % tag.dsfid) if tag.dsfid is not None else 'n/a'}")
            else:
                print("    [ISO 15693] no tag present / reader not in ISO 15693 mode")

    # 2. Serial ports --------------------------------------------------
    section("[2] Serial / COM ports (serial barcode scanners)")
    try:
        from serial.tools import list_ports

        ports = list(list_ports.comports())
        if ports:
            for port in ports:
                print(f"    {port.device}: {port.description}")
        else:
            print("  No serial ports. (HID keyboard-wedge scanners need no port.)")
    except Exception as exc:
        print(f"  pyserial unavailable ({exc}). Install it with: pip install pyserial")

    # 3. Windows PnP hint ---------------------------------------------
    if os.name == "nt":
        section("[3] Windows PnP devices (RFID / smart card / HID)")
        try:
            import subprocess
            import json

            ps = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.Present -ne $false } | "
                  "Select-Object Name, Manufacturer, DeviceID | ConvertTo-Json")
            out = subprocess.check_output(["powershell", "-Command", ps], text=True)
            devices = json.loads(out) if out.strip() else []
            if isinstance(devices, dict):
                devices = [devices]
            keywords = ("smartcard", "smart card", "omnikey", "rfid", "acr", "cardman",
                        "hid", "barcode", "scanner", "usb serial", "ch340", "ftdi", "cp210")
            shown = 0
            for d in devices:
                text = f"{d.get('Name','')} {d.get('Manufacturer','')} {d.get('DeviceID','')}".lower()
                if any(k in text for k in keywords):
                    print(f"    * {d.get('Name')} | {d.get('DeviceID')}")
                    shown += 1
            if shown == 0:
                print("  No matching PnP devices found.")
        except Exception as exc:
            print(f"  PnP query failed: {exc}")

    print("\n" + "=" * 68)
    print("Use the printed reader names with:")
    print("    python run_kiosk.py --card-reader <name> --book-reader <name> --gate-reader <name>")
    print("=" * 68)


if __name__ == "__main__":
    main()
