"""Mise à jour intégrée : rien n'est téléchargé ni supprimé pour une version publiée douteuse."""

import pytest

from vasistas import updates


@pytest.mark.parametrize("release", [
    {"version": "../../Documents", "asset": "https://example.org/vasistas-1.tar.gz"},
    {"version": "current", "asset": "https://example.org/vasistas-1.tar.gz"},
    {"version": "", "asset": "https://example.org/vasistas-1.tar.gz"},
    {"version": "1.0.0", "asset": "file:///etc/passwd"},
    {"version": "1.0.0", "asset": "http://example.org/vasistas-1.tar.gz"},
])
def test_version_publiee_douteuse_refusee(release, tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "mode", lambda: "installed")
    monkeypatch.setattr(updates, "DATA", tmp_path / "data")
    monkeypatch.setattr(updates, "APP_ROOT", tmp_path / "opt")
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **k: pytest.fail("téléchargement tenté"))
    with pytest.raises(updates.UpdateError):
        updates.install(release)
    assert not (tmp_path / "opt").exists()


def test_numeros_de_version_acceptes():
    for v in ("1.0.0", "1.0.0-beta", "0.11.0", "2.0.0~beta1"):
        assert updates._VERSION.fullmatch(v)
