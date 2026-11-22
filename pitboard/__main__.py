"""Run the Pitboard dashboard."""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

import uvicorn

from pitboard import __version__
from pitboard.api import create_app, install_log_filters
from pitboard.paths import app_home
from pitboard.settings import SettingsError, load_settings, parse_loopback_target, parse_port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pitboard",
        description="Local Star Citizen telemetry board for LighterBurrito.",
    )
    parser.add_argument("--mock", action="store_true", help="Simulate telemetry on this PC. Does not connect to the game.")
    parser.add_argument("--lan", action="store_true", help="Listen on all interfaces. Unencrypted. Off by default.")
    parser.add_argument("--local", action="store_true", help="Listen on 127.0.0.1 only and save that choice.")
    parser.add_argument("--port", type=int, default=None, help="Dashboard port (default 9477).")
    parser.add_argument("--grpc", default=None, help="Loopback game target, default 127.0.0.1:2942.")
    parser.add_argument("--schema", default=None, help="Path to an extracted telemetry.desc.")
    parser.add_argument("--home", default=None, help="Folder for settings and session logs.")
    parser.add_argument("--record", action="store_true", help="Append a JSONL session log under the home folder.")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser.")
    parser.add_argument("--version", action="store_true", help="Print the version and exit.")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.lan and args.local:
        parser.error("Choose either --lan or --local.")
    if args.mock and args.grpc:
        parser.error("--mock does not connect to a game target.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    install_log_filters()
    logging.getLogger("grpc").setLevel(logging.ERROR)

    home = app_home() if args.home is None else __import__("pathlib").Path(args.home).expanduser().resolve()
    try:
        settings = load_settings(home)
        if args.lan:
            settings.lan_enabled = True
        if args.local:
            settings.lan_enabled = False
        if args.port is not None:
            settings.port = parse_port(args.port)
        if args.grpc is not None:
            settings.grpc_target = parse_loopback_target(args.grpc)
        if args.record:
            settings.record = True
        settings.save()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2

    schema_path = None
    if args.schema:
        schema_path = __import__("pathlib").Path(args.schema).expanduser()
    app = create_app(
        home=home,
        mock=args.mock,
        schema_path=schema_path,
        discover_schema=schema_path is None,
        bind_host=settings.bind_host(),
        port=settings.port,
        grpc_target=None if args.grpc is None else settings.grpc_target,
    )
    url = f"http://127.0.0.1:{settings.port}/"
    print(f"Pitboard {__version__}  {url}")
    print(f"Pilot     {settings.pilot}")
    if args.mock:
        print("Mode      practice range (synthetic telemetry, not the game)")
    else:
        print(f"Game      {settings.grpc_target}")
    if settings.lan_enabled:
        print("LAN       ON  — unencrypted. Anyone with the link can open the board.")
        print("          Hazardous commands still only work from this PC.")
    else:
        print("LAN       off — this computer only")
    print("Token     stored in settings.json (not printed here)")
    print(f"Hazardous {'ON' if settings.allow_dangerous_actions else 'off'}")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=settings.bind_host(), port=settings.port, log_level="info", access_log=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
