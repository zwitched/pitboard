from pitboard.netpolicy import host_header_allowed, hostname_of, is_loopback_peer, origin_matches_host
from pitboard.settings import SettingsError, parse_loopback_target


def test_loopback_policy():
    assert is_loopback_peer("127.0.0.1")
    assert is_loopback_peer("::1")
    assert not is_loopback_peer("10.0.0.4")
    assert not is_loopback_peer("testclient")
    assert is_loopback_peer("testclient", testing=True)
    assert hostname_of("[::1]:9477") == "::1"
    assert hostname_of("127.0.0.1:9477") == "127.0.0.1"
    assert host_header_allowed("127.0.0.1:9477", lan_active=False)
    assert not host_header_allowed("evil.example", lan_active=False)
    assert not host_header_allowed("testserver", lan_active=False)
    assert host_header_allowed("testserver", lan_active=False, testing=True)
    assert host_header_allowed("192.168.1.20:9477", lan_active=True)
    assert not host_header_allowed("192.168.1.20:9477", lan_active=False)
    assert origin_matches_host(None, "127.0.0.1:9477")
    assert origin_matches_host("http://127.0.0.1:9477", "127.0.0.1:9477")
    assert not origin_matches_host("http://evil.example", "127.0.0.1:9477")


def test_game_target_must_be_local():
    assert parse_loopback_target("127.0.0.1:2942") == "127.0.0.1:2942"
    try:
        parse_loopback_target("10.1.1.5:2942")
    except SettingsError as exc:
        assert "this computer" in str(exc)
    else:
        raise AssertionError("remote target was accepted")
