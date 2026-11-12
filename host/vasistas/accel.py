"""Accélération graphique de Vasistas Beta : carte graphique paravirtuelle accel-virt.

accel-virt (https://github.com/acceleration3/accel-virt, projet LSW) donne à Windows un vrai
pilote WDDM 3.2 : DWM, Direct3D 9 à 12, Vulkan, OpenGL et OpenCL s'exécutent sur la carte
graphique de l'hôte (DXVK et vkd3d-proton côté Linux). L'écran composé reste sur la carte
graphique et arrive à l'hôte en dmabuf par l'affichage D-Bus (`-display dbus,gl=on`).

Ce module ne contient rien d'accel-virt : il trouve sa compilation locale
(~/.local/opt/accel-virt, VASISTAS_ACCEL_DIR), choisit la carte graphique et la taille de la
fenêtre mémoire partagée, et construit les arguments de QEMU. Seul le profil « beta »
(VASISTAS_PROFILE=beta) s'en sert.

Choix automatique de la carte (config « accel_gpu » = « auto ») : la carte intégrée sur
batterie et en équilibré (la carte dédiée reste éteinte, l'écran composé n'a pas à changer de
carte avant l'affichage), la carte dédiée en performance. La fenêtre mémoire (« hostmem »)
suit aussi le profil : c'est de la mémoire de la carte graphique, donc de la RAM sur une carte
intégrée.
"""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("VASISTAS_ACCEL_DIR", Path.home() / ".local/opt/accel-virt"))
QEMU = ROOT / "build-qemu/qemu/qemu-system-x86_64"
MODULES = ROOT / "build-qemu/qemu"
EXECUTOR = ROOT / "build-qemu/libav_executor.so"
RENDERER = ROOT / "build-qemu/av-renderer"
D3D = ROOT / "build-d3d/lib"
DRIVERS = ROOT / "build/av-drivers"
DEVICE_ID = "avgpu"   # id QEMU du dispositif : /machine/peripheral/avgpu pour qom-set

# Fenêtre mémoire partagée entre Windows et la carte graphique, en Mo, par profil de puissance
HOSTMEM = {"battery": 2048, "balanced": 4096, "performance": 8192}
CHOICES = ("auto", "integrated", "discrete")

DRM = Path("/sys/class/drm")


def missing():
    """Fichiers de la compilation locale qui manquent (liste vide : prêt)."""
    need = [QEMU, EXECUTOR, RENDERER, D3D / "libdxvk_d3d11.so", D3D / "libvkd3d-proton-d3d12.so",
            DRIVERS / "package/avgpu.sys", DRIVERS / "provision.ps1"]
    return [p for p in need if not p.exists()]


def available():
    return not missing()


def version():
    """Commit d'accel-virt compilé (court), ou None."""
    try:
        return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %cs"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# -- cartes graphiques --

def _pci_signature():
    """Cartes vidéo présentes (adresse:fabricant:modèle) : le cache des cartes est refait seulement
    si elles changent, pour ne pas réveiller la carte dédiée avec vulkaninfo à chaque démarrage."""
    sig = []
    for dev in sorted(Path("/sys/bus/pci/devices").glob("*")):
        try:
            if (dev / "class").read_text().startswith("0x03"):
                sig.append(f"{dev.name}:{(dev / 'vendor').read_text().strip()}:{(dev / 'device').read_text().strip()}")
        except OSError:
            continue
    return ",".join(sig)


def _render_node(vendor, pci=None):
    """/dev/dri/renderD12x de la carte (par adresse PCI si connue, sinon par fabricant)."""
    for node in sorted(DRM.glob("renderD*")):
        try:
            dev = (node / "device").resolve()
            if pci and dev.name == pci:
                return f"/dev/dri/{node.name}"
            if not pci and int((node / "device/vendor").read_text(), 16) == vendor:
                return f"/dev/dri/{node.name}"
        except (OSError, ValueError):
            continue
    return None


def _parse_vulkaninfo(text):
    """Cartes de `vulkaninfo` (sortie complète) : nom, type, UUID, identifiants et adresse PCI."""
    cards = []
    for block in re.split(r"^GPU\d+:\s*$", text, flags=re.M)[1:]:
        f = dict(re.findall(r"^\s*(deviceName|vendorID|deviceID|deviceType|deviceUUID|pciDomain|pciBus|pciDevice"
                            r"|pciFunction)\s*=\s*(.+?)\s*$", block, flags=re.M))
        if "deviceUUID" not in f:
            continue
        kind = {"PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU": "integrated",
                "PHYSICAL_DEVICE_TYPE_DISCRETE_GPU": "discrete"}.get(f.get("deviceType"), "other")
        if kind == "other":
            continue  # llvmpipe : Windows en logiciel, sans intérêt ici
        pci = None
        if "pciBus" in f:
            pci = "{:04x}:{:02x}:{:02x}.{:x}".format(*(int(f.get(k, "0"), 0) for k in
                                                      ("pciDomain", "pciBus", "pciDevice", "pciFunction")))
        vendor = int(f.get("vendorID", "0"), 0)
        if any(c["uuid"] == f["deviceUUID"] for c in cards):
            continue  # même carte vue par deux pilotes (fenêtrage, couche) : une seule fois
        cards.append({"uuid": f["deviceUUID"], "name": f.get("deviceName", "?"), "kind": kind,
                      "vendor": vendor, "device": int(f.get("deviceID", "0"), 0), "pci": pci,
                      "render_node": _render_node(vendor, pci)})
    return cards


def gpus(cache_dir=None, refresh=False):
    """Cartes graphiques Vulkan de l'hôte, mises en cache (gpus.json) tant que le matériel ne
    change pas."""
    from . import vm
    path = Path(cache_dir or vm.DATA) / "gpus.json"
    sig = _pci_signature()
    if not refresh:
        try:
            data = json.loads(path.read_text())
            if data.get("pci") == sig:
                # la numérotation des nœuds DRM change d'un démarrage à l'autre : jamais celle du cache
                return [{**c, "render_node": _render_node(c["vendor"], c.get("pci"))} for c in data["gpus"]]
        except (OSError, ValueError, KeyError):
            pass
    try:
        import shutil
        tool = shutil.which("vulkaninfo") or str(ROOT / "hostbin" / "vulkaninfo")
        out = subprocess.run([tool], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    cards = _parse_vulkaninfo(out)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pci": sig, "gpus": cards}, indent=1))
    except OSError:
        pass
    return cards


def choose(cards, choice, profile):
    """Carte retenue pour ce démarrage. `choice` : auto, integrated, discrete ou un UUID."""
    if not cards:
        return None
    by_uuid = next((c for c in cards if c["uuid"] == choice), None)
    if by_uuid:
        return by_uuid
    want = choice if choice in ("integrated", "discrete") else \
        ("discrete" if profile == "performance" else "integrated")
    return next((c for c in cards if c["kind"] == want), cards[0])


def display_node(cards):
    """Nœud de rendu de la carte qui affiche le bureau (l'intégrée sur un portable hybride) :
    QEMU y exporte l'écran en dmabuf, que GTK importe sans changer de carte."""
    card = next((c for c in cards if c["kind"] == "integrated"), cards[0] if cards else None)
    return card and card.get("render_node")


def hostmem(cfg, profile):
    mb = cfg.get("accel_hostmem")
    return int(mb) if isinstance(mb, int) and mb >= 1024 else HOSTMEM.get(profile, HOSTMEM["balanced"])


def plan(cfg, profile):
    """Ce que le prochain démarrage utilisera : carte, nœud d'affichage, fenêtre mémoire.
    Écrit aussi dans accel.json pour le compagnon (état affiché sans relancer vulkaninfo)."""
    from . import vm
    cards = gpus()
    card = choose(cards, cfg.get("accel_gpu", "auto"), profile)
    result = {"gpu": card, "display_node": display_node(cards), "hostmem": hostmem(cfg, profile),
              "profile": profile, "cards": cards, "isolated": True}
    try:
        (vm.DATA / "accel.json").write_text(json.dumps(result, indent=1))
    except OSError:
        pass
    return result


def last_plan():
    from . import vm
    try:
        return json.loads((vm.DATA / "accel.json").read_text())
    except (OSError, ValueError):
        return None


def qemu_args(p, screen, setup=False):
    """Arguments de QEMU pour la carte accélérée : (dispositifs, affichage).

    `setup` (pilote pas encore installé dans Windows) : virtio-vga reste la carte d'affichage,
    branchée en premier pour garder la console 0, et l'affichage reste en mémoire partagée ;
    la carte accélérée est seulement présente, pour que provision.ps1 la trouve."""
    w, h = screen
    gpu = p["gpu"]["uuid"] if p.get("gpu") else "auto"
    dev = (f"virtio-gpu-av-pci,id={DEVICE_ID},host-gpu={gpu},executor={EXECUTOR},"
           f"max_outputs=1,vectors=11,hostmem={p['hostmem']}M,xres={w},yres={h},modes={w}x{h}")
    if p.get("isolated"):
        # moteur de rendu dans un processus à part, toujours : un plantage du pilote Linux ne coûte
        # à Windows qu'une réinitialisation de la carte, et dans QEMU même, l'exécuteur rend son
        # propre contexte EGL courant et l'affichage dbus,gl=on de QEMU s'arrête sur une assertion
        # d'epoxy (essai du 2026-11-01)
        dev += f",renderer={RENDERER}"
    if setup:
        return ["-device", f"virtio-vga,xres={w},yres={h}", "-device", dev], ["-display", "dbus,p2p=yes"]
    display = "dbus,p2p=yes,gl=on"
    if p.get("display_node"):
        display += f",rendernode={p['display_node']}"
    return ["-vga", "none", "-device", dev], ["-display", display]


def qemu_env(base, data_dir):
    """Variables de QEMU, de l'exécuteur et du moteur de rendu. Les caches de shaders de DXVK et
    de vkd3d-proton sont gardés dans le dossier de données : la deuxième ouverture d'Office ou
    d'Edge ne recompile rien."""
    cache = Path(data_dir) / "shader-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(base)
    env.update({"QEMU_MODULE_DIR": str(MODULES), "AV_D3D_PATH": str(D3D),
                "DXVK_LOG_LEVEL": "warn", "DXVK_LOG_PATH": str(data_dir),
                "DXVK_STATE_CACHE_PATH": str(cache), "VKD3D_SHADER_CACHE_PATH": str(cache),
                "MESA_SHADER_CACHE_DIR": str(cache / "mesa"),
                "__GL_SHADER_DISK_CACHE_PATH": str(cache / "nvidia")})
    return env


def set_resolution(qmp, w, h):
    """Résolution de Windows en marche : le pilote ne lit pas SetUIInfo, il suit la liste de
    modes du dispositif ; un seul mode, et Windows y passe."""
    qmp.cmd("qom-set", path=f"/machine/peripheral/{DEVICE_ID}", property="modes", value=f"{w}x{h}")


# -- pilote dans Windows --

AUTHOR = "acceleration3"
PROJECT_URL = "https://github.com/acceleration3/accel-virt"


def credits():
    """Mention de l'auteur du pilote, montrée partout où Vasistas l'installe ou le décrit."""
    from .i18n import _
    return _("Pilote graphique accel-virt, créé par {author} ({url}) et compilé sur cet ordinateur.",
             author=AUTHOR, url=PROJECT_URL)


GUEST_SCRIPT = Path(__file__).resolve().parents[2] / "guest" / "accel" / "install-accel.ps1"


def package_hash():
    """Empreinte du paquet de pilotes compilé (son manifeste) : change à chaque compilation."""
    import hashlib
    try:
        return hashlib.sha256((DRIVERS / "package" / "package.sha256").read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def needs_setup(cfg):
    """Vrai tant que Windows n'a pas le pilote de cette compilation."""
    return cfg.get("accel_driver") != package_hash()


def adapters_txt(cards):
    """Noms des cartes pour l'INF (format de provision.ps1 : fabricant, modèle, nom)."""
    return "".join(f"{c['vendor']:04x}\t{c['device']:04x}\t{c['name']}\r\n" for c in cards).encode()


def share_files(cards):
    """Fichiers du CD de partage pour l'installation : paquet d'accel-virt et script."""
    files = {"accel/install-accel.ps1": b"\xef\xbb\xbf" + GUEST_SCRIPT.read_bytes(),
             "av/adapters.txt": adapters_txt(cards)}
    for path in sorted(DRIVERS.rglob("*")):
        if path.is_file():
            files["av/" + path.relative_to(DRIVERS).as_posix()] = path.read_bytes()
    return files


FIND_CD = ("$cd = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path (Join-Path $_.Root "
           "'vasistas.tag') } | Select-Object -First 1\n")


def _exec(script, timeout=900):
    from . import control
    res = control.request({"exec": script}, timeout=timeout)
    if res.get("error"):
        raise RuntimeError(res["error"])
    return res.get("code", 1), res.get("out", "")


def install(say=print):
    """Installe le pilote dans Windows (Vasistas Beta en marche, au premier démarrage), avec un
    point de restauration avant, puis redémarre Windows sur la carte accélérée seule."""
    from . import restore, vm
    say("point de restauration « avant-accel »…")
    try:
        restore.create(name="avant-accel")
    except Exception as e:  # noqa: BLE001 - un point manquant n'empêche pas l'essai
        say(f"  pas de point de restauration : {e}")
    say("installation du pilote dans Windows…")
    code, out = _exec(FIND_CD + "& (Join-Path $cd.Root 'accel\\install-accel.ps1')")
    for line in out.splitlines():
        if line.startswith("accel:"):
            say("  " + line[6:].strip())
    if code not in (0, 3010):
        raise RuntimeError(f"installation du pilote : code {code}\n{out[-2000:]}")
    cfg = vm.load_config()
    cfg["accel_driver"] = package_hash()
    vm.save_config(cfg)
    say("redémarrage de Windows sur la carte accélérée…")
    vm.stop()
    vm.start()
    return True


def remove(say=print):
    """Retire le pilote de Windows ; le démarrage suivant reprend l'affichage habituel."""
    from . import vm
    code, out = _exec(FIND_CD + "& (Join-Path $cd.Root 'accel\\install-accel.ps1') -Remove")
    say(out.strip())
    cfg = vm.load_config()
    cfg.pop("accel_driver", None)
    vm.save_config(cfg)
    return code == 0


# -- profil Beta --

CLONED = ("disk.qcow2", "OVMF_VARS.fd", "config.json", "apps.json", "windows.json", "update.json", "icons")


def clone_main(say=print):
    """Copie le Windows de Vasistas (disque, variables UEFI, réglages, icônes) dans le profil
    Beta, une seule fois. La VM principale doit être arrêtée : son disque ne doit pas bouger
    pendant la copie. Copie creuse, et instantanée sur un système de fichiers à reflink."""
    import shutil
    from . import vm
    if vm.DATA == vm.MAIN_DATA or (vm.DATA / "disk.qcow2").exists():
        return False
    try:
        main = int((vm.MAIN_DATA / "qemu.pid").read_text())
        if b"qemu-system" in Path(f"/proc/{main}/cmdline").read_bytes():
            raise RuntimeError("Arrêtez d'abord Windows dans Vasistas : la copie a besoin d'un disque immobile.")
    except (OSError, ValueError):
        pass
    vm.ensure_data()
    for name in CLONED:
        src, dst = vm.MAIN_DATA / name, vm.DATA / name
        if not src.exists():
            continue
        say(f"copie de {name}…")
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            tmp = dst.with_name(dst.name + ".tmp")
            subprocess.run(["cp", "--reflink=auto", "--sparse=always", str(src), str(tmp)], check=True)
            tmp.replace(dst)
    cfg = vm.load_config()
    for key in ("accel_driver", "gpu"):   # pilote à installer ; jamais de carte prêtée en Beta
        cfg.pop(key, None)
    vm.save_config(cfg)
    return True
