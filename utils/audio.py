"""Cross-platform ringtone helper."""

from __future__ import annotations

import math
import struct
import sys
from typing import Final

_DURATION_DEFAULT: Final[float] = 2.0          # seconds
_FREQ_DEFAULT: Final[float] = 880.0            # Hz (A5)


def play_ringtone(duration: float = _DURATION_DEFAULT,
                  freq: float = _FREQ_DEFAULT) -> None:
    """
    Play a sine-wave ringtone of *duration* seconds.

    Priority of playback back-ends:

    1. ``simpleaudio`` – portable, high-quality.
    2. ``winsound.Beep`` – Windows fallback.
    3. Silently no-op if both fail.

    Execution blocks until playback finishes so tones never overlap.
    """
    # —— primary backend: simpleaudio ————————————————————————
    try:
        import simpleaudio as sa  # type: ignore
        sample_rate: int = 44_100
        num_samples: int = int(sample_rate * duration)
        amplitude: float = 0.3

        # Generate mono 16-bit PCM data
        buf = bytearray()
        for n in range(num_samples):
            sample = amplitude * math.sin(2.0 * math.pi * freq * n / sample_rate)
            buf += struct.pack("<h", int(sample * 32_767))

        # Duplicate for stereo playback
        stereo = bytearray()
        for i in range(0, len(buf), 2):
            stereo += buf[i:i + 2] * 2

        play_obj = sa.play_buffer(bytes(stereo), 2, 2, sample_rate)
        play_obj.wait_done()
        return
    except Exception:
        pass  # fall through to secondary backend

    # —— fallback: winsound (Windows only) ————————————————
    if sys.platform.startswith("win"):
        try:
            import winsound  # type: ignore
            winsound.Beep(int(freq), int(duration * 1_000))
        except Exception:
            pass  # final silent fallback