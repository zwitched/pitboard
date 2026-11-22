#!/usr/bin/env python3
"""Extract telemetry descriptors from the owner's StarCitizen.exe."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pitboard.proto_extract import main

if __name__ == "__main__":
    raise SystemExit(main())
