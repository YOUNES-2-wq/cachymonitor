"""
Diagnostic manettes - montre exactement ce que l'application lit.

Sous Windows : enumeration HID (toutes les manettes Sony trouvees, avec le
rapport d'entree brut) puis XInput. Sous Linux : lecture de /sys.
Lance le script manette connectee, en cable PUIS en Bluetooth, et compare.

    python scripts/test_controllers.py

Le resultat est aussi ecrit a cote du script, dans test_controllers_result.txt,
pour pouvoir etre joint a une « issue » GitHub. Les accents sont absents des
messages : la console Windows est en cp1252 et ne les affiche pas tous.
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
    """Rapport brut, avec l'indice de chaque octet : c'est lui qui sert a
    verifier l'octet d'etat quand un modele ne donne pas la bonne batterie."""
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        log("    %3d : %s" % (off, " ".join("%02X" % b for b in chunk)))


log("=" * 70)
log("  Diagnostic manettes  -  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
log("  Plateforme : %s   |   CachyMonitor %s" % (sys.platform, cm.APP_VERSION))
log("=" * 70)

if cm.IS_WINDOWS:
    import ctypes

    log()
    log("-- HID : peripheriques Sony trouves ------------------------------")
    _setup, hid, k32 = cm._hid_api()
    attrs_type = cm._hid_structs()[3]
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    # FILE_FLAG_OVERLAPPED comme dans l'application : sans lui, la lecture du
    # flux attendrait sans limite de temps et le diagnostic resterait muet.
    OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 3, 0x40000000
    INVALID = ctypes.c_void_p(-1).value

    paths = cm._hid_device_paths()
    log("  %d peripheriques HID presents au total." % len(paths))
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
            bus = cm._hid_bus(path)
            serial = cm._hid_serial(handle)
            log()
            log("  VID %04X  PID %04X  « %s »"
                % (attrs.VendorID, attrs.ProductID, product or "?"))
            log("  modele reconnu : %s"
                % (known[0] if known else "NON (a ajouter dans SONY_PADS)"))
            log("  bus deduit du chemin : %s" % (bus or "inconnu"))
            log("  numero de serie (cle de dedoublonnage) : %s"
                % (serial or "absent"))
            log("  chemin : %s" % path)
            if not known or not bus:
                continue

            family = known[1]
            wanted = cm.SONY_REPORTS.get((family, bus))
            if wanted is None:
                log("  pas de rapport connu pour (%s, %s)" % (family, bus))
                continue
            report_id, index = wanted
            report = cm._hid_input_report(handle, report_id)
            if report is None:
                log("  rapport 0x%02X refuse par l'appareil (erreur %d)"
                    % (report_id, ctypes.GetLastError()))
                continue
            log("  rapport 0x%02X obtenu, %d octets" % (report[0], len(report)))
            if len(report) <= index:
                log("  rapport trop court : l'octet d'etat (indice %d) n'y est "
                    "pas. Modele different de celui attendu ?" % index)
            else:
                log("  octet d'etat (indice %d) : 0x%02X" % (index, report[index]))
                battery, status = cm._sony_battery(family, report[index])
                log("  decodage : batterie %s, etat %s"
                    % ("%d%%" % battery if battery is not None else "-", status))
            hexdump(report)
        finally:
            k32.CloseHandle(handle)
    if not sony:
        log("  Aucun peripherique Sony (VID 054C). Manette eteinte, ou "
            "accaparee par Steam / DS4Windows ?")

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
    log("  Aucune manette detectee.")
for pad in pads:
    link = {"usb": "cable USB", "bluetooth": "Bluetooth"}.get(pad["bus"], "connexion ?")
    battery = "%d%%" % pad["battery"] if pad["battery"] is not None else "-"
    log("  %-28s %-12s %6s   %s"
        % (pad["name"], link, battery, pad["status"] or ""))

log()
log("Ecrit dans %s" % OUT)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
