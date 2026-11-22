"""Who is allowed to see the token, change settings, and send hazardous commands."""

from __future__ import annotations

_LOOPBACK_PEERS = {"127.0.0.1", "::1", "localhost"}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
# Starlette's TestClient uses these names. They are not routable, and production
# refuses them unless the app was created with testing=True.
_TEST_PEER = "testclient"
_TEST_HOST = "testserver"


def hostname_of(host_header: str) -> str:
    value = (host_header or "").strip().lower()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 1 else ""
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def is_loopback_peer(host: str | None, *, testing: bool = False) -> bool:
    name = (host or "").lower()
    if name in _LOOPBACK_PEERS:
        return True
    return testing and name == _TEST_PEER


def host_header_allowed(host_header: str, *, lan_active: bool, testing: bool = False) -> bool:
    name = hostname_of(host_header)
    if name in _LOOPBACK_HOSTS:
        return True
    if testing and name == _TEST_HOST:
        return True
    if lan_active and name and name not in {"0.0.0.0", "testserver"}:
        return True
    return False


def origin_matches_host(origin: str | None, host_header: str) -> bool:
    """Browser calls must come from the same host that served the page.

    A missing Origin is a non-browser client that already has the token.
    """
    if not origin:
        return True
    text = origin.strip().lower()
    if "://" not in text:
        return False
    netloc = text.split("://", 1)[1].split("/", 1)[0]
    return netloc == (host_header or "").strip().lower()
