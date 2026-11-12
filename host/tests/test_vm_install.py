import json
import socket
import threading

from vasistas import vm


def test_fin_d_installation_lue_sur_qmp(tmp_path, monkeypatch):
    path = tmp_path / "qmp-host.sock"
    monkeypatch.setattr(vm, "QMP_HOST", path)
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)

    def qemu():
        c, _ = srv.accept()
        f = c.makefile("rwb")
        f.write(b'{"QMP": {}}\n')
        f.flush()
        f.readline()  # qmp_capabilities
        for line in ({"return": {}}, {"event": "RESET", "data": {"reason": "guest-reset"}},
                     {"event": "SHUTDOWN", "data": {"guest": True, "reason": "guest-shutdown"}}):
            f.write(json.dumps(line).encode() + b"\n")
        f.flush()
        f.close()
        c.close()
    threading.Thread(target=qemu, daemon=True).start()
    reasons = []
    vm._watch_shutdown(reasons)
    assert reasons == ["guest-shutdown"]


def test_virtiofsd_args_lecture_seule_et_isolation():
    base = vm.virtiofsd_args("/d", "/s", "namespace")
    assert base[base.index("--sandbox") + 1] == "namespace" and "--readonly" not in base
    assert "--readonly" in vm.virtiofsd_args("/d", "/s", "none", readonly=True)


def test_partage_lecture_seule_dans_la_config(monkeypatch):
    cfg = {"shares": [{"tag": "A", "path": "/a", "drive": "X:", "readonly": True},
                      {"tag": "B", "path": "/b", "drive": "W:"}]}
    saved = {}
    monkeypatch.setattr(vm, "load_config", lambda: cfg)
    monkeypatch.setattr(vm, "save_config", saved.update)
    assert vm.share_readonly("A") and not vm.share_readonly("B") and not vm.share_readonly("C")
    vm.save_shares([("/a", "X:", "A"), ("/b", "W:", "B")])
    assert saved["shares"][0]["readonly"] is True and "readonly" not in saved["shares"][1]


def test_install_reconstruit_l_iso_sans_mot_de_passe(monkeypatch):
    calls = []
    monkeypatch.setattr(vm, "_check_files", lambda install: None)
    monkeypatch.setattr(vm, "pid", lambda: None)
    monkeypatch.setattr(vm, "load_config", lambda: {})
    monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(vm.shutil, "copyfile", lambda *a: None)
    monkeypatch.setattr(vm, "DISK", vm.Path("/nonexistent/vasistas.qcow2"))
    monkeypatch.setattr(vm, "build_share", lambda install: calls.append(install))
    monkeypatch.setattr(vm, "_run_install", lambda headless: 1 / 0)  # échec en cours d'installation
    try:
        vm.install()
    except ZeroDivisionError:
        pass
    assert calls == [False]


def test_configure_script_prefixe_le_mot_de_passe(monkeypatch, tmp_path):
    (tmp_path / "configure-windows.ps1").write_text("Write-Host 1", encoding="utf-8")
    monkeypatch.setattr(vm, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(vm, "load_config", lambda: {"password": "ab'c"})
    assert vm.configure_script() == "$AutoLogonPassword = 'ab''c'\nWrite-Host 1"
