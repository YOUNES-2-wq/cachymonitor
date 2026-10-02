"""
Diagnostic manettes — montre exactement ce que l'application lit.

Sous Windows : énumération HID (toutes les manettes Sony trouvées, avec le
rapport d'entrée brut) puis XInput. Sous Linux : lecture de /sys.
Lance le script manette connectée, en câble PUIS en Bluetooth, et compare.

    python scripts/test_controllers.py

Le résultat est aussi écrit à côté du script, dans test_controllers_result.txt,
pour pouvoir être joint à une « issue » GitHub.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cachymonitor as cm

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "test_controllers_result.txt")
lines = []


def log(s=""):
    print(s)
    lines.append(s)


def hexdump(data, width=16):
    """Rapport brut, avec l'indice de chaque octet : c'est lui qui sert à
    vérifier l'octet d'état quand un modèle ne donne pas la bonne batterie."""
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        log("    %3d : %s" % (off, " ".join("%02X" % b for b in chunk)))


log("=" * 70)
log("  Diagnostic manettes  —  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
log("  Plateforme : %s   |   CachyMonitor %s" % (sys.platform, cm.APP_VERSION))
log("=" * 70)

if cm.IS_WINDOWS:
    import ctypes

    log()
    log("-- HID : périphériques Sony trouvés -------------------------------")
    _setup, hid, k32 = cm._hid_api()
    attrs_type = cm._hid_structs()[3]
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 3, 0x40000000
    INVALID = ctypes.c_void_p(-1).value

    paths = cm._hid_device_paths()
    log("  %d périphériques HID présents au total." % len(paths))
    sony = 0
    for path in paths:
        handle = k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0x03, None,
                                 OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == INVALID:
            continue
        try:
            attrs = attrs_type()
            attrs.Size = ctypes.sizeof(attrs_type)
            if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                continue
            if attrs.VendorID != cm.SONY_VID:
                continue
            sony += 1
            name_buf = ctypes.create_unicode_buffer(128)
            product = ""
            if hid.HidD_GetProductString(handle, name_buf, ctypes.sizeof(name_buf)):
                product = (name_buf.value or "").strip()
            known = cm.SONY_PADS.get(attrs.ProductID)
            log()
            log("  VID %04X  PID %04X  « %s »" % (attrs.VendorID, attrs.ProductID,
                                                  product or "?"))
            log("  modèle reconnu : %s" % (known[0] if known else "NON (à ajouter "
                                           "dans SONY_PADS)"))
            log("  chemin : %s" % path)
            report = cm._hid_read(handle, 78, timeout_ms=300)
            if report is None:
                log("  aucun rapport d'entrée reçu en 300 ms "
                    "(manette au repos, ou accès pris par un autre logiciel)")
                continue
            bus = cm.SONY_REPORT_BUS.get(report[0])
            log("  rapport : identifiant 0x%02X, %d octets  ->  bus %s"
                % (report[0], len(report), bus or "inconnu"))
            if known and bus:
                index = cm.SONY_STATUS_BYTE.get((known[1], bus))
                if index is not None and len(report) > index:
                    log("  octet d'état (indice %d) : 0x%02X"
                        % (index, report[index]))
                battery, status = cm._sony_battery(known[1], bus, report)
                log("  décodage : batterie %s, état %s"
                    % ("%d%%" % battery if battery is not None else "—", status))
            hexdump(report)
        finally:
            k32.CloseHandle(handle)
    if not sony:
        log("  Aucun périphérique Sony (VID 054C). Manette éteinte, ou "
            "accaparée par Steam / DS4Windows ?")

    log()
    log("-- XInput --------------------------------------------------------")
    pads = cm._xinput_controllers()
    if not pads:
        log("  Aucune manette XInput active sur les 4 emplacements.")
    for i, pad in enumerate(pads):
        log("  manette %d : %r" % (i, pad))

log()
log("-- Ce que l'application affichera (read_controllers) --------------")
pads = cm.read_controllers()
if not pads:
    log("  Aucune manette détectée.")
for pad in pads:
    link = {"usb": "câble USB", "bluetooth": "Bluetooth"}.get(pad["bus"], "connexion ?")
    battery = "%d%%" % pad["battery"] if pad["battery"] is not None else "—"
    log("  %-28s %-12s %6s   %s" % (pad["name"], link, battery,
                                    pad["status"] or ""))

log()
log("Écrit dans %s" % OUT)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
