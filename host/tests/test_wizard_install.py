"""Assistant : étapes de l'installation, aperçu du bureau de Windows, pilotes bloqués d'emblée."""

from pathlib import Path

from vasistas import screenview, stepper

ROOT = Path(__file__).resolve().parents[2]
DRIVER_POLICIES = ("ExcludeWUDriversInQualityUpdate", "DontSearchWindowsUpdate", "SearchOrderConfig",
                   "PreventDeviceMetadataFromNetwork")


def test_etapes_selon_les_choix():
    assert stepper.plan(False, True, True, True) == dict.fromkeys(
        ("windows", "configure", "apps", "driver", "update"), "todo")
    assert stepper.plan(True, False, False, False) == {
        "windows": "done", "configure": "todo", "apps": "skipped", "driver": "skipped", "update": "skipped"}
    assert [key for key, _short, _title in stepper.STAGES] == ["windows", "configure", "apps", "driver", "update"]


def test_pointeur_dans_l_image_ajustee():
    # écran 4:3 dans un aperçu 16:9 : bandes à gauche et à droite
    assert screenview.pointer(400, 225, 800, 450, 1024, 768) == (16383, 16383)
    assert screenview.pointer(10, 225, 800, 450, 1024, 768) is None
    assert screenview.pointer(100, 0, 800, 450, 1024, 768) == (0, 0)
    assert screenview.pointer(5, 5, 0, 0, 0, 0) is None


def test_touches_vers_qemu():
    assert screenview.key_values(38) == [{"type": "number", "data": 30}]  # A
    assert screenview.key_values(36) == [{"type": "number", "data": 28}]  # Entrée
    assert screenview.key_values(111) == [{"type": "qcode", "data": "up"}]
    assert screenview.key_values(38, shift=True)[0] == {"type": "qcode", "data": "shift"}
    assert screenview.key_values(50) is None    # Maj seule
    assert screenview.key_values(200) is None


def test_pilotes_de_windows_update_bloques_des_l_installation():
    for script in ("install/specialize.ps1", "install/configure-windows.ps1", "guest/accel/install-accel.ps1"):
        text = (ROOT / script).read_text(encoding="utf-8-sig")
        for policy in DRIVER_POLICIES:
            assert policy in text, (script, policy)


def test_bureau_entier_ajuste_et_pointe():
    from vasistas import window
    assert window.fit_screen(1100, 700, 2880, 1800) == (1100 / 2880, 0.0, (700 - 1800 * 1100 / 2880) / 2)
    # centre de la vue = centre de l'écran ; hors de l'image : ramené au bord
    assert window.screen_point(550, 350, 1100, 700, 2880, 1800) == (1440, 900)
    assert window.screen_point(-5, 9999, 1100, 700, 2880, 1800) == (0, 1799)


def test_fenetre_independante_nette():
    from vasistas import window
    # vue de 1280 x 800 pixels logiques sur un écran à 167 % : Windows prend ses pixels physiques
    scale = 5 / 3
    res = window.desktop_resolution(1280, 800, scale)
    assert res == (2133, 1333)
    assert window.desktop_layout(1280, 800, *res, scale) == (1 / scale, 0.0, 0.0, True)  # sans marge
    # tant que Windows n'a pas changé de résolution : image ajustée
    assert window.desktop_layout(1280, 800, 2880, 1800, scale)[3] is False
    assert window.desktop_resolution(100, 100, 1.0) == (800, 600)
    assert window.desktop_layout(100, 100, 800, 600, 1.0)[3] is False
    # le pointeur suit la même mise en place
    assert window.screen_point(640, 400, 1280, 800, *res, scale) == (1066, 666)


def test_icones_des_lanceurs_reprises_de_la_liste(tmp_path, monkeypatch):
    from vasistas import desktop, guestapps
    saved = []
    monkeypatch.setattr(guestapps, "DATA", tmp_path)
    monkeypatch.setattr(desktop, "in_menu", lambda app: app != "horsmenu")
    monkeypatch.setattr(desktop, "save_app_icon", lambda app, png: saved.append((app, png)))
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "winword.png").write_bytes(b"x")  # déjà reçue de l'agent
    apps = [{"id": "excel", "icon": "A"}, {"id": "winword", "icon": "B"}, {"id": "horsmenu", "icon": "C"},
            {"id": "sansicone", "icon": None}]
    guestapps._launcher_icons(apps, lambda b64: b64.encode())
    assert saved == [("excel", b"A")]
