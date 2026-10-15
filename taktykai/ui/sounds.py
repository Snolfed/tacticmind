"""Dźwięki generowane w kodzie (synteza prostych fal), bez plików z licencją.

ruch, bicie, szach, sukces, błąd. Jeśli komputer nie ma karty dźwiękowej,
gra działa dalej bez dźwięku.
"""

from __future__ import annotations

import math
import random
from array import array

import pygame

RATE = 44100


def _tone(parts: list[tuple[float, float, float]], volume: float = 0.5, noise: float = 0.0, decay: float = 18.0) -> array:
    """Sklejka tonów (częstotliwość_start, częstotliwość_koniec, czas_s) z wykładniczym wygasaniem."""
    samples = array("h")
    rng = random.Random(7)
    for f0, f1, duration in parts:
        n = int(RATE * duration)
        phase = 0.0
        for i in range(n):
            t = i / RATE
            freq = f0 + (f1 - f0) * (i / max(1, n - 1))
            phase += 2 * math.pi * freq / RATE
            envelope = math.exp(-t * decay) * min(1.0, i / 60)
            value = math.sin(phase) * 0.8 + math.sin(phase * 2) * 0.2
            if noise:
                value = value * (1 - noise) + (rng.random() * 2 - 1) * noise * math.exp(-t * 60)
            samples.append(int(max(-1.0, min(1.0, value * envelope * volume)) * 32767))
    return samples


class Sounds:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.available = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=RATE, size=-16, channels=1)
            init = pygame.mixer.get_init()
            if init is None or init[0] != RATE or init[2] != 1:
                raise pygame.error("nieobsługiwany format dźwięku")
            self._sounds = {
                "move": pygame.mixer.Sound(buffer=_tone([(190, 150, 0.09)], 0.55, noise=0.35, decay=40)),
                "capture": pygame.mixer.Sound(buffer=_tone([(320, 180, 0.12)], 0.7, noise=0.55, decay=30)),
                "check": pygame.mixer.Sound(buffer=_tone([(660, 660, 0.08), (880, 880, 0.12)], 0.35, decay=10)),
                "success": pygame.mixer.Sound(
                    buffer=_tone([(523, 523, 0.09), (659, 659, 0.09), (784, 784, 0.09), (1047, 1047, 0.25)], 0.35, decay=6)
                ),
                "brilliant": pygame.mixer.Sound(
                    buffer=_tone([(784, 784, 0.07), (988, 988, 0.07), (1175, 1175, 0.07), (1568, 1568, 0.32)], 0.38, decay=5)
                ),
                "error": pygame.mixer.Sound(buffer=_tone([(180, 110, 0.3)], 0.45, decay=5)),
            }
            self.available = True
        except (pygame.error, NotImplementedError):
            self.available = False

    def play(self, name: str) -> None:
        if self.enabled and self.available and name in self._sounds:
            self._sounds[name].play()
