"""Tableau de bord du compagnon : sélecteur d'état."""

import os

from vasistas import companion_dashboard as dash


def test_selecteur_d_etat():
    assert dash.state_action("ready", "asleep") == "sleep"
    assert dash.state_action("ready", "stopped") == "stop"
    assert dash.state_action("asleep", "ready") == "wake"
    assert dash.state_action("stopped", "ready") == "start"
    assert dash.state_action("asleep", "stopped") == "stop"
    # rien à faire, ou impossible : pas de mise en veille d'un Windows arrêté ou qui démarre
    assert dash.state_action("ready", "ready") is None
    assert dash.state_action("starting", "ready") is None
    assert dash.state_action("stopped", "asleep") is None
    assert dash.state_action("starting", "asleep") is None
    assert dash.state_action("starting", "stopped") == "stop"


def test_position_du_selecteur():
    assert dash.position("starting") == "ready"
    assert [dash.position(p) for p in ("stopped", "asleep", "ready")] == ["stopped", "asleep", "ready"]
    assert [key for key, _label in dash.POSITIONS] == ["stopped", "asleep", "ready"]
    assert set(dash.PHASES) == {"ready", "asleep", "stopped", "starting"}


def test_curseurs_des_parametres():
    from vasistas import companion_parameters as par
    assert par.memory_values(32) == list(range(2, 29, 2))      # 4 Go toujours laissés à Linux
    assert par.memory_values(4) == [2]
    assert par.cpu_values(4) == [1, 2, 3, 4]
    assert par.nearest([1, 2, 5, 10], 6) == 2 and par.nearest([2, 4, 6], 100) == 2
    assert par.marks(list(range(1, 13)), 4) == [0, 3, 5, 11]   # bouts, recommandé, milieu
    assert par.marks(par.SLEEP_VALUES, 5)[0] == 0 and 2 in par.marks(par.SLEEP_VALUES, 5)
    assert par.profile_for(4, 8) == "balanced" and par.profile_for(12, 12) == "performance"
    assert par.profile_for(5, 8) is None


def test_avertissement_de_ressources():
    from vasistas import companion_parameters as par
    assert par.resources_warning(4, 8, 24, 32) is None
    assert "mémoire" in par.resources_warning(4, 26, 24, 32)
    assert "cœur" in par.resources_warning(20, 8, 24, 32)


def test_ressources_personnalisees(monkeypatch):
    from vasistas import vm
    monkeypatch.setattr(vm, "PROFILE", "")
    monkeypatch.setattr(vm, "load_config", lambda: {"resources_custom": {"cpus": 3, "memory": 10}})
    assert vm.resources() == (3, "10G")
    # valeurs absurdes : bornées, jamais transmises telles quelles à QEMU
    monkeypatch.setattr(vm, "load_config", lambda: {"resources_custom": {"cpus": 9999, "memory": 1}})
    cpus, memory = vm.resources()
    assert 1 <= cpus <= (os.cpu_count() or 1) and memory == "2G"
    # jamais plus de mémoire que l'ordinateur n'en a, moins les 4 Go laissés à Linux
    monkeypatch.setattr(vm, "host_memory_gb", lambda: 16)
    monkeypatch.setattr(vm, "load_config", lambda: {"resources_custom": {"cpus": 2, "memory": 200}})
    assert vm.resources() == (2, "12G")
    # ni nombre, ni entier fini : le profil reprend la main
    for bad in ({"cpus": float("inf"), "memory": 8}, {"cpus": "4; rm", "memory": 8}, {"cpus": 4}, {"cpus": None, "memory": 8},
                {"cpus": 4, "memory": [8]}):
        assert vm.custom_resources({"resources_custom": bad}) is None, bad
    monkeypatch.setattr(vm, "load_config", lambda: {"resources_custom": "n'importe quoi", "resources": "balanced"})
    assert vm.resources()[1].endswith("G")


def _config(monkeypatch, cfg):
    """config.json en mémoire : rien n'est lu ni écrit dans celui de l'utilisateur."""
    from vasistas import vm
    monkeypatch.setattr(vm, "PROFILE", "")
    monkeypatch.setattr(vm, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(vm, "save_config", lambda new: (cfg.clear(), cfg.update(new)))
    return cfg


def test_choisir_un_profil_efface_les_valeurs_personnalisees(monkeypatch):
    # indicateur, page Avancé, page Paramètres : sinon le profil choisi resterait sans effet
    from vasistas import companion_parameters as par, vm, winctl
    cfg = _config(monkeypatch, {"resources_custom": {"cpus": 1, "memory": 2}, "resources_auto": False})
    assert vm.resources() == (1, "2G") and par.configured() == (1, 2)
    winctl.set_resources("performance")
    assert "resources_custom" not in cfg and vm.resources() == vm.RESOURCES["performance"]
    assert par.configured() == (12, 12)


def test_curseurs_sur_le_profil_choisi_pas_celui_du_moment(monkeypatch):
    # sur batterie, vm.resources() donne « Économie d'énergie » : la page montre le profil choisi
    from vasistas import companion_parameters as par, power
    _config(monkeypatch, {"resources": "performance"})
    monkeypatch.setattr(power, "boot_profile", lambda cfg=None: "battery")
    assert par.configured() == (12, 12)


def test_ballon_et_memoire_personnalisee(monkeypatch):
    from vasistas import power, vm
    monkeypatch.setattr(vm, "host_memory_gb", lambda: 64)
    cfg = _config(monkeypatch, {})
    assert power.memory_cap("balanced") == power.memory_bytes(vm.MEMORY)
    cfg["resources_custom"] = {"cpus": 2, "memory": 16}
    assert power.memory_cap("balanced") is None             # la mémoire réglée à la main n'est pas rabattue
    assert power.memory_cap("battery") == 6 * 2 ** 30       # sur batterie, l'économie garde la main


def test_reglages_ecrits_a_la_main():
    from vasistas import companion_parameters as par
    # autre chose qu'un nombre : pas de plantage à l'ouverture de la page
    assert par.nearest(par.SLEEP_VALUES, "5") == 0 and par.nearest([1, 2], None) == 0 and par.nearest([1, 2], True) == 0
    assert dash.update_due({}, 1e9) == (True, None)
    assert dash.update_due({"last_windows_update": "hier"}, 1e9) == (True, None)
    assert dash.update_due({"last_windows_update": 1e9 - 86400 * 40}, 1e9) == (True, 40)
    assert dash.update_due({"last_windows_update": 1e9 - 86400 * 2}, 1e9) == (False, 2)
    assert dash.update_due({"windows_update_reminder": False}, 1e9) == (False, None)


def test_applications_ouvertes():
    wins = [{"app": "excel"}, {"app": None}, {}, {"app": "winword", "kind": "popup"}, {"app": "x", "owner": 3},
            {"app": 12}, "n'importe quoi", {"app": "PAS UN IDENTIFIANT"}]
    apps = dash.open_app_ids(wins)
    assert apps == {"excel"}
    sorted(apps)  # la clé de l'étagère trie : une fenêtre sans application ne doit pas y glisser None


def test_accord_en_nombre(monkeypatch):
    from vasistas import companion_parameters as par, i18n
    monkeypatch.setattr(i18n, "_lang", "fr")
    assert [par.plural(n, "{n} cœur", "{n} cœurs") for n in (0, 1, 2)] == ["0 cœur", "1 cœur", "2 cœurs"]
    monkeypatch.setattr(i18n, "_lang", "en")
    assert [par.plural(n, "{n} core", "{n} cores") for n in (0, 1, 2)] == ["0 cores", "1 core", "2 cores"]


def test_barre_laterale():
    from vasistas import companion
    tabs = {name for name, _label, _icon in companion.Window.PRIMARY}
    # chaque page rangée ailleurs allume une destination qui existe
    assert set(companion.Window.PARENTS.values()) <= tabs
    assert not set(companion.Window.PARENTS) & tabs
    pages = tabs | set(companion.Window.PARENTS)
    assert {page for page, _sub in companion.Window.MOVED.values()} <= pages
    # le sommaire des paramètres avancés ne mène qu'à des pages rangées sous Paramètres
    assert {name for name, *_rest in dash.ParametersHub.ENTRIES} == set(companion.Window.PARENTS)


def test_lanceur_de_demarrage_automatique():
    from vasistas.companion_windows import autostart_text
    text = autostart_text("/home/moi/.local/bin/vasistas", True)
    assert "Exec=/home/moi/.local/bin/vasistas boot --sleep\n" in text
    assert "--sleep" not in autostart_text("vasistas", False)
