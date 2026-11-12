"""Vasistas Beta : choix de la carte, lecture de vulkaninfo, arguments de QEMU (accel.py)."""
from vasistas import accel

VULKANINFO = """
GPU0:
VkPhysicalDeviceProperties:
	deviceName        = AMD Radeon 890M Graphics (RADV STRIX1)
	vendorID          = 0x1002
	deviceID          = 0x150e
	deviceType        = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
	deviceUUID        = 00000000-6500-0000-0000-000000000000
VkPhysicalDevicePCIBusInfoPropertiesEXT:
	pciDomain   = 0
	pciBus      = 101
	pciDevice   = 0
	pciFunction = 0
GPU1:
	deviceName        = NVIDIA GeForce RTX 5060 Laptop GPU
	vendorID          = 0x10de
	deviceID          = 0x2d59
	deviceType        = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
	deviceUUID        = 11111111-2222-3333-4444-555555555555
GPU2:
	deviceName        = llvmpipe (LLVM 21.1.8, 256 bits)
	vendorID          = 0x10005
	deviceID          = 0x0000
	deviceType        = PHYSICAL_DEVICE_TYPE_CPU
	deviceUUID        = 6c6c766d-7069-7065-5555-494400000000
"""


def test_vulkaninfo_sans_llvmpipe():
    cards = accel._parse_vulkaninfo(VULKANINFO)
    assert [c["kind"] for c in cards] == ["integrated", "discrete"]
    assert cards[0]["pci"] == "0000:65:00.0" and cards[0]["vendor"] == 0x1002
    assert cards[1]["pci"] is None


def test_choix_automatique_suit_la_puissance():
    cards = accel._parse_vulkaninfo(VULKANINFO)
    assert accel.choose(cards, "auto", "battery")["kind"] == "integrated"
    assert accel.choose(cards, "auto", "balanced")["kind"] == "integrated"
    assert accel.choose(cards, "auto", "performance")["kind"] == "discrete"
    assert accel.choose(cards, "integrated", "performance")["kind"] == "integrated"
    assert accel.choose(cards, cards[1]["uuid"], "battery") is cards[1]
    # carte dédiée éteinte : la seule carte présente
    assert accel.choose(cards[:1], "discrete", "performance") is cards[0]
    assert accel.choose([], "auto", "balanced") is None


def test_memoire_partagee():
    assert accel.hostmem({}, "battery") == 2048
    assert accel.hostmem({}, "performance") == 8192
    assert accel.hostmem({"accel_hostmem": 4096}, "battery") == 4096
    assert accel.hostmem({"accel_hostmem": 12}, "balanced") == 4096  # valeur absurde ignorée


def test_arguments_qemu():
    plan = {"gpu": {"uuid": "u-1"}, "hostmem": 2048, "display_node": "/dev/dri/renderD128", "isolated": True}
    dev, disp = accel.qemu_args(plan, (2880, 1800))
    assert dev[:2] == ["-vga", "none"]
    assert "host-gpu=u-1" in dev[3] and "hostmem=2048M" in dev[3] and "modes=2880x1800" in dev[3]
    assert "renderer=" in dev[3]
    assert disp == ["-display", "dbus,p2p=yes,gl=on,rendernode=/dev/dri/renderD128"]
    # pilote pas encore installé : virtio-vga d'abord (console 0), affichage sans GL
    dev, disp = accel.qemu_args(plan, (2880, 1800), setup=True)
    assert dev[1].startswith("virtio-vga") and dev[3].startswith("virtio-gpu-av-pci")
    assert disp == ["-display", "dbus,p2p=yes"]


def test_adapters_txt():
    cards = accel._parse_vulkaninfo(VULKANINFO)
    assert accel.adapters_txt(cards[:1]) == b"1002\t150e\tAMD Radeon 890M Graphics (RADV STRIX1)\r\n"


def test_noeud_de_rendu_jamais_repris_du_cache(tmp_path, monkeypatch):
    """Les nœuds DRM changent de numéro d'un démarrage à l'autre : le cache ne garde que la carte."""
    import json
    card = {"uuid": "u", "name": "n", "kind": "integrated", "vendor": 0x1002, "device": 1,
            "pci": "0000:65:00.0", "render_node": "/dev/dri/renderD128"}
    monkeypatch.setattr(accel, "_pci_signature", lambda: "sig")
    monkeypatch.setattr(accel, "_render_node", lambda vendor, pci=None: "/dev/dri/renderD129")
    (tmp_path / "gpus.json").write_text(json.dumps({"pci": "sig", "gpus": [card]}))
    assert accel.gpus(cache_dir=tmp_path)[0]["render_node"] == "/dev/dri/renderD129"


def test_credits_de_l_auteur():
    assert "acceleration3" in accel.credits() and "github.com/acceleration3/accel-virt" in accel.credits()
