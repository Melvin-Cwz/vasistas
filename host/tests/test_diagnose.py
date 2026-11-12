"""Diagnostic : anonymisation du rapport, liste des paquets (diagnose.py)."""

from vasistas import diagnose

HOME = "/home/marie"
SHARES = [("/home/marie/Documents", "Documents"), ("/home/marie/Projets Dupont", "Projets Dupont")]


def anon(text):
    return diagnose.anonymize(text, HOME, "marie", host="portable-marie", secrets=["s3cr3tP4ss"],
                              shares=SHARES, drives=["Z:", "X:"], windows_user="")


def test_password_never_appears():
    out = anon('config {"user": "vasistas", "password": "s3cr3tP4ss"}')
    assert "s3cr3tP4ss" not in out
    assert "<secret>" in out


def test_shared_files_hidden_with_spaces():
    out = anon("2026-10-04 INFO ouverture de /home/marie/Documents/Bilan 2025 final.docx -> Z:\\Bilan 2025 final.docx")
    assert "Bilan" not in out and "final" not in out
    assert "<partage" in out and "Z:\\<fichier>" in out


def test_custom_share_label_hidden():
    out = anon("partage ajouté : Projets Dupont (X:)")
    assert "Dupont" not in out


def test_generic_labels_kept():
    assert "Documents" in anon("lecteur Documents (Linux) remonté")


def test_home_user_host_email():
    out = anon("lecture de /home/marie/.local/share/vasistas/apps.json par marie sur portable-marie, "
               "compte marie.martin@example.org, ~/Images/vacances.png")
    assert "marie" not in out.replace("<utilisateur>", "")
    assert "portable-marie" not in out
    assert "example.org" not in out
    assert "vacances" not in out
    # chemins de configuration (dossiers cachés) gardés lisibles
    assert "~/.local/share/vasistas/apps.json" in out


def test_windows_profile_path():
    out = anon(r"C:\Users\Marie\AppData\Local\Temp\x.tmp")
    assert "Marie" not in out
    assert r"C:\Users\<utilisateur>\AppData" in out


def test_vasistas_words_untouched():
    # le compte Windows par défaut s'appelle « vasistas » : les noms de modules ne doivent pas bouger
    out = diagnose.anonymize("vasistas.app INFO prêt", HOME, "marie", windows_user="")
    assert out == "vasistas.app INFO prêt"


def test_required_packages_from_install_sh():
    pkgs = diagnose.required_packages()
    assert "qemu-system-x86" in pkgs and "virtiofsd" in pkgs


def test_network_identifiers_masked():
    out = anon("eth0 52:54:00:12:34:56 ip 192.168.1.42 via 8.8.8.8, invité 10.0.2.15, lo 127.0.0.1, "
               "v6 2a01:cb00:1234:5678::1 local fe80::1 boucle ::1 heure 12:30:45")
    assert "52:54" not in out and "<mac>" in out
    assert "192.168" not in out and "8.8.8.8" not in out
    assert "10.0.2.15" in out and "127.0.0.1" in out
    assert "2a01" not in out and "fe80::1" in out and "::1" in out and "12:30:45" in out


def test_wifi_names_masked():
    out = anon("connexion ESSID: \"BoxDeMarie\" ok\nSSID=Cafe du coin\nnmcli: MaBox:wpa2\nlien suivant")
    assert "BoxDeMarie" not in out and "Cafe" not in out and "MaBox" not in out
    assert "lien suivant" in out


def test_url_credentials_and_tokens_masked():
    out = anon("GET https://bob:hunter2@exemple.org/x?token=abc123&a=1&api_key=zzz&key=yyy")
    for leak in ("bob", "hunter2", "abc123", "zzz", "yyy"):
        assert leak not in out
    assert "a=1" in out


def test_short_user_name_masked():
    out = diagnose.anonymize("session al sur pc ; plus loin alors", "/home/al", "al", host="pc")
    assert "<utilisateur>" in out and "<machine>" in out and "alors" in out
