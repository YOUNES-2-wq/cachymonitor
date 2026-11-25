"""Barre de titre de Windows 11 aux couleurs du thème (DWM)."""

import ctypes
import functools

_DARK_MODE, _CAPTION_COLOR, _TEXT_COLOR = 20, 35, 36     # DWMWINDOWATTRIBUTE


@functools.lru_cache(maxsize=1)
def _dwmapi():
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                          ctypes.c_void_p, ctypes.c_ulong]
    return dwm


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def colorref(hex_color):
    """« #rrggbb » vers COLORREF (0x00bbggrr)."""
    r, g, b = _rgb(hex_color)
    return r | g << 8 | b << 16


def tint_title_bar(hwnd, background, text):
    """Pose les couleurs de la barre de titre. Purement décoratif : un Windows qui
    ne connaît pas ces réglages garde sa barre habituelle."""
    try:
        dwm = _dwmapi()
        r, g, b = _rgb(background)
        dark = 0.299 * r + 0.587 * g + 0.114 * b < 128
        for attribute, value in ((_DARK_MODE, int(dark)),
                                 (_CAPTION_COLOR, colorref(background)),
                                 (_TEXT_COLOR, colorref(text))):
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, AttributeError):
        pass
