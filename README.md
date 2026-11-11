# BuzzLight

Ambient lighting for USB LED strip kits: the cheap ones with an Artery AT32
controller sold as Lytmi / Beelight (USB ID `2E3C:5740`). The strip glows
with the colors at the edges of your screen, or shows any solid color you
pick. BuzzLight talks to the controller directly; no vendor software needed.

## Features

- **Ambilight** at up to 60 FPS, using DirectX Desktop Duplication with a GDI
  fallback.
- **Ignores black bars.** On an ultrawide, 16:9 video leaves black bars at the
  sides; BuzzLight detects them and samples the edges of the actual picture.
  Letterboxed movies (bars top and bottom) work too, including subtitles
  inside the bars.
- **Natural-looking color:** averaging in linear light, adjustable saturation,
  and frame-rate-independent smoothing that still reacts fast to scene cuts.
- **Solid colors** with presets and smooth fades.
- **LED setup:** set LEDs per side, the start corner and the direction, then
  press **Identify** to light each side in its own color on the real strip.
- **Tray app:** closing the window keeps the lights running. Turn on
  **Start with Windows** to launch minimized at login. Only one copy runs at
  a time.
- **Recovers on its own** after unplugging the strip, display changes, UAC
  prompts and sleep.

## Run from source (Windows)

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw BuzzLight.pyw
```

## Build the exe

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller BuzzLight.spec --noconfirm
```

This produces `dist\BuzzLight\BuzzLight.exe`. Copy the whole `BuzzLight`
folder anywhere and run the exe.

## Notes

- Close any other LED app (e.g. Beelight) first. Only one program can use the
  strip's COM port.
- Settings live in `%APPDATA%\BuzzLight\settings.json`. When BuzzLight runs
  without a console, its log goes to `%APPDATA%\BuzzLight\buzzlight.log`.
- `BUZZLIGHT_PORT=COM5` forces a specific port.
- The controller protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Development

```bat
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest tests
```

| Module | Role |
|---|---|
| `buzzlight/device/` | Packet codec (`protocol.py`), port discovery, and `Strip`, the serial I/O thread |
| `buzzlight/ambilight/` | Screen capture, black-bar detection, sampling and smoothing, plus the engine thread |
| `buzzlight/layout.py` | Where each LED sits around the screen |
| `buzzlight/controller.py` | App state: modes, power and brightness, settings persistence |
| `buzzlight/ui/` | Qt window, LED preview, tray, theme |

## License

MIT. See [LICENSE](LICENSE).
