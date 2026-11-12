"""Catalogue d'allègement : applications de Win11Debloat (tag 2026.08.24, vendoré) et exclusions."""
import json
from pathlib import Path

from vasistas import slim

VENDOR = Path(slim.__file__).parent / "vendor" / "win11debloat"
# Office, Outlook, Power BI du Store, Store, Edge : ne jamais supprimer
INTERDITS = {
    "Microsoft.MicrosoftOfficeHub", "Microsoft.MicrosoftPowerBIForWindows", "Microsoft.Office.OneNote",
    "Microsoft.OutlookForWindows", "microsoft.windowscommunicationsapps", "Microsoft.WindowsStore",
    "Microsoft.DesktopAppInstaller", "Microsoft.Edge", "Microsoft.WindowsTerminal",
}


def _appx():
    return [(it["key"], a) for it in slim.CATALOG for a in it.get("appx", [])]


def test_aucune_application_interdite():
    assert not [(k, a) for k, a in _appx() if a in INTERDITS]


def test_pas_de_doublon_entre_elements():
    ids = [a for _, a in _appx()]
    assert len(ids) == len(set(ids))


def test_listes_win11debloat_viennent_du_fichier_vendore():
    apps = json.loads((VENDOR / "Apps.json").read_text(encoding="utf-8-sig"))["Apps"]
    connus = set()
    for a in apps:
        v = a["AppId"]
        connus.update(v if isinstance(v, list) else [v])
    for it in slim.CATALOG:
        if it["key"] in ("apps-bloat", "apps-thirdparty"):
            assert set(it["appx"]) <= connus


def test_licence_et_commit_vendores():
    assert "MIT License" in (VENDOR / "LICENSE").read_text(encoding="utf-8-sig")
    assert (VENDOR / "COMMIT").read_text().strip().startswith("f431c561")


def test_niveaux_et_groupes_valides():
    for it in slim.CATALOG:
        assert it["level"] in slim.LEVELS
        assert it["group"] in slim.GROUPS
