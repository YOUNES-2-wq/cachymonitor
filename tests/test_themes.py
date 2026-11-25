"""Garde-fous sur les thèmes : palettes complètes, lisibles, libellés et réglages cohérents."""
import pytest

from cachymon import i18n, theme


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_chaque_theme_a_les_memes_roles():
    # Un rôle manquant ferait planter col() au premier affichage de ce thème.
    roles = set(theme.THEMES["sombre"])
    for name, palette in theme.THEMES.items():
        assert set(palette) == roles, name


def test_couleurs_au_format_hexadecimal():
    for name, palette in theme.THEMES.items():
        for role, value in palette.items():
            assert len(value) == 7 and value[0] == "#", (name, role)
            int(value[1:], 16)


def test_modes_et_libelles_vont_ensemble():
    assert set(theme.THEME_MODES) - {"systeme"} == set(theme.THEMES)
    assert set(theme.THEME_LABELS) == set(theme.THEME_MODES)
    assert theme.DEFAULT_THEME in theme.THEME_MODES


def test_libelles_traduits():
    # La liste Thème passe par tr() : chaque libellé doit exister dans le dictionnaire français.
    for label in theme.THEME_LABELS.values():
        assert label in i18n.TRANSLATIONS["fr"], label


@pytest.mark.parametrize("name", sorted(theme.THEMES))
def test_texte_lisible_sur_les_cartes(name):
    palette = theme.THEMES[name]
    assert _contrast(palette["text"], palette["card"]) >= 4.5
    for role in ("cpu", "gpu", "ram", "vram", "fps", "ft", "ok", "warn", "bad"):
        assert _contrast(palette[role], palette["card"]) >= 3.0, role


def test_theme_claude_seul_en_verre():
    for name in theme.THEMES:
        theme.set_palette(name)
        assert theme.is_glass() == (name == "claude")
    theme.set_palette("sombre")


def test_intensite_du_verre_bornee():
    theme.set_glass_level(5)
    assert theme.glass_level() == 1.0
    theme.set_glass_level(-2)
    assert theme.glass_level() == 0.0
    theme.set_glass_level(theme.DEFAULT_GLASS_LEVEL)


def test_accent_claude_inconnu_retombe_sur_le_defaut():
    theme.set_claude_accent("nexiste-pas")
    assert theme.THEMES["claude"]["cpu"] == theme.CLAUDE_ACCENTS[theme.DEFAULT_ACCENT][1]
    assert theme.claude_orb() == theme.CLAUDE_ACCENTS[theme.DEFAULT_ACCENT][3]


def test_chaque_accent_est_valide_et_lisible():
    card = theme.THEMES["claude"]["card"]
    for key, (name, main, fps, orb) in theme.CLAUDE_ACCENTS.items():
        assert name in i18n.TRANSLATIONS["fr"], key
        assert _contrast(main, card) >= 3.0 and _contrast(fps, card) >= 3.0, key
        assert len(orb) == 3 and all(0 <= c <= 255 for c in orb), key
    theme.set_claude_accent(theme.DEFAULT_ACCENT)


def test_accent_windows_fonce_reste_lisible():
    card = theme.THEMES["windows"]["card"]
    for dark in ("#000000", "#00188f", "#4c0000", "#004b1c", "#0000ff", "#ff0000",
                 "#8000ff", "#2d00ff"):
        assert _contrast(theme.readable_accent(dark), card) >= 3.0, dark


def test_couleur_de_barre_de_titre():
    from cachymon.titlebar import colorref
    assert colorref("#112233") == 0x332211


def test_accent_windows_gris_remplace_par_le_bleu(monkeypatch):
    monkeypatch.setattr(theme, "_windows_accent", lambda: "#767676")
    theme.set_windows_accent()
    assert theme.THEMES["windows"]["cpu"] == "#60cdff"
