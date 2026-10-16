import ctypes
from ctypes import wintypes
import subprocess
import json

print("=" * 60)
print("NFSU KIOSK HARDWARE DIAGNOSTIC TOOL")
print("=" * 60)

# 1. Check PC/SC Smartcard Readers
print("\n[1] Checking PC/SC Contactless Smartcard Readers (winscard.dll)...")
try:
    sc = ctypes.windll.winscard
    hCtx = wintypes.HANDLE()
    ret = sc.SCardEstablishContext(0, 0, 0, ctypes.byref(hCtx))
    if ret == 0:
        buf = ctypes.create_string_buffer(2048)
        buflen = wintypes.DWORD(2048)
        ret2 = sc.SCardListReadersA(hCtx, None, buf, ctypes.byref(buflen))
        if ret2 == 0:
            raw = buf.raw[:buflen.value].decode("ascii", errors="ignore")
            readers = [r for r in raw.split("\x00") if r]
            print(f"  --> FOUND {len(readers)} PC/SC Smartcard Reader(s):")
            for idx, r in enumerate(readers, 1):
                print(f"      {idx}. {r}")
                
            # Check if card is currently on the reader
            for r in readers:
                hCard = wintypes.HANDLE()
                dwProto = wintypes.DWORD()
                ret3 = sc.SCardConnectA(hCtx, r.encode('ascii'), 2, 3, ctypes.byref(hCard), ctypes.byref(dwProto))
                if ret3 == 0:
                    print(f"      [*] Card DETECTED on reader: {r}")
                    # Try reading UID
                    apdu = bytes([0xFF, 0xCA, 0x00, 0x00, 0x00])
                    recv_buf = ctypes.create_string_buffer(256)
                    recv_len = wintypes.DWORD(256)
                    pci = ctypes.c_void_p.in_dll(sc, "g_rgSCardT1Pci" if dwProto.value == 2 else "g_rgSCardT0Pci")
                    ret4 = sc.SCardTransmit(hCard, ctypes.byref(pci), apdu, len(apdu), None, recv_buf, ctypes.byref(recv_len))
                    if ret4 == 0 and recv_len.value >= 2:
                        res_bytes = recv_buf.raw[:recv_len.value]
                        if res_bytes[-2:] == b'\x90\x00':
                            uid = res_bytes[:-2].hex().upper()
                            print(f"      [*] Card UID read successfully: {uid}")
                        else:
                            print(f"      [-] APDU response status: {res_bytes[-2:].hex().upper()}")
                    sc.SCardDisconnect(hCard, 0)
                else:
                    print(f"      [ ] Reader is empty (no card tapped right now).")
        else:
            err = hex(ret2 if ret2 > 0 else (1 << 32) + ret2)
            print(f"  --> No PC/SC reader service active (Status: {err}).")
        sc.SCardReleaseContext(hCtx)
    else:
        print(f"  --> Could not establish winscard context: {hex(ret)}")
except Exception as e:
    print(f"  --> PC/SC check error: {e}")

# 2. Check Windows PnP USB Devices (OMNIKEY, Smartrac, Barcode, HID, COM ports)
print("\n[2] Checking Connected USB PnP Devices...")
try:
    ps_cmd = 'Get-CimInstance Win32_PnPEntity | Where-Object { $_.Present -ne $false } | Select-Object Name, Manufacturer, DeviceID, PNPClass | ConvertTo-Json'
    output = subprocess.check_output(['powershell', '-Command', ps_cmd], text=True)
    devices = json.loads(output)
    if isinstance(devices, dict):
        devices = [devices]
    
    matches = []
    keywords = ['omnikey', 'smartrac', 'rfid', 'smartcard', 'cardman', 'hid', 'scanner', 'barcode', 'pos', 'serial', 'ch340', 'ftdi', 'cp210', 'acm', 'com']
    for d in devices:
        name = str(d.get('Name') or '')
        mfg = str(d.get('Manufacturer') or '')
        dev_id = str(d.get('DeviceID') or '')
        pnp_class = str(d.get('PNPClass') or '')
        full_text = f"{name} {mfg} {dev_id} {pnp_class}".lower()
        if any(kw in full_text for kw in keywords):
            matches.append(d)
            
    print(f"  --> Found {len(matches)} relevant hardware device(s):")
    for m in matches:
        print(f"      * [{m.get('PNPClass')}] {m.get('Name')} | ID: {m.get('DeviceID')}")
except Exception as e:
    print(f"  --> USB PnP error: {e}")

# 3. Check Serial / COM Ports
print("\n[3] Checking Serial / COM Ports...")
try:
    ps_cmd2 = 'Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Description, Name | ConvertTo-Json'
    output2 = subprocess.check_output(['powershell', '-Command', ps_cmd2], text=True).strip()
    if output2:
        ports = json.loads(output2)
        if isinstance(ports, dict):
            ports = [ports]
        print(f"  --> Found {len(ports)} Serial/COM Port(s):")
        for p in ports:
            print(f"      * {p.get('DeviceID')}: {p.get('Description') or p.get('Name')}")
    else:
        print("  --> No virtual COM/Serial ports detected (devices are likely HID keyboard-wedge or PC/SC).")
except Exception as e:
    print(f"  --> Serial check error: {e}")

print("\n" + "=" * 60)
