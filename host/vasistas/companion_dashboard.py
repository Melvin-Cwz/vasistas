"""Tableau de bord du compagnon (maquette docs/maquettes/tableau-de-bord.html).

Accueil : un bandeau qui prend la couleur de l'état de Windows, avec l'aperçu en direct de son
écran, un sélecteur d'état à trois positions (Arrêté, En veille, Actif) et l'utilisation du
processeur et de la mémoire vive ; dessous, le mode d'affichage, les applications du menu et les
actions recommandées. Le sommaire des paramètres avancés est ici aussi ; la page Paramètres
elle-même est dans companion_parameters.py.
"""

import re
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Granite", "7.0")
from gi.repository import Gdk, GLib, Granite, Gtk  # noqa: E402

from . import control, desktop, vm, winctl  # noqa: E402
from .companion_common import card, clear, confirm, dim, notify_failure, texture_from_b64  # noqa: E402
from .companion_home import phase, qemu_usage  # noqa: E402
from .i18n import N_, _, current  # noqa: E402
from .winctl import APP_ID  # noqa: E402

# phase -> (titre, explication, ce que l'état coûte)
PHASES = {
    "ready": (N_("Windows est actif"), N_("Les applications Windows s'ouvrent immédiatement."),
              N_("Mémoire vive utilisée, processeur à la demande.")),
    "asleep": (N_("Windows est en veille"), N_("Windows sort de veille à l'ouverture d'une application Windows."),
               N_("Mémoire vive réservée, processeur au repos.")),
    "stopped": (N_("Windows est arrêté"), N_("Windows démarre à l'ouverture d'une application Windows, en 30 secondes "
                                             "environ."),
                N_("Aucune ressource utilisée.")),
    "starting": (N_("Démarrage de Windows…"), N_("Les applications demandées s'ouvriront dès que Windows sera actif."),
                 N_("Chargement de Windows en mémoire vive.")),
}
POSITIONS = [("stopped", N_("Arrêté")), ("asleep", N_("En veille")), ("ready", N_("Actif"))]
VEILS = {"asleep": N_("En veille"), "stopped": N_("Arrêté"), "starting": N_("Démarrage")}

CSS = """
.vasistas-band { padding: 24px 30px; }
.vasistas-band.ready { background-image: linear-gradient(172deg, #0d52bf, #002e99); }      /* Blueberry 700, 900 */
.vasistas-band.asleep { background-image: linear-gradient(172deg, #452981, #260063); }     /* Grape 700, 900 */
.vasistas-band.starting { background-image: linear-gradient(172deg, #a62100, #7a0000); }   /* Orange 900, Strawberry 900 */
.vasistas-band.stopped { background-image: linear-gradient(172deg, #273445, #0e141f); }    /* Slate 700, 900 */
.vasistas-band label { color: white; }
.vasistas-band label.soft { color: #e8eefc; }
.vasistas-title { font-size: 2.1em; font-weight: 300; }
.vasistas-band .linked button, .vasistas-band button.band { background: alpha(black, 0.28); background-image: none;
  border-color: transparent; box-shadow: none; text-shadow: none; }
.vasistas-band .linked button:checked { background: white; }
.vasistas-band .linked button:checked label { color: #002e99; }
.vasistas-band button:disabled label { color: #b9c0cc; }
.vasistas-band levelbar trough { background: alpha(white, 0.26); border: none; box-shadow: none; padding: 0; min-height: 6px; }
.vasistas-band levelbar block { border: none; box-shadow: none; min-height: 6px; }
.vasistas-band levelbar block.filled { background: white; }
.vasistas-band levelbar block.empty { background: transparent; }
.vasistas-preview { border-radius: 9px; background: #0e141f; }
.vasistas-veil { background: alpha(black, 0.55); }
.vasistas-chip { background: alpha(black, 0.62); border-radius: 4px; padding: 2px 9px; margin: 10px; font-size: 0.85em;
  font-weight: 600; }
.vasistas-shelf { padding: 10px; }
.vasistas-open { min-width: 6px; min-height: 6px; border-radius: 3px; background: @accent_color; }
.vasistas-open.off { background: transparent; }
.vasistas-choice button:checked { background-color: @accent_color; background-image: none; }
.vasistas-choice button:checked label { color: white; }
.vasistas-sidebar { padding: 10px; background: alpha(@theme_fg_color, 0.04); }
.vasistas-sidebar button.nav { padding: 6px 10px; }
.vasistas-sidebar button.nav:checked { background: @accent_color; background-image: none; }
.vasistas-sidebar button.nav:checked label, .vasistas-sidebar button.nav:checked image { color: white; }
"""
_css_loaded = False


def load_css():
    global _css_loaded
    if not _css_loaded:
        _css_loaded = True
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)


def state_action(current, target):
    """Commande de winctl qui mène de la phase `current` à la position `target` du sélecteur
    d'état ; None s'il n'y a rien à faire, ou si c'est impossible (pas de mise en veille d'un
    Windows arrêté ou en cours de démarrage)."""
    if target == current or (target == "ready" and current == "starting"):
        return None
    if target == "stopped":
        return "stop"
    if target == "asleep":
        return "sleep" if current == "ready" else None
    return {"stopped": "start", "asleep": "wake"}.get(current)


def position(current):
    """Position du sélecteur pour une phase : pendant le démarrage, Windows va vers « Actif »."""
    return "ready" if current == "starting" else current


def allocated():
    """(cœurs, mémoire vive en Go) alloués à Windows."""
    cpus, memory = vm.resources()
    m = re.match(r"(\d+)", str(memory))
    return max(1, int(cpus)), max(1, int(m.group(1)) if m else 8)


def open_app_ids(wins):
    """Applications qui ont une fenêtre ouverte, d'après la liste de l'hôte ; les fenêtres sans
    application reconnue (canonical_app rend None) et les entrées mal formées sont ignorées."""
    apps = {desktop.canonical_app(w.get("app")) for w in wins
            if isinstance(w, dict) and isinstance(w.get("app"), str) and w.get("kind") != "popup"
            and not w.get("owner")}
    return apps - {None}


def update_due(cfg, now):
    """(rappel de mise à jour de Windows à montrer ?, jours depuis la dernière ou None)."""
    last = cfg.get("last_windows_update")
    # config.json s'écrit aussi à la main : autre chose qu'une date vaut « jamais »
    days = int((now - last) / 86400) if isinstance(last, (int, float)) and not isinstance(last, bool) and last > 0 \
        else None
    # rappel mensuel, sauf si l'utilisateur gère lui-même les mises à jour (page Paramètres)
    return (days is None or days > 30) and cfg.get("windows_update_reminder") is not False, days


def heading(text):
    """Intertitre de groupe, à la manière de Granite (petites capitales espacées)."""
    return Granite.HeaderLabel.new(text)


class DashboardPage(Gtk.Box):
    __gtype_name__ = "VasistasDashboardPage"

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        load_css()
        self.win = win
        self.phase = None
        self.syncing = False
        self.busy = False        # une commande d'état en cours
        self.fetching = False    # aperçu et fenêtres en cours de lecture
        self.sample = None
        self.open_apps = set()
        self.shelf_key = None

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.band())
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=30, margin_end=30,
                          margin_top=20, margin_bottom=30)
        content.append(self.mode_card())
        content.append(heading(_("Applications")))
        self.shelf = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                                 min_children_per_line=3, homogeneous=True, halign=Gtk.Align.FILL)
        for c in (Granite.STYLE_CLASS_CARD, Granite.STYLE_CLASS_ROUNDED, "vasistas-shelf"):
            self.shelf.add_css_class(c)
        content.append(self.shelf)
        content.append(heading(_("Actions recommandées")))
        self.actions = card()
        content.append(self.actions)
        body.append(content)
        self.append(Gtk.ScrolledWindow(child=body, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True))

    def add_help(self, on_click):
        """Pas de bouton « ? » sur l'accueil : l'aide a sa propre entrée dans la barre latérale."""

    # -- bandeau d'état --

    def band(self):
        self.band_box = Gtk.Box(spacing=28)
        self.band_box.add_css_class("vasistas-band")

        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self.veil_label = Gtk.Label()
        self.veil_spinner = Gtk.Spinner()
        veil = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.FILL, halign=Gtk.Align.FILL)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER, vexpand=True)
        inner.append(self.veil_spinner)
        inner.append(self.veil_label)
        veil.append(inner)
        veil.add_css_class("vasistas-veil")
        self.veil = veil
        self.chip = Gtk.Label(label=_("En direct"), halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.chip.add_css_class("vasistas-chip")
        overlay = Gtk.Overlay(child=self.picture, overflow=Gtk.Overflow.HIDDEN)
        overlay.add_overlay(veil)
        overlay.add_overlay(self.chip)
        overlay.add_css_class("vasistas-preview")
        overlay.set_cursor_from_name("pointer")
        overlay.set_tooltip_text(_("Ouvrir Windows en mode bureau"))
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: self.phase == "ready" and self.set_mode("single"))
        overlay.add_controller(click)
        frame = Gtk.AspectFrame(ratio=1.6, obey_child=False, child=overlay, width_request=360, valign=Gtk.Align.CENTER)
        self.band_box.append(frame)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("vasistas-title")
        self.text = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        self.text.add_css_class("soft")
        side.append(self.title)
        side.append(self.text)

        row = Gtk.Box(spacing=8, margin_top=10)
        selector = Gtk.Box(homogeneous=True)
        selector.add_css_class("linked")
        self.positions = {}
        first = None
        for key, label in POSITIONS:
            b = Gtk.ToggleButton(label=_(label), group=first, width_request=96)
            first = first or b
            b.connect("toggled", self.on_position, key)
            selector.append(b)
            self.positions[key] = b
        row.append(selector)
        self.restart = Gtk.Button(label=_("Redémarrer"))
        self.restart.add_css_class("band")
        self.restart.connect("clicked", lambda *_a: self.win.restart_windows())
        row.append(self.restart)
        side.append(row)
        self.effect = Gtk.Label(xalign=0, wrap=True)
        self.effect.add_css_class("soft")
        self.effect.add_css_class(Granite.STYLE_CLASS_SMALL_LABEL)
        side.append(self.effect)

        usage = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=10)
        self.bars = {}
        for i, (key, label) in enumerate((("cpu", _("Processeur")), ("ram", _("Mémoire vive")))):
            name = Gtk.Label(label=label, xalign=0)
            name.add_css_class(Granite.STYLE_CLASS_SMALL_LABEL)
            bar = Gtk.LevelBar(min_value=0, max_value=1, hexpand=True, valign=Gtk.Align.CENTER, width_request=160)
            value = Gtk.Label(xalign=1, width_chars=12)
            value.add_css_class(Granite.STYLE_CLASS_SMALL_LABEL)
            usage.attach(name, 0, i, 1, 1)
            usage.attach(bar, 1, i, 1, 1)
            usage.attach(value, 2, i, 1, 1)
            self.bars[key] = (bar, value)
        side.append(usage)
        self.band_box.append(side)
        return self.band_box

    def show_phase(self, p):
        if p == self.phase:
            return
        self.phase = p
        title, text, effect = PHASES[p]
        self.title.set_label(_(title))
        self.text.set_label(_(text))
        self.effect.set_label(_(effect))
        for name in PHASES:
            self.band_box.remove_css_class(name)
        self.band_box.add_css_class(p)
        self.syncing = True
        self.positions[position(p)].set_active(True)
        self.syncing = False
        self.positions["asleep"].set_sensitive(p in ("ready", "asleep"))
        self.restart.set_sensitive(p == "ready")
        self.veil.set_visible(p != "ready")
        self.chip.set_visible(p == "ready")
        self.veil_label.set_label(_(VEILS.get(p, "")))
        self.veil_spinner.set_visible(p == "starting")
        self.veil_spinner.set_spinning(p == "starting")
        if p in ("stopped", "starting"):
            self.picture.set_paintable(None)

    def on_position(self, button, target):
        if self.syncing or not button.get_active():
            return
        action = state_action(self.phase, target)
        if action is None or self.busy:
            self.resync()
            return

        def run():
            self.busy = True
            self.syncing = True
            self.positions[target].set_active(True)
            self.syncing = False

            def work():
                try:
                    getattr(winctl, action)()
                except Exception as e:  # noqa: BLE001 - message à l'utilisateur
                    notify_failure(self.win, e)
                GLib.idle_add(self.command_done)
            threading.Thread(target=work, name="vasistas-state", daemon=True).start()
        # un clic suffit à arrêter Windows : avec des fenêtres ouvertes, on demande d'abord
        # (Windows est éteint de force au bout d'une minute, documents non enregistrés perdus)
        if action == "stop" and ((self.win.state.get("host") or {}).get("windows") or 0) > 0:
            self.resync()
            confirm(self.win, _("Arrêter Windows ?"),
                    _("Les applications Windows ouvertes seront fermées. Enregistrez vos documents avant d'arrêter."),
                    _("Arrêter"), lambda: self.busy or run())
        else:
            run()

    def command_done(self):
        self.busy = False
        self.phase = None  # relu au prochain état
        self.win.poll()
        return False

    def resync(self):
        """Remet le sélecteur sur l'état réel (position refusée ou commande déjà en cours)."""
        if self.phase:
            self.syncing = True
            self.positions[position(self.phase)].set_active(True)
            self.syncing = False

    def show_usage(self, state, p):
        cpus, memory = allocated()
        pid = state.get("pid")
        usage = qemu_usage(pid, self.sample) if pid else None
        self.sample = usage["sample"] if usage else None
        cpu = (usage or {}).get("cpu")
        cpu = 0.0 if p in ("asleep", "stopped") or cpu is None else min(100.0, cpu / cpus)
        ram = (usage or {}).get("rss_mb", 0) / 1024
        self.bars["cpu"][0].set_value(cpu / 100)
        self.bars["cpu"][1].set_label(f"{cpu:.0f} %")
        self.bars["ram"][0].set_value(min(1.0, ram / memory))
        used = f"{ram:.1f}"
        self.bars["ram"][1].set_label(_("{used} sur {total} Go", total=memory,
                                        used=used if current() == "en" else used.replace(".", ",")))

    # -- aperçu en direct et applications ouvertes --

    def fetch(self):
        if self.fetching:
            return
        self.fetching = True

        def work():
            shot, wins = None, None
            try:
                shot = control.request({"thumbnail": 640}, timeout=2).get("png")
                wins = control.request({"windows": True}, timeout=1).get("windows") or []
            except (OSError, ValueError, AttributeError):  # AttributeError : réponse qui n'est pas un objet
                pass
            finally:
                GLib.idle_add(self.fetched, shot, wins)  # toujours : sinon l'aperçu resterait figé
        threading.Thread(target=work, name="vasistas-preview", daemon=True).start()

    def fetched(self, shot, wins):
        self.fetching = False
        texture = texture_from_b64(shot) if shot else None
        if texture is not None and self.phase in ("ready", "asleep"):
            self.picture.set_paintable(texture)
        if isinstance(wins, list):
            self.open_apps = open_app_ids(wins)
            self.fill_shelf()
        return False

    # -- mode d'affichage --

    def mode_card(self):
        box = Gtk.Box(spacing=14)
        for c in (Granite.STYLE_CLASS_CARD, Granite.STYLE_CLASS_ROUNDED):
            box.add_css_class(c)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER,
                        margin_start=16, margin_top=12, margin_bottom=12)
        title = Gtk.Label(label=_("Mode d'affichage"), xalign=0)
        title.add_css_class(Granite.STYLE_CLASS_H4_LABEL)
        self.mode_hint = dim("")
        texts.append(title)
        texts.append(self.mode_hint)
        box.append(texts)
        selector = Gtk.Box(valign=Gtk.Align.CENTER, margin_end=16)
        selector.add_css_class("linked")
        selector.add_css_class("vasistas-choice")
        self.modes = {}
        first = None
        for key, label in (("integrated", _("Mode intégré")), ("single", _("Mode bureau"))):
            b = Gtk.ToggleButton(label=label, group=first)
            first = first or b
            b.connect("toggled", lambda btn, k=key: btn.get_active() and not self.syncing and self.set_mode(k))
            selector.append(b)
            self.modes[key] = b
        box.append(selector)
        return box

    def show_mode(self):
        single = vm.load_config().get("display_mode") == "single"
        self.syncing = True
        self.modes["single" if single else "integrated"].set_active(True)
        self.syncing = False
        self.mode_hint.set_label(
            _("Le bureau de Windows complet dans une seule fenêtre, barre des tâches comprise.") if single else
            _("Chaque application Windows s'ouvre dans sa propre fenêtre, parmi celles de Linux."))

    def set_mode(self, mode):
        cfg = vm.load_config()
        cfg["display_mode"] = mode
        vm.save_config(cfg)
        self.show_mode()

        def work():
            try:
                control.request({"desktop": mode == "single"}, timeout=10)
            except (OSError, ValueError):
                pass  # Windows arrêté, hôte en train de quitter : le mode s'appliquera au démarrage
        threading.Thread(target=work, name="vasistas-mode", daemon=True).start()

    # -- applications du menu --

    def fill_shelf(self):
        reg = desktop.load_registry()
        # apps.json vient de ce que Windows a déclaré : les entrées mal formées sont ignorées
        apps = sorted(((app, str(entry.get("name") or app)) for app, entry in reg.items()
                       if isinstance(entry, dict) and desktop.in_menu(app)), key=lambda a: a[1].lower())
        key = (apps, sorted(self.open_apps), self.phase == "ready")
        if key == self.shelf_key:
            return
        self.shelf_key = key
        clear(self.shelf)
        for app, name in apps:
            self.shelf.append(self.app_button(app, name))
        add = self.tile(Gtk.Image(icon_name="list-add-symbolic", pixel_size=32, margin_top=8, margin_bottom=8),
                        _("Ajouter"), False)
        add.connect("clicked", lambda *_a: self.win.show_page("install"))
        self.shelf.append(add)

    def tile(self, icon, name, is_open):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(icon)
        label = Gtk.Label(label=name, max_width_chars=12, wrap=True, justify=Gtk.Justification.CENTER)
        label.add_css_class(Granite.STYLE_CLASS_SMALL_LABEL)
        box.append(label)
        dot = Gtk.Box(halign=Gtk.Align.CENTER)
        dot.add_css_class("vasistas-open")
        if not is_open:
            dot.add_css_class("off")
        box.append(dot)
        button = Gtk.Button(child=box)
        button.add_css_class(Granite.STYLE_CLASS_FLAT)
        return button

    def app_button(self, app, name):
        icon = Gtk.Image(pixel_size=48)
        path = desktop.app_icon_path(app)
        if path.exists():
            icon.set_from_file(str(path))
        else:
            icon.set_from_icon_name(APP_ID)
        button = self.tile(icon, name, self.phase == "ready" and app in self.open_apps)
        button.set_tooltip_text(_("Ouvrir {name}", name=name))
        button.connect("clicked", lambda *_a: winctl.spawn("launch-app", app))
        return button

    # -- actions recommandées --

    def show_actions(self, p):
        late, days = update_due(vm.load_config(), time.time())
        key = (late, days is None, p == "ready")
        if key == getattr(self, "actions_key", None):
            return
        self.actions_key = key
        clear(self.actions)
        if late:
            button = Gtk.Button(label=_("Mettre à jour"), valign=Gtk.Align.CENTER, sensitive=p == "ready")
            button.add_css_class(Granite.STYLE_CLASS_SUGGESTED_ACTION)
            button.connect("clicked", lambda *_a: self.windows_update())
            self.actions.append(self.action_row(
                "software-update-available-symbolic",
                _("Mises à jour de Windows à installer") if days is not None else _("Windows n'a jamais été mis à jour depuis Vasistas"),
                _("Un point de restauration est créé avant l'installation. Windows doit être actif."), button))
        details = Gtk.Button(label=_("Détails"), valign=Gtk.Align.CENTER)
        details.connect("clicked", lambda *_a: self.win.show_page("diagnose"))
        self.actions.append(self.action_row(
            "process-completed-symbolic", _("Vérifier l'ordinateur et Vasistas"),
            _("Le diagnostic contrôle la machine virtuelle, l'affichage et les dossiers partagés."), details))

    @staticmethod
    def action_row(icon, title, text, button):
        box = Gtk.Box(spacing=12, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        box.append(Gtk.Image(icon_name=icon, pixel_size=24, valign=Gtk.Align.CENTER))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        texts.append(Gtk.Label(label=title, xalign=0, wrap=True))
        texts.append(dim(text))
        box.append(texts)
        box.append(button)
        return Gtk.ListBoxRow(activatable=False, child=box)

    def windows_update(self):
        general = self.win.show_page("general")
        if general is not None:
            general.windows_update()

    def update(self, state):
        p = phase(state)
        self.show_phase(p)
        self.show_usage(state, p)
        self.show_mode()
        self.show_actions(p)
        if p == "ready":
            self.fetch()
        else:
            self.open_apps = set()
        self.fill_shelf()


class ParametersHub(Gtk.Box):
    """Paramètres avancés : sommaire des pages de réglages existantes, classées par thème (volet
    « Avancés » de companion_parameters.ParametersPage)."""

    __gtype_name__ = "VasistasParametersHub"
    ENTRIES = [
        ("display", "preferences-desktop-display", N_("Affichage"),
         N_("Écrans, fenêtres, carte graphique et fluidité.")),
        ("windows", "computer", "Windows",
         N_("Mises à jour, son, clavier, imprimantes et optimisation de Windows.")),
        ("restoration", "document-revert", N_("Restauration"),
         N_("Points de restauration du disque de Windows.")),
        ("settings", "preferences-system", N_("Préférences de Vasistas"),
         N_("Démarrage, thème, langue et mises à jour de Vasistas.")),
        ("about", "dialog-information", N_("À propos"), N_("Version, licences et remerciements.")),
    ]

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=30, margin_end=30,
                         margin_top=18, margin_bottom=30)
        entries = card()
        for name, icon, label, text in self.ENTRIES:
            box = Gtk.Box(spacing=12, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
            box.append(Gtk.Image(icon_name=icon, pixel_size=32))
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
            texts.append(Gtk.Label(label=_(label), xalign=0))
            texts.append(dim(_(text)))
            box.append(texts)
            box.append(Gtk.Image(icon_name="go-next-symbolic"))
            row = Gtk.ListBoxRow(child=box)
            row.page = name
            entries.append(row)
        entries.connect("row-activated", lambda _lb, row: win.show_page(row.page))
        self.append(entries)

    def add_help(self, on_click):
        """Chaque page de réglages a son propre bouton d'aide."""

    def update(self, state):
        """Rien à suivre : le sommaire ne dépend pas de l'état de Windows."""
