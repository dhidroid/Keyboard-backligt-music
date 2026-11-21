#!/usr/bin/env python3
"""
kblight - sync your laptop keyboard backlight to music (macOS + Windows)

INSTALL
    pip install numpy soundcard requests
    macOS only:      pip install pyobjc-core pyobjc-framework-Cocoa
    OpenRGB driver:  pip install openrgb-python

RUN
    python kblight.py --list                 # show audio devices
    python kblight.py                        # auto-detect everything
    python kblight.py --driver console       # no hardware, just a terminal bar (test)
    python kblight.py --device "BlackHole"   # pick the audio input by name

AUDIO SOURCE
    Windows : captures whatever is playing on your default speakers (WASAPI loopback).
    macOS   : macOS cannot capture system audio natively. Install the free BlackHole
              (2ch) driver, create a "Multi-Output Device" (speakers + BlackHole) in
              Audio MIDI Setup, play music through it and run with --device BlackHole.
              Without it the script falls back to the microphone (works, but noisier).

BACKLIGHT DRIVERS
    mac      MacBook keyboard backlight (brightness only - Apple keyboards are white).
             Uses Apple's private CoreBrightness API, so it can break on new macOS.
    razer    Razer Blade laptops via the Razer Synapse / Chroma REST API (full RGB).
    openrgb  Any keyboard OpenRGB can see (start OpenRGB and enable its SDK Server).
    console  Fake driver that prints a bar. Use it to test the audio side.

Stop with Ctrl+C - the original keyboard brightness is restored.
"""

from __future__ import annotations

import argparse
import colorsys
import platform
import sys
import time

import numpy as np

SYSTEM = platform.system()  # "Darwin" or "Windows"
SAMPLE_RATE = 44100
# CoreAudio accepts blocks from 15 to 512 frames for this recorder.
BLOCK = 512  # ~12 ms of audio per update


# ------------------------------------------------------------------ drivers
class Driver:
    name = "base"
    min_interval = 0.0  # seconds between updates

    def set(self, level: float, hue: float) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ConsoleDriver(Driver):
    name = "console"

    def set(self, level, hue):
        bar = "#" * int(level * 50)
        sys.stdout.write(f"\r[{bar:<50}] {level:4.2f}")
        sys.stdout.flush()

    def close(self):
        print()


class MacDriver(Driver):
    """MacBook keyboard backlight via private CoreBrightness.KeyboardBrightnessClient."""

    name = "mac"

    def __init__(self):
        import objc

        objc.loadBundle(
            "CoreBrightness",
            globals(),
            bundle_path="/System/Library/PrivateFrameworks/CoreBrightness.framework",
        )
        self.client = objc.lookUpClass("KeyboardBrightnessClient").alloc().init()

        self.kid = 1
        try:
            ids = list(self.client.copyKeyboardBacklightIDs() or [])
            if ids:
                self.kid = int(ids[0])
        except Exception:
            pass

        try:
            self.original = float(self.client.brightnessForKeyboard_(self.kid))
        except Exception:
            self.original = 0.5

        # Stop macOS auto-brightness from fighting us (restored on exit).
        self.was_auto = None
        try:
            self.was_auto = bool(self.client.isAutoBrightnessEnabledForKeyboard_(self.kid))
            if self.was_auto:
                self.client.enableAutoBrightness_forKeyboard_(False, self.kid)
        except Exception:
            self.was_auto = None

    def set(self, level, hue):
        self.client.setBrightness_forKeyboard_(float(level), self.kid)

    def close(self):
        try:
            self.client.setBrightness_forKeyboard_(self.original, self.kid)
            if self.was_auto:
                self.client.enableAutoBrightness_forKeyboard_(True, self.kid)
        except Exception:
            pass


class RazerDriver(Driver):
    """Razer Chroma REST API (Windows, Razer Synapse installed)."""

    name = "razer"
    min_interval = 0.04
    BASE = "http://localhost:54235/razer/chromasdk"

    def __init__(self):
        import requests

        self.http = requests.Session()
        resp = self.http.post(
            self.BASE,
            json={
                "title": "kblight",
                "description": "Music synced keyboard backlight",
                "author": {"name": "kblight", "contact": "https://localhost"},
                "device_supported": ["keyboard"],
                "category": "application",
            },
            timeout=3,
        )
        resp.raise_for_status()
        self.uri = resp.json()["uri"]
        self.last_beat = time.time()

    def set(self, level, hue):
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, level))
        color = r | (g << 8) | (b << 16)  # Chroma uses BGR packed ints
        self.http.put(
            f"{self.uri}/keyboard",
            json={"effect": "CHROMA_STATIC", "param": {"color": color}},
            timeout=1,
        )
        if time.time() - self.last_beat > 8:
            self.http.put(f"{self.uri}/heartbeat", timeout=1)
            self.last_beat = time.time()

    def close(self):
        try:
            self.http.delete(self.uri, timeout=2)  # hands lighting back to Synapse
        except Exception:
            pass


class OpenRGBDriver(Driver):
    """Any keyboard supported by OpenRGB (SDK server must be running)."""

    name = "openrgb"
    min_interval = 0.03

    def __init__(self):
        from openrgb import OpenRGBClient
        from openrgb.utils import DeviceType, RGBColor

        self.RGBColor = RGBColor
        self.cli = OpenRGBClient(name="kblight")
        self.devs = self.cli.get_devices_by_type(DeviceType.KEYBOARD)
        if not self.devs:
            raise RuntimeError("OpenRGB is running but sees no keyboard device")

    def set(self, level, hue):
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, level))
        for d in self.devs:
            d.set_color(self.RGBColor(r, g, b))

    def close(self):
        try:
            for d in self.devs:
                d.set_color(self.RGBColor(255, 255, 255))
            self.cli.disconnect()
        except Exception:
            pass


DRIVERS = {
    "mac": MacDriver,
    "razer": RazerDriver,
    "openrgb": OpenRGBDriver,
    "console": ConsoleDriver,
}


def pick_driver(name: str) -> Driver:
    if name != "auto":
        return DRIVERS[name]()

    order = ["mac"] if SYSTEM == "Darwin" else ["razer", "openrgb"]
    errors = []
    for n in order:
        try:
            return DRIVERS[n]()
        except Exception as e:  # noqa: BLE001
            errors.append(f"  - {n}: {e}")
    print("Could not find a supported keyboard backlight:\n" + "\n".join(errors))
    print("Falling back to the console visualizer (see --driver and the file header).\n")
    return ConsoleDriver()


# -------------------------------------------------------------------- audio
class Analyzer:
    """Turn waveform and spectrum energy into a smooth level and beat pulse."""

    def __init__(self, sr=SAMPLE_RATE, block=BLOCK, bass_weight=0.7, sensitivity=1.0):
        self.window = np.hanning(block)
        freqs = np.fft.rfftfreq(block, 1.0 / sr)
        self.bass = (freqs >= 30) & (freqs < 150)
        self.mid = (freqs >= 150) & (freqs < 2000)
        self.bass_weight = bass_weight
        self.sensitivity = sensitivity
        self.envelope_peak = 1e-4
        self.spectrum_peak = 1e-6
        self.level = 0.0
        self.previous_energy = 0.0
        self.flash = 0.0
        self.beat_cooldown = 0
        self.beat_cooldown_frames = max(1, int(0.08 * sr / block))

    def update(self, block: np.ndarray) -> float:
        mono = block.mean(axis=1) if block.ndim == 2 else block
        if len(mono) != len(self.window):
            return self.level

        rms = float(np.sqrt(np.mean(mono**2)))
        if rms < 1e-4:  # silence gate
            target = 0.0
            self.flash *= 0.75
        else:
            spec = np.abs(np.fft.rfft(mono * self.window))
            spectrum_energy = float(
                self.bass_weight * spec[self.bass].mean()
                + (1 - self.bass_weight) * spec[self.mid].mean()
            )

            # Normalize both the waveform envelope and spectrum independently so
            # microphone volume changes do not make the keyboard look static.
            self.envelope_peak = max(rms, self.envelope_peak * 0.995)
            self.spectrum_peak = max(spectrum_energy, self.spectrum_peak * 0.995)
            waveform_level = min(1.0, rms / self.envelope_peak)
            spectrum_level = min(1.0, spectrum_energy / self.spectrum_peak)
            energy = 0.65 * waveform_level + 0.35 * spectrum_level
            target = min(1.0, energy * self.sensitivity)

            rise = energy - self.previous_energy
            if self.beat_cooldown:
                self.beat_cooldown -= 1
            elif energy > 0.55 and rise > 0.12:
                self.flash = 1.0
                self.beat_cooldown = self.beat_cooldown_frames
            else:
                self.flash *= 0.75
            self.previous_energy = energy

        # Fast attack and slower release keep the waveform visible without flicker.
        rate = 0.85 if target > self.level else 0.2
        self.level += (target - self.level) * rate
        return self.level


def open_audio(device: str | None):
    import soundcard as sc

    include_loopback = SYSTEM == "Windows"
    if device:
        microphones = sc.all_microphones(include_loopback=include_loopback)
        matches = [m for m in microphones if device.casefold() in m.name.casefold()]
        if not matches:
            available = ", ".join(m.name for m in microphones) or "none"
            raise RuntimeError(
                f"Audio device {device!r} was not found. Available devices: {available}. "
                "Install BlackHole 2ch and configure it in Audio MIDI Setup for macOS "
                "system-audio capture."
            )
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise RuntimeError(
                f"Audio device {device!r} is ambiguous; use a more specific name: {names}"
            )
        mic = matches[0]
    elif SYSTEM == "Windows":
        mic = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
    else:
        mic = sc.default_microphone()
    print(f"Audio input: {mic.name}")
    return mic.recorder(samplerate=SAMPLE_RATE, blocksize=BLOCK)


def list_devices():
    import soundcard as sc

    print("Audio inputs (use --device with part of the name):")
    for m in sc.all_microphones(include_loopback=SYSTEM == "Windows"):
        tag = " [loopback]" if getattr(m, "isloopback", False) else ""
        print(f"  - {m.name}{tag}")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Sync keyboard backlight to music")
    ap.add_argument("--list", action="store_true", help="list audio devices and exit")
    ap.add_argument("--device", help="audio input name (substring)")
    ap.add_argument("--driver", default="auto", choices=["auto", *DRIVERS])
    ap.add_argument(
        "--sensitivity", type=float, default=1.0, help="higher = brighter (default 1.0)"
    )
    ap.add_argument("--bass", type=float, default=0.7, help="bass weight 0..1 (default 0.7)")
    ap.add_argument(
        "--gamma", type=float, default=1.3, help="contrast; higher = punchier (default 1.3)"
    )
    ap.add_argument(
        "--floor", type=float, default=0.05, help="minimum brightness 0..1 (default 0.05)"
    )
    ap.add_argument(
        "--flash",
        type=float,
        default=0.9,
        help="beat flash strength 0..1 (default 0.9; use 0 to disable)",
    )
    ap.add_argument("--hue", type=float, default=0.6, help="start colour 0..1 (RGB drivers)")
    ap.add_argument(
        "--hue-speed", type=float, default=0.03, help="colour cycling per second (0 = fixed)"
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="print live audio RMS and brightness for troubleshooting",
    )
    args = ap.parse_args()

    if args.list:
        list_devices()
        return

    driver = pick_driver(args.driver)
    print(f"Backlight driver: {driver.name}   (Ctrl+C to stop)")
    analyzer = Analyzer(bass_weight=args.bass, sensitivity=args.sensitivity)
    hue, last_sent, last_level, last_t = args.hue, 0.0, -1.0, time.time()
    silent_frames = 0
    last_debug = 0.0

    try:
        with open_audio(args.device) as rec:
            while True:
                block = rec.record(numframes=BLOCK)
                level = analyzer.update(block)
                brightness = max(
                    args.floor,
                    min(1.0, level**args.gamma + analyzer.flash * args.flash),
                )

                mono = block.mean(axis=1) if block.ndim == 2 else block
                rms = float(np.sqrt(np.mean(mono**2)))
                if rms < 1e-4:
                    silent_frames += 1
                else:
                    silent_frames = 0

                if silent_frames == int(3.0 * SAMPLE_RATE / BLOCK):
                    if args.device:
                        print(
                            "\nNo audio is reaching the selected input. "
                            "Route music through a Multi-Output Device containing BlackHole "
                            "or choose a different --device.",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "\nNo audio is reaching the default microphone. "
                            "Check microphone permissions and input level.",
                            file=sys.stderr,
                        )

                now = time.time()
                if args.debug and now - last_debug >= 0.25:
                    sys.stderr.write(
                        f"\rRMS {rms:.4f}  level {level:.2f}  brightness {brightness:.2f}"
                    )
                    sys.stderr.flush()
                    last_debug = now

                hue = (hue + args.hue_speed * (now - last_t)) % 1.0
                last_t = now

                if now - last_sent >= driver.min_interval and abs(brightness - last_level) > 0.01:
                    driver.set(brightness, hue)
                    last_sent, last_level = now, brightness
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
