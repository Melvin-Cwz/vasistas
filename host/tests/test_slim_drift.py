from vasistas import slim


def test_drifted():
    before = {"sysmain": "on", "svc-light": "on", "wsearch": "off", "caps": "on", "inconnu": "on"}
    now = {"sysmain": "off", "svc-light": "partial", "wsearch": "off", "caps": "on", "inconnu": "off"}
    assert slim.drifted(before, now) == ["svc-light", "sysmain"]
