"""Bureau de Windows montré dans l'assistant d'installation.

L'écran est relu chaque seconde par une capture QMP (screendump) ; les clics et les touches
sont renvoyés à Windows, pour répondre à une question de l'installateur (clé refusée…).
shortcut: capture par seconde et clavier limité au bloc principal et aux flèches, suffisant
pour suivre une installation ; passer à l'affichage D-Bus de QEMU (display.py) pour un vrai
bureau interactif. Une fois le pilote accéléré en marche, QEMU n'a plus de surface à capturer :
l'aperçu le dit et les fenêtres de Vasistas prennent le relais.
"""

import queue
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import vm  # noqa: E402
from .i18n import _  # noqa: E402

# touches hors du bloc principal : code matériel de GDK (evdev + 8) -> qcode de QEMU
EXTENDED = {111: "up", 116: "down", 113: "left", 114: "right", 110: "home", 115: "end",
            119: "delete", 112: "pgup", 117: "pgdn", 104: "kp_enter"}
MODIFIERS = {50: "shift", 62: "shift_r", 37: "ctrl", 105: "ctrl_r", 64: "alt", 108: "alt_r"}


def key_values(keycode, shift=False, ctrl=False, alt=False):
    """Touches pour la commande QMP send-key, d'après le code matériel de GDK. Le bloc principal
    porte les mêmes numéros que les scancodes PC ; None pour une touche inconnue ou un
    modificateur seul (il part avec la touche suivante)."""
    if keycode in MODIFIERS:
        return None
    if keycode in EXTENDED:
        key = {"type": "qcode", "data": EXTENDED[keycode]}
    elif 1 <= keycode - 8 <= 88:
        key = {"type": "number", "data": keycode - 8}
    else:
        return None
    mods = [{"type": "qcode", "data": name} for name, on in (("ctrl", ctrl), ("alt", alt), ("shift", shift)) if on]
    return mods + [key]


def pointer(x, y, width, height, screen_w, screen_h):
    """Position absolue QMP (0 à 32767) d'un point de l'aperçu (width x height), où l'écran
    (screen_w x screen_h) est ajusté sans déformation et centré ; None hors de l'image."""
    if min(width, height, screen_w, screen_h) <= 0:
        return None
    scale = min(width / screen_w, height / screen_h)
    px = (x - (width - screen_w * scale) / 2) / scale
    py = (y - (height - screen_h * scale) / 2) / scale
    if not (0 <= px < screen_w and 0 <= py < screen_h):
        return None
    return int(px * 32767 / screen_w), int(py * 32767 / screen_h)


class ScreenView(Gtk.Overlay):
    """Aperçu de l'écran de Windows ; start() et stop() suivent sa visibilité."""

    def __init__(self):
        super().__init__(vexpand=True)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, focusable=True)
        self.picture.set_size_request(-1, 220)
        self.set_child(self.picture)
        self.note = Gtk.Label(label=_("En attente de l'écran de Windows…"), wrap=True, justify=Gtk.Justification.CENTER)
        self.note.add_css_class("dim-label")
        self.add_overlay(self.note)
        self.size = (0, 0)
        self.timer = 0
        self.jobs = queue.Queue()
        self.worker = None
        self.shot = vm.DATA / "screen.png"

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self.on_click)
        self.picture.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.picture.add_controller(keys)

    def start(self):
        if not self.timer:
            self.capture()
            self.timer = GLib.timeout_add(1000, self.capture)

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    # -- fil de travail : une seule connexion QMP à la fois, hors du fil de GTK --

    def submit(self, job):
        self.jobs.put(job)
        if not (self.worker and self.worker.is_alive()):
            self.worker = threading.Thread(target=self.work, name="vasistas-screenview", daemon=True)
            self.worker.start()

    def work(self):
        while True:
            try:
                job = self.jobs.get(timeout=5)
            except queue.Empty:
                return
            try:
                qmp = vm.Qmp(timeout=3)
                try:
                    job(qmp)
                finally:
                    qmp.close()
            except (OSError, EOFError, RuntimeError, ValueError) as e:
                GLib.idle_add(self.show, None, str(e))

    def capture(self):
        if self.jobs.empty():  # jamais deux captures en attente
            self.submit(self.dump)
        return True

    def dump(self, qmp):
        qmp.cmd("screendump", filename=str(self.shot), format="png")
        GLib.idle_add(self.show, str(self.shot), None)

    def show(self, path, error):
        texture = None
        if path:
            try:
                texture = Gdk.Texture.new_from_filename(path)
            except GLib.Error:
                pass
        if texture:
            self.size = (texture.get_width(), texture.get_height())
            self.picture.set_paintable(texture)
            self.note.set_visible(False)
        elif not vm.pid():
            self.picture.set_paintable(None)
            self.note.set_label(_("Windows est arrêté."))
            self.note.set_visible(True)
        elif error and "surface" in error:
            self.picture.set_paintable(None)
            self.note.set_label(_("Windows utilise maintenant la carte graphique accélérée : son bureau "
                                  "n'est plus visible ici. Les applications s'ouvrent dans leurs propres "
                                  "fenêtres."))
            self.note.set_visible(True)
        return False

    # -- souris et clavier vers Windows --

    def on_click(self, gesture, _n, x, y):
        self.picture.grab_focus()
        pos = pointer(x, y, self.picture.get_width(), self.picture.get_height(), *self.size)
        if not pos:
            return
        button = {1: "left", 2: "middle", 3: "right"}.get(gesture.get_current_button(), "left")
        move = [{"type": "abs", "data": {"axis": "x", "value": pos[0]}},
                {"type": "abs", "data": {"axis": "y", "value": pos[1]}}]

        def job(qmp):
            qmp.cmd("input-send-event", events=move)
            for down in (True, False):
                qmp.cmd("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": button}}])
            self.dump(qmp)
        self.submit(job)

    def on_key(self, _ctrl, _keyval, keycode, state):
        keys = key_values(keycode, shift=bool(state & Gdk.ModifierType.SHIFT_MASK),
                          ctrl=bool(state & Gdk.ModifierType.CONTROL_MASK),
                          alt=bool(state & Gdk.ModifierType.ALT_MASK))
        if not keys:
            return False
        self.submit(lambda qmp: qmp.cmd("send-key", keys=keys))
        return True
