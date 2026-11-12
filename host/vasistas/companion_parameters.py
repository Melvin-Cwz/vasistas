"""Page « Paramètres » du compagnon (maquette docs/maquettes/tableau-de-bord.html).

« Essentiels » : les paramètres courants, avec un curseur pour tout ce qui se dose (processeur,
mémoire vive, délai de mise en veille, points de restauration conservés). Chaque curseur porte
son repère « recommandé » et la page prévient quand Linux n'a plus assez de ressources.
« Avancés » : le sommaire des pages de réglages existantes, classées par thème.
"""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Granite", "7.0")
from gi.repository import Granite, Gtk  # noqa: E402

from . import restore, sleep, vm, winctl  # noqa: E402
from .companion_common import card, dim, notify_failure  # noqa: E402
from .companion_dashboard import ParametersHub, heading, load_css  # noqa: E402
from .companion_windows import AUTOSTART, write_autostart  # noqa: E402
from .i18n import _, current  # noqa: E402

SLEEP_VALUES = [1, 2, 5, 10, 15, 30, 60, 0]   # minutes sans fenêtre ; 0 : jamais
KEEP_VALUES = list(range(1, 11))
RECOMMENDED = {"cpus": 4, "memory": 8, "sleep": 5, "keep": restore.KEEP_DEFAULT}
MIN_MEMORY, LINUX_RESERVE = 2, 4              # Go : plancher de Windows, part toujours laissée à Linux


def host_cpus():
    return os.cpu_count() or 4


def host_memory():
    """Mémoire vive de l'ordinateur, en Go entiers."""
    return max(MIN_MEMORY + LINUX_RESERVE, vm.host_memory_gb())


def configured():
    """(cœurs, mémoire vive en Go) réglés : les valeurs personnalisées, sinon celles du profil
    choisi (et non du profil du moment : sur batterie, vm.resources() donne « Économie d'énergie »)."""
    cpus, memory = vm.custom_resources() or vm.RESOURCES[winctl.resources()]
    return cpus, int(str(memory).rstrip("G"))


def cpu_values(total):
    return list(range(1, max(1, total) + 1))


def memory_values(total):
    """Mémoire vive proposée à Windows : de 2 Go à ce qui laisse 4 Go à Linux, par pas de 2 Go."""
    return list(range(MIN_MEMORY, max(MIN_MEMORY, total - LINUX_RESERVE) + 1, 2))


def nearest(values, value):
    """Indice de la valeur la plus proche (un réglage écrit à la main peut tomber entre deux ;
    s'il n'est pas un nombre, la première)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return min(range(len(values)), key=lambda i: abs(values[i] - value))


def marks(values, recommended):
    """Indices des repères d'un curseur : les deux bouts, la valeur recommandée, et le milieu
    s'il est assez loin des autres."""
    last = len(values) - 1
    out = {0, last}
    if recommended in values:
        out.add(values.index(recommended))
    middle = last // 2
    if last >= 6 and all(abs(middle - i) >= 2 for i in out):
        out.add(middle)
    return sorted(out)


def profile_for(cpus, memory):
    """Profil de ressources (clé de vm.RESOURCES) qui donne exactement ces valeurs, ou None."""
    for key, (c, m) in vm.RESOURCES.items():
        if (c, int(str(m).rstrip("G"))) == (cpus, memory):
            return key
    return None


def resources_warning(cpus, memory, total_cpus, total_memory):
    """Avertissement quand Linux n'a plus assez de mémoire vive ou de cœurs ; None sinon."""
    if total_memory - memory < 8 and memory > total_memory / 2:
        return _("Linux ne dispose plus que de {n} Go de mémoire vive : des ralentissements sont possibles.",
                 n=total_memory - memory)
    if cpus > total_cpus * 2 / 3:
        return plural(total_cpus - cpus,
                      _("Linux ne dispose plus que de {n} cœur : l'ordinateur peut manquer de réactivité."),
                      _("Linux ne dispose plus que de {n} cœurs : l'ordinateur peut manquer de réactivité."))
    return None


def plural(n, one, many, **fields):
    """Accord en nombre (textes déjà traduits) : en français, `one` pour 0 ou 1 ; en anglais,
    pour 1 seulement."""
    single = n == 1 if current() == "en" else n < 2
    return (one if single else many).format(n=n, **fields)


def config_stamp():
    """Change quand config.json est réécrit (par cette page ou par une autre)."""
    try:
        return vm.CONFIG.stat().st_mtime_ns
    except OSError:
        return None


def save(**values):
    cfg = vm.load_config()
    for key, value in values.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    vm.save_config(cfg)


class Slider(Gtk.Box):
    """Titre, valeur en clair et curseur à repères ; `on_change(valeur)` à chaque déplacement."""

    def __init__(self, title, subtitle, values, value, recommended, text, mark_text, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_top=10,
                         margin_bottom=6)
        self.values, self.text, self.on_change, self.syncing = values, text, on_change, False
        self.recommended = recommended
        head = Gtk.Box(spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        texts.append(Gtk.Label(label=title, xalign=0, wrap=True))
        if subtitle:
            texts.append(dim(subtitle))
        head.append(texts)
        self.value_label = Gtk.Label(xalign=1, valign=Gtk.Align.CENTER)
        self.value_label.add_css_class(Granite.STYLE_CLASS_H4_LABEL)
        head.append(self.value_label)
        self.append(head)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, max(1, len(values) - 1), 1)
        self.scale.set_draw_value(False)
        self.scale.set_round_digits(0)
        for i in marks(values, recommended):
            label = mark_text(values[i])
            if values[i] == recommended:
                label = _("{value} · recommandé", value=label)
            self.scale.add_mark(i, Gtk.PositionType.BOTTOM, label)
        self.scale.connect("value-changed", self.changed)
        self.append(self.scale)
        self.set_value(value)

    @property
    def value(self):
        return self.values[min(len(self.values) - 1, max(0, round(self.scale.get_value())))]

    def set_value(self, value):
        # config.json s'écrit aussi à la main : autre chose qu'un nombre vaut la valeur recommandée
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = self.recommended
        self.syncing = True
        self.scale.set_value(nearest(self.values, value))
        self.syncing = False
        self.value_label.set_label(self.text(self.value))

    def changed(self, _scale):
        self.value_label.set_label(self.text(self.value))
        if not self.syncing:
            self.on_change(self.value)


def choice(options, selected, on_change):
    """Sélecteur lié : [(clé, libellé)] ; rend (boîte, {clé: bouton})."""
    box = Gtk.Box(valign=Gtk.Align.CENTER)
    box.add_css_class("linked")
    box.add_css_class("vasistas-choice")
    buttons, first = {}, None
    for key, label in options:
        b = Gtk.ToggleButton(label=label, group=first, active=key == selected)
        first = first or b
        b.connect("toggled", lambda btn, k=key: btn.get_active() and on_change(k))
        box.append(b)
        buttons[key] = b
    return box, buttons


def labelled(title, subtitle, widget):
    """Ligne de réglage : titre et explication à gauche, contrôle à droite ; rend (ligne, explication)."""
    box = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=10, margin_bottom=10)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    texts.append(Gtk.Label(label=title, xalign=0, wrap=True))
    hint = dim(subtitle)
    texts.append(hint)
    box.append(texts)
    box.append(widget)
    return box, hint


def group(*children):
    lb = card()
    for child in children:
        lb.append(Gtk.ListBoxRow(activatable=False, child=child))
    return lb


class ParametersPage(Gtk.Box):
    __gtype_name__ = "VasistasParametersPage"

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        load_css()
        self.win = win
        self.syncing = False
        self.total_cpus, self.total_memory = host_cpus(), host_memory()

        head = Gtk.Box(spacing=12, margin_start=30, margin_end=30, margin_top=24)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title = Gtk.Label(label=_("Paramètres"), xalign=0)
        title.add_css_class("vasistas-title")
        self.level_hint = dim("")
        texts.append(title)
        texts.append(self.level_hint)
        head.append(texts)
        levels, _buttons = choice([("essentials", _("Essentiels")), ("advanced", _("Avancés"))], "essentials",
                                  self.show_level)
        head.append(levels)
        self.append(head)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.stack.add_named(Gtk.ScrolledWindow(child=self.essentials(), hscrollbar_policy=Gtk.PolicyType.NEVER),
                             "essentials")
        self.stack.add_named(Gtk.ScrolledWindow(child=ParametersHub(win),
                                                hscrollbar_policy=Gtk.PolicyType.NEVER), "advanced")
        self.append(self.stack)
        self.show_level("essentials")
        self.synced = None
        self.sync()

    def add_help(self, on_click):
        """Chaque page de réglages a son propre bouton d'aide."""

    def update(self, state):
        """Ces paramètres ne dépendent pas de l'état de Windows, mais se règlent aussi ailleurs
        (indicateur, pages Avancé, Restauration et Préférences) : relus quand ils ont changé."""
        key = (config_stamp(), os.path.exists(AUTOSTART))
        if key != self.synced:
            self.sync()

    def sync(self):
        """Affiche les réglages enregistrés, sans rien réécrire."""
        self.synced = (config_stamp(), os.path.exists(AUTOSTART))
        cfg = vm.load_config()
        cpus, memory = configured()
        self.cpus.set_value(cpus)
        self.memory.set_value(memory)
        self.show_resources()
        session, notify, auto = os.path.exists(AUTOSTART), cfg.get("windows_update_reminder") is not False, \
            restore.settings()
        self.syncing = True
        try:
            self.startup["session" if session else "demand"].set_active(True)
            self.updates["notify" if notify else "manual"].set_active(True)
            self.restore_auto.set_active(auto["auto"])
        finally:
            self.syncing = False
        self.sleep_delay.set_value(sleep.settings()["sleep_without_windows_minutes"] or 0)
        self.keep.set_value(auto["keep"])
        self.keep.set_sensitive(auto["auto"])
        self.show_startup(session)
        self.show_updates(notify)

    def save(self, **values):
        """Enregistre ; en cas d'échec (disque plein, dossier protégé), le dit et réaffiche les
        réglages réellement enregistrés."""
        try:
            save(**values)
        except OSError as e:
            notify_failure(self.win, e)
            self.synced = None

    def show_level(self, name):
        self.stack.set_visible_child_name(name)
        self.level_hint.set_label(
            _("Les paramètres courants. Chaque curseur indique la valeur recommandée.") if name == "essentials" else
            _("Tous les paramètres de Windows et de Vasistas, classés par thème."))

    # -- Essentiels --

    def essentials(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=30, margin_end=30, margin_top=6,
                      margin_bottom=30)
        box.append(heading(_("Ressources allouées à Windows")))
        box.append(self.resources_group())
        box.append(heading(_("Démarrage et mise en veille")))
        box.append(self.startup_group())
        box.append(heading(_("Mises à jour et sauvegarde")))
        box.append(self.updates_group())
        return box

    # ressources : profil, processeur, mémoire vive

    def resources_group(self):
        profiles, self.profiles = choice([(key, _(label)) for key, label, _hint in winctl.RESOURCES], None,
                                         self.on_profile)
        row, self.profile_hint = labelled(_("Profil"), "", profiles)
        self.cpus = Slider(_("Processeur"), None, cpu_values(self.total_cpus), RECOMMENDED["cpus"],
                           RECOMMENDED["cpus"],
                           lambda v: plural(v, _("{n} cœur sur {total}"), _("{n} cœurs sur {total}"),
                                            total=self.total_cpus), str, self.on_resources)
        self.memory = Slider(_("Mémoire vive"), None, memory_values(self.total_memory), RECOMMENDED["memory"],
                             RECOMMENDED["memory"],
                             lambda v: _("{n} Go sur {total}", n=v, total=self.total_memory),
                             lambda v: _("{n} Go", n=v), self.on_resources)
        self.split = Gtk.LevelBar(min_value=0, max_value=self.total_memory, margin_start=12, margin_end=12)
        self.split_label = dim("")
        self.split_label.set_margin_start(12)
        self.split_label.set_margin_bottom(10)
        self.warning = Gtk.Label(xalign=0, wrap=True, margin_start=12, margin_end=12, margin_bottom=10)
        share = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        share.append(self.memory)
        share.append(self.split)
        share.append(self.split_label)
        share.append(self.warning)
        return group(row, self.cpus, share)

    def show_resources(self):
        cpus, memory = self.cpus.value, self.memory.value
        # profil enregistré, et non déduit des curseurs : ils s'arrêtent à ce que l'ordinateur possède
        key = None if vm.custom_resources() else winctl.resources()
        self.syncing = True
        try:
            for k, button in self.profiles.items():
                button.set_active(k == key)
        finally:
            self.syncing = False
        hints = {k: hint for k, _label, hint in winctl.RESOURCES}
        self.profile_hint.set_label(_(hints[key]) if key else _("Personnalisé."))
        self.split.set_value(memory)
        self.split_label.set_label(_("Windows {win} Go · Linux {lin} Go", win=memory, lin=self.total_memory - memory))
        text = resources_warning(cpus, memory, self.total_cpus, self.total_memory)
        self.warning.set_label(text or _("Le reste demeure disponible pour Linux. Pris en compte au prochain "
                                         "démarrage de Windows."))
        (self.warning.add_css_class if text else self.warning.remove_css_class)("warning")
        (self.warning.remove_css_class if text else self.warning.add_css_class)(Granite.STYLE_CLASS_DIM_LABEL)

    def on_profile(self, key):
        if self.syncing:
            return
        try:
            winctl.set_resources(key)  # efface aussi les valeurs personnalisées
        except OSError as e:
            notify_failure(self.win, e)
        self.sync()

    def on_resources(self, _value):
        cpus, memory = self.cpus.value, self.memory.value
        key = profile_for(cpus, memory)
        try:
            if key:
                winctl.set_resources(key)
            else:
                # « Économie d'énergie » plafonne la mémoire à chaud et réserve les cœurs sobres :
                # des valeurs personnalisées n'y auraient pas d'effet
                if winctl.resources() == "battery":
                    winctl.set_resources("balanced")
                save(resources_custom={"cpus": cpus, "memory": memory})
        except OSError as e:
            notify_failure(self.win, e)
            self.synced = None
        self.show_resources()

    # démarrage et mise en veille

    def startup_group(self):
        start, self.startup = choice([("demand", _("À la demande")), ("session", _("À l'ouverture de session"))],
                                     None, self.on_startup)
        row, self.startup_hint = labelled(_("Démarrage de Windows"), "", start)
        self.sleep_delay = Slider(_("Mise en veille automatique"),
                                  _("Quand aucune fenêtre Windows n'est ouverte. La sortie de veille est "
                                    "immédiate."),
                                  SLEEP_VALUES, RECOMMENDED["sleep"], RECOMMENDED["sleep"],
                                  lambda v: plural(v, _("Après {n} minute"), _("Après {n} minutes")) if v
                                  else _("Jamais"),
                                  lambda v: _("{n} min", n=v) if v else _("Jamais"),
                                  lambda v: self.save(sleep_without_windows_minutes=v))
        return group(row, self.sleep_delay)

    def show_startup(self, session):
        self.startup_hint.set_label(
            _("Windows démarre en veille à l'ouverture de session : les applications s'ouvrent en quelques "
              "secondes, mais la mémoire vive est utilisée en permanence.") if session else
            _("30 secondes d'attente au premier lancement ; aucune ressource utilisée avant."))

    def on_startup(self, key):
        if self.syncing:
            return
        try:
            if key == "session":
                write_autostart(True)
                save(autostart_sleep=True)
            elif os.path.exists(AUTOSTART):
                os.unlink(AUTOSTART)
        except OSError as e:
            notify_failure(self.win, e)
        self.sync()  # ce qui est réellement en place, même après un échec

    # mises à jour et sauvegarde

    def updates_group(self):
        notify, self.updates = choice([("notify", _("Me prévenir")), ("manual", _("Manuelles"))], None,
                                      self.on_updates)
        row, self.updates_hint = labelled(_("Mises à jour de Windows"), "", notify)
        self.restore_auto = Gtk.Switch(valign=Gtk.Align.CENTER)
        points, _hint = labelled(_("Points de restauration automatiques"),
                                 _("Créés avant chaque installation, mise à jour ou changement de pilote."),
                                 self.restore_auto)
        self.keep = Slider(_("Nombre de points conservés"), None, KEEP_VALUES, RECOMMENDED["keep"],
                           RECOMMENDED["keep"], lambda v: plural(v, _("{n} point"), _("{n} points")), str,
                           lambda v: self.save(restore_keep=v))
        self.restore_auto.connect("notify::active", self.on_restore)
        return group(row, points, self.keep)

    def show_updates(self, notify):
        self.updates_hint.set_label(
            _("Un rappel sur l'accueil une fois par mois ; l'installation se lance d'un clic.") if notify else
            _("Aucun rappel ; Windows Update reste disponible dans Windows."))

    def on_updates(self, key):
        if self.syncing:
            return
        self.save(windows_update_reminder=key == "notify")
        self.show_updates(key == "notify")

    def on_restore(self, switch, _pspec):
        if self.syncing:
            return
        self.save(restore_auto=switch.get_active())
        self.keep.set_sensitive(switch.get_active())
