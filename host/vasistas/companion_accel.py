"""Carte « Accélération graphique » de la page Affichage, dans Vasistas Beta seulement.

Elle montre d'un coup d'œil le chemin de l'image (Windows → carte graphique → bureau), son
état en direct (images composées par la carte graphique, par seconde), et les deux réglages
qui comptent : la carte utilisée et la mémoire partagée. Le pilote de Windows s'installe ou se
retire d'ici, avec un point de restauration avant l'installation."""

import threading
import time

from gi.repository import GLib, Granite, Gtk

from . import accel, control, power, vm
from .companion_common import confirm, dash_card, dim, guest_ready, row, tile
from .i18n import N_, _

GPU_CHOICES = [("auto", N_("Automatique")), ("integrated", N_("Intégrée")), ("discrete", N_("Dédiée"))]
MEM_CHOICES = [(None, N_("Automatique")), (2048, N_("2 Go")), (4096, N_("4 Go")), (8192, N_("8 Go"))]

CSS = """
.accel-flow { padding: 12px 14px; border-radius: 8px; background: alpha(@theme_fg_color, 0.04); }
.accel-step { padding: 6px 10px; border-radius: 6px; background: alpha(@theme_fg_color, 0.07); }
.accel-step.on { background: alpha(#68B723, 0.18); }
.accel-step.gpu.on { background: alpha(#A56DE2, 0.22); }
.accel-link { min-width: 22px; min-height: 2px; border-radius: 1px; background: alpha(@theme_fg_color, 0.2); }
.accel-link.on { background: #68B723; }
.accel-link.pulse { background: #9BDB4D; }
.beta-chip { padding: 2px 9px; border-radius: 999px; font-size: 0.8em; font-weight: 700;
  color: #fff; background: #F37329; }
"""


def short_gpu(name):
    """« AMD Radeon 890M Graphics (RADV STRIX1) » → « Radeon 890M »."""
    if not name:
        return _("carte graphique")
    name = name.split(" (")[0].replace(" Graphics", "")
    for brand in ("AMD ", "NVIDIA GeForce ", "NVIDIA ", "Intel(R) ", "Intel "):
        name = name.replace(brand, "")
    return name.strip()


class AccelCard(Gtk.Box):
    def __init__(self, win, banner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.banner = win, banner
        self.frames = None
        self.busy = False
        self.installing = False
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(self.get_display() or win.get_display(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box, head = dash_card(_("Accélération graphique"), "applications-graphics-symbolic", "purple")
        beta = Gtk.Label(label=_("BÊTA"), valign=Gtk.Align.CENTER)
        beta.add_css_class("beta-chip")
        head.append(beta)
        self.append(box)

        # chemin de l'image : trois étapes reliées, allumées quand tout fonctionne
        flow = Gtk.Box(spacing=8, halign=Gtk.Align.FILL)
        flow.add_css_class("accel-flow")
        self.steps, self.links = [], []
        for i, (icon, text) in enumerate((("computer-symbolic", _("Windows")),
                                          ("applications-graphics-symbolic", ""),
                                          ("video-display-symbolic", _("Bureau")))):
            if i:
                link = Gtk.Box(valign=Gtk.Align.CENTER, hexpand=True)
                link.add_css_class("accel-link")
                flow.append(link)
                self.links.append(link)
            step = Gtk.Box(spacing=6)
            step.add_css_class("accel-step")
            if i == 1:
                step.add_css_class("gpu")
            step.append(Gtk.Image(icon_name=icon))
            label = Gtk.Label(label=text)
            step.append(label)
            flow.append(step)
            self.steps.append((step, label))
        box.append(flow)
        self.summary = Gtk.Label(xalign=0, wrap=True)
        box.append(self.summary)

        tiles = Gtk.Box(spacing=10, homogeneous=True)
        t, self.fps_label = tile(_("Compositions/s"))
        t.set_tooltip_text(_("Images que Windows a composées sur la carte graphique, chaque seconde"))
        tiles.append(t)
        t, self.card_label = tile(_("Carte"))
        tiles.append(t)
        t, self.mem_label = tile(_("Mémoire partagée"))
        tiles.append(t)
        box.append(tiles)

        cfg = vm.load_config()
        self.cards = accel.gpus()
        kinds = {c["kind"] for c in self.cards}
        self.gpu_drop = Gtk.DropDown.new_from_strings([_(lbl) for _k, lbl in GPU_CHOICES])
        cur = cfg.get("accel_gpu", "auto")
        self.gpu_drop.set_selected(next((i for i, (k, _l) in enumerate(GPU_CHOICES) if k == cur), 0))
        self.gpu_drop.connect("notify::selected", self.on_gpu)
        self.gpu_drop.set_sensitive(len(kinds) > 1)
        gpu_help = (_("Automatique : la carte intégrée, plus économe, sauf en mode Performance.")
                    if len(kinds) > 1 else
                    _("Une seule carte graphique est disponible pour Windows. La carte dédiée apparaît ici "
                      "lorsqu'elle est allumée."))
        box.append(row(_("Carte utilisée"), gpu_help, self.gpu_drop))

        self.mem_drop = Gtk.DropDown.new_from_strings([_(lbl) for _k, lbl in MEM_CHOICES])
        cur = cfg.get("accel_hostmem")
        self.mem_drop.set_selected(next((i for i, (k, _l) in enumerate(MEM_CHOICES) if k == cur), 0))
        self.mem_drop.connect("notify::selected", self.on_mem)
        box.append(row(_("Mémoire partagée"), _("Zone où Windows et la carte graphique échangent leurs données. "
                                                "Automatique : 2 Go sur batterie, 4 Go en équilibré, 8 Go en "
                                                "Performance."), self.mem_drop))

        actions = Gtk.Box(spacing=8)
        self.install_btn = Gtk.Button(label=_("Installer le pilote dans Windows"))
        self.install_btn.add_css_class(Granite.STYLE_CLASS_SUGGESTED_ACTION)
        self.install_btn.connect("clicked", lambda *_a: self.install())
        actions.append(self.install_btn)
        self.remove_btn = Gtk.Button(label=_("Retirer le pilote"))
        self.remove_btn.add_css_class("flat")
        self.remove_btn.connect("clicked", lambda *_a: self.ask_remove())
        actions.append(self.remove_btn)
        self.spinner = Gtk.Spinner(visible=False)
        actions.append(self.spinner)
        box.append(actions)
        self.progress = dim("")
        self.progress.set_visible(False)
        box.append(self.progress)
        version = accel.version()
        self.footer = dim(accel.credits() + (" " + _("Version {version}.", version=version) if version else ""))
        self.footer.set_selectable(True)
        box.append(self.footer)
        self.show_static()

    # -- réglages --

    def on_gpu(self, d, _p):
        cfg = vm.load_config()
        cfg["accel_gpu"] = GPU_CHOICES[d.get_selected()][0]
        vm.save_config(cfg)
        self.banner.need("accel")
        self.show_static()

    def on_mem(self, d, _p):
        cfg = vm.load_config()
        mb = MEM_CHOICES[d.get_selected()][0]
        if mb is None:
            cfg.pop("accel_hostmem", None)
        else:
            cfg["accel_hostmem"] = mb
        vm.save_config(cfg)
        self.banner.need("accel")
        self.show_static()

    # -- état --

    def show_static(self):
        """Ce qui ne dépend pas de Windows en marche : compilation, pilote, prochain choix."""
        cfg = vm.load_config()
        lacking = accel.missing()
        need_driver = accel.needs_setup(cfg)
        plan = accel.last_plan() if vm.pid() else None
        nxt = accel.choose(self.cards, cfg.get("accel_gpu", "auto"), power.boot_profile(cfg))
        card = (plan or {}).get("gpu") or nxt
        self.steps[1][1].set_label(short_gpu(card and card["name"]))
        self.card_label.set_label(short_gpu(card and card["name"]))
        mb = (plan or {}).get("hostmem") or accel.hostmem(cfg, power.boot_profile(cfg))
        self.mem_label.set_label(_("{n} Go", n=mb // 1024))
        self.install_btn.set_visible(not lacking and need_driver and not self.installing)
        self.remove_btn.set_visible(not lacking and not need_driver and not self.installing)
        if lacking:
            self.summary.set_label(_("accel-virt n'est pas compilé sur cet ordinateur : il manque {path}. "
                                     "Voir docs/acceleration-graphique.md.", path=lacking[0].name))
        elif need_driver:
            self.summary.set_label(_("Windows n'a pas encore le pilote graphique. Démarrez Windows, puis "
                                     "installez-le : Vasistas crée d'abord un point de restauration."))

    def update(self, state):
        if self.installing:
            return
        self.show_static()
        ready = guest_ready(state)
        if not ready or accel.needs_setup(vm.load_config()) or accel.missing():
            self.light(False)
            self.fps_label.set_label("–")
            self.frames = None
            if not accel.missing() and not accel.needs_setup(vm.load_config()):
                self.summary.set_label(_("Au prochain démarrage, Windows dessinera sur la {gpu}.",
                                         gpu=self.card_label.get_label()))
            return
        if self.busy or not self.get_mapped():
            return
        self.busy = True

        def work():
            try:
                stats = control.request({"stats": True}, timeout=1)
            except (OSError, ValueError):
                stats = {}
            GLib.idle_add(self.show_live, stats)
        threading.Thread(target=work, daemon=True).start()

    def light(self, on, pulse=False):
        for step, _l in self.steps:
            (step.add_css_class if on else step.remove_css_class)("on")
        for link in self.links:
            (link.add_css_class if on else link.remove_css_class)("on")
            (link.add_css_class if pulse else link.remove_css_class)("pulse")

    def show_live(self, stats):
        self.busy = False
        now = time.monotonic()
        on = bool(stats.get("gpu"))
        frames = stats.get("gpu_frames")
        fps = None
        if frames is not None and self.frames is not None and now > self.frames[1]:
            fps = (frames - self.frames[0]) / (now - self.frames[1])
        if frames is not None:
            self.frames = (frames, now)
        self.light(on, pulse=bool(fps))
        self.fps_label.set_label("–" if fps is None else str(round(fps)))
        gpu = self.card_label.get_label()
        if on:
            self.summary.set_label(
                _("Windows dessine sur la {gpu} : Direct3D, Vulkan et OpenGL tournent sur la carte graphique, "
                  "et l'image arrive au bureau sans passer par le processeur.", gpu=gpu) if fps is None or fps > 0.5
                else _("Windows dessine sur la {gpu}. L'écran ne change pas : rien n'est recomposé.", gpu=gpu))
        else:
            self.summary.set_label(_("La carte graphique accélérée ne fournit pas encore d'image. Si cela dure, "
                                     "redémarrez Windows."))
        return False

    # -- pilote --

    def say(self, text):
        GLib.idle_add(self._say, text)

    def _say(self, text):
        self.progress.set_label(text)
        self.progress.set_visible(bool(text))
        return False

    def install(self):
        if not guest_ready(self.win.state):
            self.win.notify(_("Démarrez d'abord Windows"))
            return
        self._run(accel.install, _("Pilote installé : Windows redémarre sur la carte graphique accélérée."))

    def ask_remove(self):
        confirm(self.win, _("Retirer le pilote graphique ?"),
                _("Windows reprendra l'affichage habituel, dessiné par le processeur, au prochain démarrage."),
                _("Retirer"), lambda: self._run(accel.remove, _("Pilote retiré. Redémarrez Windows pour revenir à "
                                                               "l'affichage habituel.")))

    def _run(self, fn, done):
        self.installing = True
        self.install_btn.set_visible(False)
        self.remove_btn.set_visible(False)
        self.spinner.set_visible(True)
        self.spinner.start()

        def work():
            try:
                fn(say=self.say)
                msg = done
            except Exception as e:  # noqa: BLE001 - message lisible, l'essai reste possible
                msg = _("Échec : {e}", e=str(e).splitlines()[0])
            GLib.idle_add(self._finished, msg)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, msg):
        self.installing = False
        self.spinner.stop()
        self.spinner.set_visible(False)
        self._say(msg)
        self.show_static()
        return False
