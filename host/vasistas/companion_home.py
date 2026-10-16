"""Accueil du compagnon : état de Windows et son action principale, applications ouvertes avec
leur mode d'affichage ; à droite l'écran en direct et le mode d'affichage en cours. Les réglages
restent dans leurs pages (Affichage, Windows) : l'Accueil résume et renvoie."""

import os
import threading
import time

from gi.repository import GLib, Granite, Gtk, Pango

from . import control, desktop, power, vm, winctl
from .companion_common import card, clear, columns, dash_card, dim, help_button, mode_chip, notify_failure
from .i18n import N_, _
from .winctl import APP_ID

CLOCK_TICKS = os.sysconf("SC_CLK_TCK")


def qemu_usage(pid, previous=None):
    """Processeur (en % d'un cœur, depuis la mesure précédente) et mémoire réelle de QEMU."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        cpu = int(fields[11]) + int(fields[12])   # utime + stime, en tops d'horloge
        with open(f"/proc/{pid}/status") as f:
            rss = next((int(line.split()[1]) for line in f if line.startswith("VmRSS:")), 0)
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    now = time.monotonic()
    pct = None
    if previous and previous[0] == pid and now > previous[2]:
        pct = 100 * (cpu - previous[1]) / CLOCK_TICKS / (now - previous[2])
    return {"sample": (pid, cpu, now), "cpu": pct, "rss_mb": rss // 1024}


def phase(state):
    """« stopped », « starting », « ready », « asleep »."""
    host = state.get("host") or {}
    if not state.get("pid"):
        return "stopped"
    if host.get("paused"):
        return "asleep"
    return "ready" if host.get("guest_ready") else "starting"


TITLES = {
    "stopped": (N_("Windows est arrêté"), N_("Windows démarre automatiquement à "
                                             "l'ouverture d'une application Windows.")),
    "starting": (N_("Windows démarre…"), N_("Les applications demandées s'ouvriront dès que Windows sera prêt.")),
    "ready": (N_("Windows est prêt"), N_("Les applications Windows s'ouvrent immédiatement.")),
    "asleep": (N_("Windows est en veille"), N_("Windows sort de veille en une seconde à l'ouverture de la prochaine "
                                               "application Windows.")),
}


ICONS = {"stopped": "system-shutdown-symbolic", "starting": "content-loading-symbolic",
         "ready": "emblem-ok-symbolic", "asleep": "weather-clear-night-symbolic"}


class HomePage(Gtk.Box):
    __gtype_name__ = "VasistasHomePage"

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.shown_phase = None
        self.last_windows = None
        self.busy = False
        self.syncing = False
        page, outer, left, right = columns()
        self.append(page)
        outer.prepend(self.alerts_card())
        left.append(self.windows_card())
        left.append(self.apps_card())
        from .companion_display import LivePanel
        self.live = LivePanel(compact=True)
        right.append(self.live)
        right.append(self.display_card())

    def add_help(self, on_click):
        btn = help_button(on_click)
        self.win_head.append(btn)
        return btn

    # -- alertes : ce qui demande une action --

    def alerts_card(self):
        self.alerts = Gtk.Box(spacing=12, visible=False)
        for c in (Granite.STYLE_CLASS_CARD, Granite.STYLE_CLASS_ROUNDED, "dash-card"):
            self.alerts.add_css_class(c)
        self.alerts.append(Gtk.Image(icon_name="dialog-information-symbolic", valign=Gtk.Align.CENTER))
        self.alert_text = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.alerts.append(self.alert_text)
        btn = Gtk.Button(label=_("Mettre à jour Windows"), valign=Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_a: self.windows_update())
        self.alerts.append(btn)
        return self.alerts

    def show_alerts(self, ready):
        last = vm.load_config().get("last_windows_update")
        days = int((time.time() - last) / 86400) if last else None
        late = ready and (days is None or days > 30)
        if late:
            self.alert_text.set_label(_("Windows n'a pas été mis à jour depuis plus d'un mois.") if days else
                                      _("Les mises à jour de Windows n'ont jamais été lancées depuis Vasistas."))
        self.alerts.set_visible(late)

    # -- Windows --

    def windows_card(self):
        box, self.win_head = dash_card("Windows", "computer-symbolic", "blue")
        line = Gtk.Box(spacing=16)
        self.icon = Gtk.Image(icon_name="system-shutdown-symbolic", pixel_size=48)
        line.append(self.icon)
        # démarrage : une roue qui tourne dit que ça avance, l'icône fixe ne le disait pas
        self.spinner = Gtk.Spinner(width_request=48, height_request=48, visible=False)
        line.append(self.spinner)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class(Granite.STYLE_CLASS_H2_LABEL)
        self.subtitle = dim("")
        texts.append(self.title)
        texts.append(self.subtitle)
        line.append(texts)
        box.append(line)
        self.buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        box.append(self.buttons)
        return box

    def iter_buttons(self):
        b = self.buttons.get_first_child()
        while b:
            yield b
            b = b.get_next_sibling()

    def show_phase(self, p):
        if p == self.shown_phase:
            return
        self.shown_phase = p
        title, sub = TITLES[p]
        self.title.set_label(_(title))
        self.subtitle.set_label(_(sub))
        self.icon.set_from_icon_name(ICONS[p])
        self.icon.set_visible(p != "starting")
        self.spinner.set_visible(p == "starting")
        self.spinner.set_spinning(p == "starting")
        clear(self.buttons)
        # une action principale ; les autres dans le menu ⋯
        primary, others = {
            "stopped": ((_("Démarrer"), winctl.start), []),
            "asleep": ((_("Réveiller"), winctl.wake), [(_("Arrêter"), winctl.stop)]),
            "ready": ((_("Mettre en veille"), winctl.sleep),
                      [(_("Redémarrer"), winctl.restart), (_("Arrêter"), winctl.stop)]),
            "starting": (None, [(_("Arrêter"), winctl.stop)]),
        }[p]
        if others:
            pop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=4, margin_bottom=4)
            more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Autres actions"),
                                  popover=Gtk.Popover(child=pop))
            for label, fn in others:
                item = Gtk.Button(label=label)
                item.add_css_class(Granite.STYLE_CLASS_FLAT)
                item.get_child().set_xalign(0)
                self.wire(item, fn, more.popdown)
                pop.append(item)
            self.buttons.append(more)
        if primary:
            btn = Gtk.Button(label=primary[0])
            btn.add_css_class(Granite.STYLE_CLASS_SUGGESTED_ACTION)
            self.wire(btn, primary[1])
            self.buttons.append(btn)

    def wire(self, btn, fn, before=None):
        def run(_b):
            if before:
                before()
            for b in list(self.iter_buttons()):
                b.set_sensitive(False)

            def work():
                try:
                    fn()
                except (OSError, SystemExit, Exception) as e:  # noqa: BLE001 : message à l'utilisateur
                    notify_failure(self.win, e)
                GLib.idle_add(self.done_action)
            threading.Thread(target=work, daemon=True).start()
        btn.connect("clicked", run)

    def done_action(self):
        self.shown_phase = None  # boutons refaits au prochain état
        self.win.poll()
        return False

    # -- applications ouvertes --

    def apps_card(self):
        box, _head = dash_card(_("Applications ouvertes"), "view-app-grid-symbolic", "purple")
        self.windows_list = card()
        box.append(self.windows_list)
        return box

    def refresh_windows(self, ready):
        if not ready:
            self.show_windows([])
            return
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                wins = control.request({"windows": True}, timeout=1).get("windows") or []
            except (OSError, ValueError):
                wins = None
            GLib.idle_add(self._windows_done, wins)
        threading.Thread(target=work, daemon=True).start()

    def _windows_done(self, wins):
        self.busy = False
        if wins is not None:
            self.show_windows(wins)
        return False

    def show_windows(self, wins):
        main = [w for w in wins if w.get("kind") != "popup" and not w.get("owner")]
        modes = power.app_modes(vm.load_config())
        key = [(w.get("id"), w.get("title"), w.get("app")) for w in main] + [sorted(modes.items())]
        if key == self.last_windows:
            return
        self.last_windows = key
        clear(self.windows_list)
        if not main:
            self.windows_list.append(Gtk.Label(label=_("Aucune application Windows ouverte."),
                                               margin_top=14, margin_bottom=14))
            return
        reg = desktop.load_registry()
        for w in main:
            app = w.get("app") or ""
            line = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            icon = Gtk.Image(pixel_size=32)
            if app and desktop.app_icon_path(app).exists():
                icon.set_from_file(str(desktop.app_icon_path(app)))
            else:
                icon.set_from_icon_name(APP_ID)
            line.append(icon)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
            texts.append(Gtk.Label(label=w.get("title") or app, xalign=0, ellipsize=Pango.EllipsizeMode.END))
            texts.append(dim((reg.get(app) or {}).get("name") or app))
            line.append(texts)
            rule = modes.get(power.canonical(app))
            chip = mode_chip(rule, _(next(m[1] for m in power.MODES if m[0] == rule)) if rule else _("Par défaut"))
            chip.set_tooltip_text(_("Mode d'affichage de cette application"))
            line.append(chip)
            self.windows_list.append(line)

    def windows_update(self):
        general = self.win.show_page("general")
        if general is not None:
            general.windows_update()

    def go(self, name):
        if self.win.show_page(name) is None:
            self.win.notify(_("Cette page n'est pas disponible."))

    # -- affichage : résumé, le réglage est sur la page Affichage --

    def display_card(self):
        box, head = dash_card(_("Affichage"), "video-display-symbolic", "green")
        more = Gtk.Button(label=_("Régler l'affichage"), valign=Gtk.Align.CENTER)
        more.connect("clicked", lambda *_a: self.go("display"))
        head.append(more)
        self.mode_title = Gtk.Label(xalign=0)
        self.mode_title.add_css_class("tile-value")
        box.append(self.mode_title)
        self.mode_hint = dim("")
        box.append(self.mode_hint)
        return box

    def show_display(self, state):
        cfg = vm.load_config()
        i = power.mode_index(cfg)
        p = ((state.get("host") or {}).get("power") or {})
        if p.get("rule"):
            name = (desktop.load_registry().get(p.get("app")) or {}).get("name") or p.get("app") or ""
            mode = _(next(m[1] for m in power.MODES if m[0] == p["rule"]))
            self.mode_title.set_label(_("Mode {mode}", mode=mode))
            self.mode_hint.set_label(_("Défini pour l'application {app}.", app=name))
        elif i is None:
            self.mode_title.set_label(_("Réglages personnalisés"))
            self.mode_hint.set_label(_("Des réglages fins ont été modifiés dans les options avancées de la page "
                                       "Affichage."))
        else:
            self.mode_title.set_label(_("Mode {mode}", mode=_(power.MODES[i][1])))
            self.mode_hint.set_label(_(power.MODES[i][2]))

    def update(self, state):
        p = phase(state)
        self.show_phase(p)
        self.refresh_windows(p == "ready")
        self.show_alerts(p == "ready")
        self.live.refresh(state)
        self.show_display(state)
