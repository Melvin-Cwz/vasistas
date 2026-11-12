"""Étapes de l'installation, affichées en entête de l'assistant et animées au fil de l'eau :
Windows, configuration, applications, pilotes graphiques, mises à jour."""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .i18n import N_, _  # noqa: E402

# clé, nom court sous la pastille, titre affiché pendant l'étape
STAGES = [
    ("windows", N_("Windows"), N_("Installation de Windows")),
    ("configure", N_("Configuration"), N_("Configuration de Windows")),
    ("apps", N_("Applications"), N_("Installation de vos applications")),
    ("driver", N_("Pilotes graphiques"), N_("Installation des pilotes graphiques")),
    ("update", N_("Mises à jour"), N_("Mise à jour de Windows")),
]
TITLES = {key: title for key, _short, title in STAGES}

CSS = """
.vasistas-step-dot { min-width: 30px; min-height: 30px; border-radius: 15px;
    background: alpha(@text_color, 0.10); transition: background 400ms ease; }
.vasistas-step-dot.active { background: @accent_color; color: white; }
.vasistas-step-dot.done { background: @success_color; color: white; }
.vasistas-step-dot.failed { background: @error_color; color: white; }
.vasistas-step-dot.skipped { background: alpha(@text_color, 0.05); color: alpha(@text_color, 0.4); }
.vasistas-step-line { min-height: 2px; background: alpha(@text_color, 0.15); transition: background 600ms ease; }
.vasistas-step-line.done { background: @success_color; }
.vasistas-step-name { transition: opacity 400ms ease; opacity: 0.55; }
.vasistas-step-name.active, .vasistas-step-name.done { opacity: 1; }
"""
STATES = ("todo", "active", "done", "failed", "skipped")


def plan(installed, apps, driver, update):
    """État de départ de chaque étape : ce qui est déjà fait, et ce qui n'a pas lieu d'être.
    `installed` : Windows est déjà installé ; `apps` : au moins une application choisie ;
    `driver` : un pilote graphique à installer ; `update` : mise à jour de Windows demandée."""
    return {"windows": "done" if installed else "todo", "configure": "todo",
            "apps": "todo" if apps else "skipped", "driver": "todo" if driver else "skipped",
            "update": "todo" if update else "skipped"}


class Stepper(Gtk.Box):
    """Une pastille par étape, reliées par un trait qui se colore à mesure que l'on avance."""

    def __init__(self):
        super().__init__(margin_top=6, margin_bottom=6)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.items = {}
        for i, (key, short, _title) in enumerate(STAGES):
            # le trait d'une étape est à sa gauche : il se colore quand l'étape est atteinte
            line = Gtk.Box(hexpand=True, valign=Gtk.Align.START, margin_top=14)
            line.add_css_class("vasistas-step-line")
            if i:
                self.append(line)
            stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=300,
                              halign=Gtk.Align.CENTER)
            stack.add_css_class("vasistas-step-dot")
            stack.add_named(Gtk.Label(label=str(i + 1)), "todo")
            spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            stack.add_named(spinner, "active")
            for state, icon in (("done", "object-select-symbolic"), ("failed", "dialog-warning-symbolic"),
                                ("skipped", "list-remove-symbolic")):
                stack.add_named(Gtk.Image(icon_name=icon, pixel_size=16), state)
            name = Gtk.Label(label=_(short), wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=12,
                             width_chars=9)
            name.add_css_class("vasistas-step-name")
            name.add_css_class("small-label")
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            cell.append(stack)
            cell.append(name)
            self.append(cell)
            self.items[key] = (stack, spinner, name, line)

    def set_state(self, key, state):
        stack, spinner, name, line = self.items[key]
        for widget in (stack, name, line):
            for s in STATES:
                widget.remove_css_class(s)
        stack.add_css_class(state)
        name.add_css_class(state)
        if state in ("active", "done"):
            line.add_css_class("done")
        (spinner.start if state == "active" else spinner.stop)()
        stack.set_visible_child_name(state)

    def set_states(self, states):
        for key, state in states.items():
            self.set_state(key, state)
