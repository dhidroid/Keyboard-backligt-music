# kblight

Sync a laptop keyboard backlight to the waveform and energy of live audio. The project
supports macOS, Windows, OpenRGB, Razer Chroma, and a console visualizer for
testing without hardware.

## Requirements

- Python 3.10 or newer
- macOS or Windows
- An audio input visible to SoundCard

On macOS, grant microphone access to the terminal or Python application in
**System Settings > Privacy & Security > Microphone**.

## Install

```console
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `macos` extra installs the Objective-C bridge used by the Mac keyboard
driver. The `openrgb` extra installs the OpenRGB client.

## Run

```console
python kblight.py --list
python kblight.py
python kblight.py --driver console
python kblight.py --device "BlackHole"
python kblight.py --flash 1.0
```

Use `python3` instead of `python` if your system does not provide a `python`
command.

The visualizer follows the audio waveform envelope and adds a short bright
flash when it detects a strong beat or transient. Use `--flash 0` to disable
flashes, or increase it up to `1.0` for stronger flashes. The default gamma is
now `1.3` so normal music produces visible brightness changes.

### macOS audio

macOS does not expose system audio as a normal microphone. Install
[BlackHole 2ch](https://existential.audio/blackhole/) (or run
`brew install --cask blackhole-2ch`), then:

1. Open **Audio MIDI Setup** and create a Multi-Output Device containing your
   speakers and **BlackHole 2ch**.
2. Select that Multi-Output Device as your music app's output.
3. Confirm `BlackHole 2ch` appears in `python3 kblight.py --list`.
4. Run `python3 kblight.py --device BlackHole --flash 1.0`.

If the brightness stays at `0.05` and the app reports no audio, music is not
being sent to BlackHole. Start it with `--debug` to monitor live RMS and
brightness:

```console
python3 kblight.py --device BlackHole --flash 1.0 --debug
```

The device argument is matched case-insensitively by substring, so `BlackHole`
selects `BlackHole 2ch`. If it is not listed, install/restart BlackHole before
running the command. If no `--device` is provided, kblight uses the default
microphone. Use `--device BlackHole` explicitly for routed system audio.

### Drivers

- `mac`: MacBook keyboard brightness through Apple's private CoreBrightness API
- `razer`: Razer Chroma REST API (requires Razer Synapse)
- `openrgb`: any keyboard supported by OpenRGB's SDK server
- `console`: terminal bar for testing audio and configuration

The default `auto` driver selects `mac` on macOS and tries Razer/OpenRGB on
Windows before falling back to `console`.

## Development

Run the focused tests and quality checks:

```console
python -m pytest
python -m ruff check .
python -m black --check .
```

Enable the local Git hooks once:

```console
pre-commit install
pre-commit run --all-files
```

GitHub Actions runs the same checks for every push and pull request. The
project uses the MIT license; see [LICENSE](LICENSE).
