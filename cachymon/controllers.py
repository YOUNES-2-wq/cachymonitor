"""CachyMonitor : module controllers (voir cachymonitor.py)."""

import re

from .debug import debug_exc



# ----------------------------------------------------------------------------- #
#  Manettes
# ----------------------------------------------------------------------------- #

# Préfixes de fabricant retirés du nom affiché, déjà assez long comme ça.
CONTROLLER_NAME_PREFIXES = ("Sony Interactive Entertainment ", "Sony Computer Entertainment ",
                            "Microsoft ", "Nintendo ")


def _clean_controller_name(name):
    for prefix in CONTROLLER_NAME_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# --------------------------------------------------------------------------
#  Manettes sous Windows
# --------------------------------------------------------------------------
# Windows n'a pas d'équivalent de /sys : il faut deux sources, aucune ne
# couvrant tout le matériel.
#
#   · XInput (xinput1_4.dll) : les manettes Xbox et toutes celles qui se font
#     passer pour elles. L'API ne donne QUE quatre niveaux de batterie (pas un
#     pourcentage) et aucun nom de modèle — elle ne le publie pas.
#   · HID brut : les manettes Sony (DualSense, DualShock 4), que Windows ne
#     présente pas comme des manettes XInput. Le nom vient du descripteur USB,
#     la batterie du rapport d'entrée, décodé comme le fait le pilote Linux
#     (hid-playstation pour la DualSense, hid-sony pour la DualShock 4).
#
# Si DS4Windows ou Steam traduit une manette Sony en manette Xbox, la même
# manette physique apparaît des deux côtés. Rien ne permet de relier la manette
# virtuelle à son original : on préfère l'afficher en double plutôt que de
# masquer une vraie seconde manette.

# Niveaux XInput (BATTERY_LEVEL_EMPTY/LOW/MEDIUM/FULL) ramenés à un pourcentage
# approché.
XINPUT_BATTERY = {0: 5, 1: 20, 2: 50, 3: 100}

# Manette filaire : pas de batterie, mais une connexion connue.
XINPUT_BAT_WIRED = 0x01
# Les deux seuls types où le niveau veut dire quelque chose : piles alcalines
# et accu. Les autres — DISCONNECTED (0x00) et UNKNOWN (0xFF), que renvoient
# beaucoup de manettes tierces et les manettes virtuelles de Steam ou
# DS4Windows — laissent un niveau qui ne signifie rien : mieux vaut n'afficher
# aucune batterie qu'un pourcentage inventé.
XINPUT_BAT_WIRELESS = (0x02, 0x03)

# xinput1_4 est celle de Windows 8 et suivants, donc toujours présente sur
# Windows 11 ; les deux autres ne servent que si l'app tourne ailleurs.
# xinput9_1_0 n'a pas XInputGetBatteryInformation : la manette est alors
# détectée, mais sans batterie.
XINPUT_DLLS = ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll")

XUSER_MAX_COUNT = 4

SONY_VID = 0x054C
# PID -> (nom affiché par défaut, famille de décodage du rapport d'entrée)
SONY_PADS = {
    0x0CE6: ("DualSense", "dualsense"),
    0x0DF2: ("DualSense Edge", "dualsense"),
    0x05C4: ("DualShock 4", "ds4"),
    0x09CC: ("DualShock 4", "ds4"),
    0x0BA0: ("DualShock 4 (dongle)", "ds4"),
}

# (famille, bus) -> (rapport d'entrée à demander, indice de l'octet d'état).
# En Bluetooth, la manette n'envoie d'elle-même qu'un rapport 0x01 réduit aux
# boutons et aux joysticks : la batterie n'est que dans le rapport complet,
# qu'il faut donc réclamer explicitement. Celui-ci porte un octet d'en-tête de
# plus que son équivalent USB, d'où l'indice décalé d'un cran.
SONY_REPORTS = {
    ("dualsense", "usb"): (0x01, 53),
    ("dualsense", "bluetooth"): (0x31, 54),
    ("ds4", "usb"): (0x01, 30),
    ("ds4", "bluetooth"): (0x11, 32),
}

# Le plus grand rapport d'entrée d'une manette Sony fait 78 octets ; un tampon
# plus grand que nécessaire est accepté par le pilote HID.
SONY_REPORT_SIZE = 78

# Protocoles Bluetooth reconnaissables dans le chemin du périphérique :
# « HID over BR/EDR » et « HID over GATT » (basse consommation). Le chemin est
# la seule source fiable du type de connexion — ni l'identifiant du rapport ni
# sa longueur ne renseignent dessus, Windows complétant toujours la lecture à
# la taille maximale déclarée par l'appareil.
BLUETOOTH_HID_PROTOCOLS = ("{00001124-", "{00001812-")

# Identifiant du fabricant tel qu'il apparaît dans le chemin d'un périphérique
# HID : « vid_054c » en USB, « vid&0002054c » en Bluetooth (le préfixe code le
# type de bus). Il sert de pré-filtre : la boucle de mesure passe par ici une
# fois par seconde, et ouvrir les quinze ou vingt périphériques HID d'un PC à
# chaque fois pour n'en garder qu'un serait du gâchis.
HID_PATH_VID = re.compile(r"vid[_&](?:[0-9a-f]{4})?([0-9a-f]{4})")

_hid_api_cache = None


def _hid_api():
    """setupapi + hid + kernel32, signatures posées une fois pour toutes.

    Les pointeurs et les handles doivent être déclarés explicitement : sans
    restype, ctypes les tronque à 32 bits et le processus meurt en
    ACCESS_VIOLATION — le même piège que pour la mémoire partagée.
    """
    global _hid_api_cache
    if _hid_api_cache is None:
        import ctypes
        from ctypes import wintypes

        setup = ctypes.windll.setupapi
        hid = ctypes.windll.hid
        k32 = ctypes.windll.kernel32

        setup.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        setup.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                               ctypes.c_void_p, wintypes.DWORD]
        setup.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                      ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.c_void_p]
        setup.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p]
        setup.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

        # Ces fonctions renvoient un BOOLEAN, c'est-à-dire UN octet : sans
        # restype, ctypes lit un entier de 32 bits dont les octets de poids
        # fort sont laissés indéterminés par la convention d'appel 64-bit, et
        # un échec peut passer pour un succès.
        for name in ("HidD_GetAttributes", "HidD_GetProductString",
                     "HidD_GetSerialNumberString", "HidD_GetInputReport"):
            getattr(hid, name).restype = ctypes.c_ubyte
        hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        hid.HidD_GetProductString.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                              wintypes.ULONG]
        hid.HidD_GetSerialNumberString.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                   wintypes.ULONG]
        hid.HidD_GetInputReport.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            wintypes.ULONG]

        k32.CreateEventW.restype = ctypes.c_void_p
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                     ctypes.c_wchar_p]
        k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.c_void_p, ctypes.c_void_p]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        k32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_void_p, wintypes.BOOL]
        k32.CancelIo.argtypes = [ctypes.c_void_p]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        _hid_api_cache = (setup, hid, k32)
    return _hid_api_cache


_hid_structs_cache = None


def _hid_structs():
    """Structures Win32 de l'énumération HID : (GUID, interface, détail,
    attributs, overlapped). Construites une seule fois : ctypes fabriquerait
    sinon un type différent à chaque appel.
    """
    global _hid_structs_cache
    if _hid_structs_cache is None:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                        ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

        # La vraie structure finit par un tableau de taille variable ; un
        # tampon généreux évite le double appel qui sert à mesurer le chemin.
        class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("DevicePath", ctypes.c_wchar * 512)]

        class HIDD_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                        ("ProductID", wintypes.USHORT),
                        ("VersionNumber", wintypes.USHORT)]

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p),
                        ("InternalHigh", ctypes.c_void_p),
                        ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                        ("hEvent", ctypes.c_void_p)]

        _hid_structs_cache = (GUID, SP_DEVICE_INTERFACE_DATA,
                              SP_DEVICE_INTERFACE_DETAIL_DATA_W, HIDD_ATTRIBUTES,
                              OVERLAPPED)
    return _hid_structs_cache


def _hid_device_paths():
    """Chemins de tous les périphériques HID présents."""
    import ctypes

    setup, _hid, _k32 = _hid_api()
    guid_type, iface_type, detail_type, _attrs, _ov = _hid_structs()

    # GUID_DEVINTERFACE_HID : {4D1E55B2-F16F-11CF-88CB-001111000030}
    guid = guid_type(0x4D1E55B2, 0xF16F, 0x11CF,
                     (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11,
                                          0x11, 0x00, 0x00, 0x30))
    DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x02, 0x10
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    dev_info = setup.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                          DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not dev_info or dev_info == INVALID_HANDLE_VALUE:
        return []

    paths = []
    try:
        iface = iface_type()
        iface.cbSize = ctypes.sizeof(iface_type)
        index = 0
        while setup.SetupDiEnumDeviceInterfaces(dev_info, None, ctypes.byref(guid),
                                                index, ctypes.byref(iface)):
            index += 1
            detail = detail_type()
            # cbSize décrit la structure OFFICIELLE (un DWORD puis un WCHAR,
            # alignés), pas notre tampon : 8 octets en 64-bit, 6 en 32-bit.
            detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setup.SetupDiGetDeviceInterfaceDetailW(
                    dev_info, ctypes.byref(iface), ctypes.byref(detail),
                    ctypes.sizeof(detail), None, None):
                paths.append(detail.DevicePath)
        return paths
    finally:
        setup.SetupDiDestroyDeviceInfoList(dev_info)


def _hid_bus(path):
    """Type de connexion d'un périphérique HID, d'après son chemin."""
    low = path.lower()
    if any(proto in low for proto in BLUETOOTH_HID_PROTOCOLS):
        return "bluetooth"
    return "usb" if "vid_" in low else None


def _hid_serial(handle):
    """Numéro de série d'un périphérique HID, ou None."""
    import ctypes

    _setup, hid, _k32 = _hid_api()
    buf = ctypes.create_unicode_buffer(128)
    if not hid.HidD_GetSerialNumberString(handle, buf, ctypes.sizeof(buf)):
        return None
    return (buf.value or "").strip() or None


def _hid_get_report(handle, report_id, size):
    """Rapport RÉCLAMÉ à l'appareil (requête GET_REPORT), ou None.

    C'est la seule façon d'obtenir le rapport complet en Bluetooth : la manette
    n'y envoie d'elle-même qu'un rapport réduit aux boutons et aux joysticks.
    Et c'est en lecture seule — lui imposer le mode complet lui prendrait la
    main sur l'éclairage et les vibrations, au détriment des jeux.
    """
    import ctypes

    _setup, hid, _k32 = _hid_api()
    buf = (ctypes.c_ubyte * size)()
    # L'identifiant du rapport voulu se met dans le premier octet, qui ne peut
    # donc pas servir à vérifier que l'appareil a répondu quelque chose.
    buf[0] = report_id
    if not hid.HidD_GetInputReport(handle, buf, size):
        return None
    report = bytes(buf)
    # Un vrai rapport de manette n'est jamais vide : il porte au moins des
    # joysticks au repos (0x80) et un horodatage. Tout à zéro, c'est un tampon
    # resté intact, qu'il ne faut pas décoder — la batterie en sortirait à 5 %
    # alors qu'on n'en sait rien.
    return report if any(report[1:]) else None


def _hid_stream_report(handle, size, timeout_ms=80):
    """Premier rapport reçu du flux de l'appareil, ou None.

    Second recours : en USB, la manette Sony refuse GET_REPORT (« échec
    général »), mais elle émet ses rapports en continu — un arrive en quelques
    millisecondes. La lecture est asynchrone et annulée au-delà du délai : une
    manette silencieuse ne doit pas figer le thread de mesure.
    """
    import ctypes
    from ctypes import wintypes

    _setup, _hid, k32 = _hid_api()
    overlapped_type = _hid_structs()[4]
    ERROR_IO_PENDING, WAIT_OBJECT_0 = 997, 0

    buf = (ctypes.c_ubyte * size)()
    read = wintypes.DWORD(0)
    event = k32.CreateEventW(None, True, False, None)
    if not event:
        return None
    ov = overlapped_type()
    ov.hEvent = event
    try:
        if not k32.ReadFile(handle, buf, size, ctypes.byref(read), ctypes.byref(ov)):
            if ctypes.GetLastError() != ERROR_IO_PENDING:
                return None
            if k32.WaitForSingleObject(event, timeout_ms) != WAIT_OBJECT_0:
                # On attend la fin réelle de l'annulation : sans cela, le noyau
                # pourrait encore écrire dans un tampon déjà libéré par Python.
                k32.CancelIo(handle)
                k32.GetOverlappedResult(handle, ctypes.byref(ov),
                                        ctypes.byref(read), True)
                return None
            if not k32.GetOverlappedResult(handle, ctypes.byref(ov),
                                           ctypes.byref(read), False):
                return None
        return bytes(buf[:read.value])
    finally:
        k32.CloseHandle(event)


def _hid_input_report(handle, report_id, size=SONY_REPORT_SIZE):
    """Un rapport d'entrée de l'identifiant demandé, ou None.

    Aucune des deux méthodes ne marche sur les deux bus : la manette répond à
    GET_REPORT en Bluetooth mais le refuse en USB, où elle diffuse en revanche
    ses rapports en continu. On essaie donc l'une puis l'autre.
    """
    # Un appareil peut répondre par un autre rapport que celui demandé : les
    # indices ne voudraient alors rien dire.
    def utilisable(report):
        return report is not None and len(report) > 1 and report[0] == report_id

    report = _hid_get_report(handle, report_id, size)
    if utilisable(report):
        return report
    report = _hid_stream_report(handle, size)
    return report if utilisable(report) else None


def _sony_battery(family, status_byte):
    """Batterie d'une manette Sony : (pourcentage, état) ou (None, None).

    Décodage repris des pilotes Linux : le matériel ne publie qu'un niveau par
    dizaine, dont on prend le milieu (0 = 0-9 %, 1 = 10-19 %…).
    """
    level = status_byte & 0x0F

    if family == "dualsense":
        # Quartet haut : 0 décharge, 1 en charge, 2 pleine ; le reste signale
        # un défaut (température ou tension) et on ne sait alors rien de sûr.
        charge = (status_byte & 0xF0) >> 4
        if charge == 0x02:
            return 100, "full"
        if charge not in (0x00, 0x01):
            return None, None
        return min(level * 10 + 5, 100), "charging" if charge == 0x01 else "discharging"

    # DualShock 4 : le bit 4 dit si le câble est branché, et le niveau monte
    # alors jusqu'à 11 (pleine) — 14 et 15 signalent un défaut de charge.
    cable = bool(status_byte & 0x10)
    if not cable:
        return min(level * 10 + 5, 100), "discharging"
    if level >= 11:
        return (100, "full") if level == 11 else (None, None)
    return min(level * 10 + 5, 100), "charging"


def _sony_pad(handle, path, product_id):
    """Une manette Sony : nom, bus, batterie, à partir d'un périphérique ouvert."""
    import ctypes

    _setup, hid, _k32 = _hid_api()
    label, family = SONY_PADS[product_id]

    name_buf = ctypes.create_unicode_buffer(128)
    if hid.HidD_GetProductString(handle, name_buf, ctypes.sizeof(name_buf)):
        product = _clean_controller_name((name_buf.value or "").strip())
        if product:
            label = product

    bus = _hid_bus(path)
    battery = status = None
    wanted = SONY_REPORTS.get((family, bus))
    if wanted is not None:
        report_id, index = wanted
        report = _hid_input_report(handle, report_id)
        if report is not None and len(report) > index:
            battery, status = _sony_battery(family, report[index])
    return {"name": label, "bus": bus, "battery": battery, "status": status}


def _hid_sony_controllers():
    """Manettes Sony vues en HID brut : nom, bus, batterie."""
    import ctypes

    _setup, hid, k32 = _hid_api()
    attrs_type = _hid_structs()[3]

    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE = 0x01, 0x02
    OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 3, 0x40000000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    found = {}
    for path in _hid_device_paths():
        vid = HID_PATH_VID.search(path.lower())
        if vid is None or int(vid.group(1), 16) != SONY_VID:
            continue
        handle = k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            # Périphérique ouvert en exclusif par un autre logiciel, ou dont
            # l'accès demande des droits : il y en a beaucoup, on passe.
            continue
        try:
            attrs = attrs_type()
            attrs.Size = ctypes.sizeof(attrs_type)
            if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                continue
            if attrs.VendorID != SONY_VID or attrs.ProductID not in SONY_PADS:
                continue

            pad = _sony_pad(handle, path, attrs.ProductID)
            # Une manette expose plusieurs interfaces HID (pavé tactile,
            # capteurs de mouvement, une par collection sous USB) : on n'en
            # garde qu'une, celle qui a répondu la batterie.
            # Le dédoublonnage se fait sur le numéro de série, qui est l'adresse
            # MAC sur les manettes Sony : identique d'une interface à l'autre
            # pour une même manette, mais différent entre deux manettes du même
            # modèle. Sans lui, deux DualSense n'en feraient qu'une à l'écran —
            # justement le cas où connaître sa batterie importe.
            key = _hid_serial(handle) or (attrs.ProductID, pad["bus"])
            if key not in found or (found[key]["battery"] is None
                                    and pad["battery"] is not None):
                found[key] = pad
        finally:
            k32.CloseHandle(handle)
    return list(found.values())


_xinput_cache = None


def _xinput():
    """(dll, XINPUT_STATE, XINPUT_BATTERY_INFORMATION), ou None sans XInput.

    Posé une seule fois : la boucle de mesure passe ici chaque seconde, et
    ctypes ne décharge jamais une bibliothèque qu'il a chargée — son compteur
    de références monterait indéfiniment, et les structures seraient refaites à
    chaque appel.
    """
    global _xinput_cache
    if _xinput_cache is None:
        import ctypes
        from ctypes import wintypes

        class XINPUT_STATE(ctypes.Structure):
            _fields_ = [("dwPacketNumber", wintypes.DWORD),
                        ("wButtons", wintypes.WORD),
                        ("bLeftTrigger", ctypes.c_ubyte),
                        ("bRightTrigger", ctypes.c_ubyte),
                        ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                        ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]

        class XINPUT_BATTERY_INFORMATION(ctypes.Structure):
            _fields_ = [("BatteryType", ctypes.c_ubyte),
                        ("BatteryLevel", ctypes.c_ubyte)]

        dll = None
        for name in XINPUT_DLLS:
            try:
                dll = ctypes.windll.LoadLibrary(name)
                break
            except OSError:
                continue
        # False plutôt que None : on retient que la recherche a déjà échoué,
        # au lieu de recharger la bibliothèque absente à chaque seconde.
        _xinput_cache = ((dll, XINPUT_STATE, XINPUT_BATTERY_INFORMATION)
                         if dll is not None else False)
    return _xinput_cache or None


def _xinput_controllers():
    """Manettes vues par XInput : batterie en quatre niveaux, sans modèle."""
    import ctypes

    api = _xinput()
    if api is None:
        return []
    dll, XINPUT_STATE, XINPUT_BATTERY_INFORMATION = api

    get_battery = getattr(dll, "XInputGetBatteryInformation", None)

    found = []
    for user in range(XUSER_MAX_COUNT):
        state = XINPUT_STATE()
        if dll.XInputGetState(user, ctypes.byref(state)) != 0:   # ERROR_SUCCESS
            continue

        battery, status, bus = None, None, None
        if get_battery is not None:
            info = XINPUT_BATTERY_INFORMATION()
            # 0 = BATTERY_DEVTYPE_GAMEPAD (1 serait le casque branché dessus).
            if get_battery(user, 0, ctypes.byref(info)) == 0:
                if info.BatteryType == XINPUT_BAT_WIRED:
                    bus = "usb"
                elif info.BatteryType in XINPUT_BAT_WIRELESS:
                    # Sans fil : XInput ne dit pas si c'est le dongle USB ou le
                    # Bluetooth, et se tromper afficherait une fausse info.
                    battery = XINPUT_BATTERY.get(info.BatteryLevel)
                    status = "discharging" if battery is not None else None
        found.append({"name": "Xbox Controller", "bus": bus,
                      "battery": battery, "status": status})
    return found


def read_controllers():
    """Liste des manettes connectées : nom, connexion, batterie. Les manettes Sony d'abord : on connaît leur
    modèle et leur batterie au pourcentage près, là où XInput reste vague.
    """
    pads = []
    for source in (_hid_sony_controllers, _xinput_controllers):
        try:
            pads += source()
        except Exception:
            debug_exc("manettes : " + source.__name__)
            # Une source indisponible (DLL absente, accès refusé par un autre
            # logiciel) ne doit pas priver l'utilisateur de l'autre.
            continue
    return pads
