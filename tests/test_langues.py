"""Garde-fous sur le dictionnaire de traductions."""
from cachymon import i18n


def test_traductions_sans_cle_vide():
    for lang, textes in i18n.TRANSLATIONS.items():
        for en, tr_ in textes.items():
            assert en.strip() and tr_.strip(), (lang, en)


def test_traduction_conserve_les_champs_de_format():
    # Une traduction qui perd un « {} » ou un « {nom} » casse l'affichage.
    import re
    champs = re.compile(r"\{[^{}]*\}")
    for lang, textes in i18n.TRANSLATIONS.items():
        for en, tr_ in textes.items():
            assert sorted(champs.findall(en)) == sorted(champs.findall(tr_)), (lang, en)


def test_tr_retombe_sur_l_anglais():
    i18n.set_language("en")
    assert i18n.tr("texte jamais traduit xyz") == "texte jamais traduit xyz"


def test_tr_traduit_en_francais():
    i18n.set_language("fr")
    cle = next(iter(i18n.TRANSLATIONS["fr"]))
    assert i18n.tr(cle) == i18n.TRANSLATIONS["fr"][cle]
    i18n.set_language("en")


def test_libelles_des_listes_traduits():
    # Les listes Thème et Langue passent par tr() : « System » doit exister en français.
    from cachymon.theme import THEME_LABELS
    for libelle in (*THEME_LABELS.values(), *i18n.LANG_LABELS.values()):
        if libelle in ("English", "Français"):
            continue        # noms de langues, jamais traduits
        assert libelle in i18n.TRANSLATIONS["fr"], libelle
