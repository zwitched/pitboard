#!/usr/bin/env python3
"""Run the practice telemetry server on 127.0.0.1.

Pitboard --mock starts this itself. Use the script when you want the fake
game on a fixed port.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pitboard.mock_server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Practice Star Citizen telemetry server (loopback only).")
    parser.add_argument("--port", type=int, default=29421)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("Port out of range.", file=sys.stderr)
        return 2
    try:
        asyncio.run(serve(args.port))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
