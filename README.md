# Pitboard

Local telemetry board for Star Citizen, built for LighterBurrito. It talks only to the game's own gRPC server on this PC (`127.0.0.1:2942`) and shows a dashboard you control. No memory reading, no launcher mods, no account calls.

This is an original clean-room app. The game schema is extracted on your machine from your copy of `StarCitizen.exe` and is not part of this repo. The practice server uses a synthetic descriptor so the board can run with the game closed. That synthetic file is not the game's schema.

Unofficial. Not affiliated with Cloud Imperium Games.

## What you get

- Character vitals and ship state, updated from `TelemetryStream` (about 17 frames per second when the game is streaming).
- Command buttons from `ListTriggerableActions` / `TriggerGameAction` when that build exposes them (5.0 PTU). 4.10.3 LIVE is display only.
- Hazardous commands (self-destruct, eject, main power off, opening or unlocking doors, ports, and cargo) stay off until you arm them on this PC, and each one still needs a hold to confirm.
- LAN access off by default. Turning it on is unencrypted and uses a random token.
- A practice gRPC server for tests and for using the board without the game.
- A session log you can turn on later, and a small extension seam for something like a Stream Deck.

## Setup (PowerShell)

From the repo folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

If `py` is not on your PATH, use `python` instead. You need Python 3.11 or newer. The requirements include `websockets`. Uvicorn does not install that on its own, and without it the page loads but the live stream never connects.



Check the extractor without the game:

```powershell
python tools\extract_proto.py --self-test
```

Run the tests (dev dependencies):

```powershell
pip install -r requirements-dev.txt
pytest
```

## Enable telemetry in the game

The local server is off until you turn it on. It listens on `127.0.0.1:2942` with no TLS and no authentication. That is the game's design. Leave Pitboard on this computer unless you deliberately turn LAN access on.

### 4.10.3 LIVE — user environment variable

Close the game and the RSI Launcher, including the launcher icon by the clock. Then:

```powershell
setx GRPC_CLIENT_SERVER_ENABLED true
```

You should see `SUCCESS: Specified value was saved.` Start the RSI Launcher after that, then the game. The launcher only passes the variable through if it was started afterwards. Spawn your character. This build streams vitals and ship state. It does not accept `TriggerGameAction`.

Turn it back off, then restart the launcher:

```powershell
[Environment]::SetEnvironmentVariable("GRPC_CLIENT_SERVER_ENABLED", $null, "User")
```

### 5.0 PTU — `user.cfg`

Close the game. Open `user.cfg` in the channel folder you play. A common path is:

```text
C:\Program Files\Roberts Space Industries\StarCitizen\PTU\user.cfg
```

Your install folder may differ. Create the file if it is missing (Notepad, Save as, type All files, name it `user.cfg` so it is not `user.cfg.txt`). Add:

```ini
server.game.telemetry.enabled=1
```

Start the game. In `Game.log` next to that `user.cfg` you should see the service register and a line that the local server is on `127.0.0.1:2942`. The stream starts after your character has spawned (`Initializing game telemetry component of local player`). Commands are available on this build. A frame can omit sections, and proto3 omits zeros, so a missing section is kept from the previous frame and a zero inside a section that did arrive is a real zero.

## Extract the schema

There is no gRPC reflection. The descriptors are embedded in `StarCitizen.exe`. Point the extractor at the channel executable, not the RSI Launcher:

```powershell
python tools\extract_proto.py --exe "C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Bin64\StarCitizen.exe"
```

PTU is the same command with `PTU\Bin64\StarCitizen.exe`. Output goes to `schema\extracted\` (`telemetry.desc`, reconstructed `.proto` files, and `manifest.json`). That folder is gitignored. Pitboard loads the `.desc`. The `.proto` text is for you to read. After a game patch, run the extractor again.

If a field shows up under Unmapped on the ship tab, map it without editing code. Create `data\field_map.json`:

```json
{
  "character.health": "actor.vitals.health",
  "ship.speed": "vehicle.speed_mps"
}
```

Keys are `character.<metric>` or `ship.<metric>`. Values are dotted paths in the merged frame.

## Run

Game running, schema extracted:

```powershell
python -m pitboard
```

Open http://127.0.0.1:9477/ on this PC. The access token is written to `data\settings.json` and is not printed. The page on this PC picks it up by itself.

Practice range, no game:

```powershell
python -m pitboard --mock
```

The banner says the numbers are simulated. `--mock` does not connect to port 2942 and will not send the synthetic schema to the real game.

Useful flags:

```powershell
python -m pitboard --port 9477 --open
python -m pitboard --record
python -m pitboard --local
python tools\mock_telemetry_server.py --port 29421
```

`--record` appends a JSONL session under `data\sessions\`. The token is not in that file. Recording can also be toggled in Settings.

Settings live in `data\settings.json` (mode 600 on Unix). Override the folder with `PITBOARD_HOME`. Override the descriptor path with `PITBOARD_SCHEMA`.

## Safety

- The dashboard binds to `127.0.0.1` unless LAN is on. The game target must be loopback too. Pitboard will not dial a remote telemetry port.
- Browser calls must come from the same host that served the page. The token is compared in constant time and redacted from logs.
- Hazardous commands are refused unless Settings on this PC has them armed, the request is from this PC (not a phone), and the UI has held the button long enough to mint a one-time confirmation. A script still has to arm and then send that confirmation on purpose. Closing doors or locking them is not treated as hazardous. Turning lights, gear, or similar toggles is allowed.
- LAN access is off by default. Settings can save the choice, then you restart. `--lan` turns it on for this process and saves it. The page warns that the link is not encrypted. Anyone with the link can read telemetry and send non-hazardous commands. Hazardous commands still only work from this PC. Regenerate the token in Settings to disconnect other devices. Do this on a network you trust, not on public Wi-Fi. Listening on every interface (`0.0.0.0`) also exposes the app on VPNs and virtual adapters.
- The game port itself has no authentication. Keeping Pitboard on loopback is what stops the rest of the network from driving it.

## Phone or tablet

On this PC, open Settings, turn on LAN access, restart Pitboard, and use the link or QR code shown there. The phone must be on the same network. The connection is plain HTTP. Windows may ask to allow Python on private networks the first time.

## Windows executable (optional)

On Windows, with the venv active and PyInstaller installed (`pip install pyinstaller`):

```powershell
.\tools\build_windows.ps1
```

That produces `dist\pitboard.exe`. It is not signed, so SmartScreen may warn the first time. Settings and logs are written to a `data` folder next to the exe. This build is not produced here. Build it on your own machine.

## Layout

| Path | Role |
| --- | --- |
| `pitboard/` | App: schema loader, gRPC link, normalizer, safety, HTTP, WebSocket |
| `web/` | Dashboard (character, ship, actions) |
| `tools/extract_proto.py` | Scan `StarCitizen.exe` for `sc.game.telemetry` descriptors |
| `tools/mock_telemetry_server.py` | Practice server on loopback |
| `schema/synthetic/` | Original practice schema, not from the game |
| `schema/extracted/` | Your descriptors. Gitignored |
| `pitboard/extensions.py` | Seam for a future Stream Deck client |
| `pitboard/recording.py` | Session JSONL |

A Stream Deck client would implement `TelemetryExtension` (`on_link`, `on_frame`, `on_action`) and register it on the hub. It should use the same action list and the same hazardous-command rules. Nothing in this repo talks to Elgato.

## What was tested without the game

The practice server, the dashboard API, reconnect refusal of the synthetic schema against the real port, hazardous-command gates, host and origin checks, and the extractor (descriptors hidden inside junk bytes, including a second imported file) are covered by `pytest`. A round trip also recompiles the reconstructed `.proto`.

Not verified here, because this environment has no Star Citizen install: pulling descriptors out of a real `StarCitizen.exe`, decoding a live 4.10.3 or 5.0 stream, or the exact field names the game uses. After you extract, unmapped paths on the ship tab are the leftovers. `data\field_map.json` is there for those.
