"""Dźwięki gry syntezowane w kodzie (bez plików z nagraniami, więc bez problemów z licencją).

Brzmienie wzorowane na chess.com:
 - ruch — krótkie, drewniane „puknięcie” figury o szachownicę,
 - bicie — podwójne, ostrzejsze „klaśnięcie” (figura uderza w figurę),
 - szach — puknięcie z jasnym dzwoneczkiem,
 - roszada — dwa szybkie puknięcia (król i wieża),
 - promocja — puknięcie z rosnącym tonem,
 - rozwiązane zadanie / genialny ruch — dzwonkowe arpeggio,
 - błąd — miękkie, opadające „bonk”.

Drewniane puknięcie to suma kilku szybko gasnących drgań własnych (jak deska) i krótkiego
szumu uderzenia. Dzwonek to tony harmoniczne o proporcjach dzwonu (1 : 2 : 2,76 : 5,4).
Próbki są generowane w formacie, w jakim system faktycznie otworzył dźwięk (mono albo stereo).
"""

from __future__ import annotations

import math
import random
import threading
from array import array

import pygame

PREFERRED_RATE = 44100
#: Mały bufor = dźwięk ruchu słychać od razu po puszczeniu figury.
BUFFER = 512


def pre_init() -> None:
    """Wywoływane przed ``pygame.init()``: format i mały bufor (niskie opóźnienie)."""
    pygame.mixer.pre_init(PREFERRED_RATE, -16, 2, BUFFER)


class _Synth:
    def __init__(self, rate: int) -> None:
        self.rate = rate
        self._rng = random.Random(1234)

    def buffer(self, seconds: float) -> list[float]:
        return [0.0] * int(self.rate * seconds)

    def knock(self, out: list[float], start: float, gain: float = 1.0, brightness: float = 1.0) -> None:
        """Drewniane puknięcie: drgania własne deski + krótki, przefiltrowany szum uderzenia."""
        rate = self.rate
        modes = ((170.0, 34.0, 0.55), (520.0, 55.0, 1.0), (1180.0 * brightness, 90.0, 0.6), (2450.0 * brightness, 150.0, 0.3))
        begin = int(start * rate)
        length = min(len(out) - begin, int(0.14 * rate))
        lowpass = 0.0
        alpha = min(0.95, 0.35 * brightness)
        for i in range(length):
            t = i / rate
            drop = 1 + 0.05 * math.exp(-t * 70)  # lekkie opadanie wysokości tuż po uderzeniu
            value = 0.0
            for freq, decay, amp in modes:
                value += amp * math.exp(-t * decay) * math.sin(2 * math.pi * freq * drop * t)
            noise = self._rng.uniform(-1.0, 1.0)
            lowpass += alpha * (noise - lowpass)
            value += 1.1 * lowpass * math.exp(-t * 260)
            attack = min(1.0, i / (0.0012 * rate))
            out[begin + i] += gain * attack * value

    def bell(self, out: list[float], start: float, freq: float, gain: float = 1.0, decay: float = 5.0, length: float = 0.6) -> None:
        """Dzwonek: tony o proporcjach dzwonu, wyższe gasną szybciej."""
        rate = self.rate
        partials = ((1.0, 1.0, 1.0), (2.0, 0.45, 1.6), (2.76, 0.3, 2.2), (5.4, 0.12, 3.5))
        begin = int(start * rate)
        count = min(len(out) - begin, int(length * rate))
        for i in range(count):
            t = i / rate
            value = 0.0
            for ratio, amp, speed in partials:
                value += amp * math.exp(-t * decay * speed) * math.sin(2 * math.pi * freq * ratio * t)
            attack = min(1.0, i / (0.003 * rate))
            out[begin + i] += gain * attack * value

    def tone(self, out: list[float], start: float, f0: float, f1: float, length: float, gain: float, decay: float) -> None:
        """Miękki ton z przesuwaną wysokością (do dźwięku błędu i promocji)."""
        rate = self.rate
        begin = int(start * rate)
        count = min(len(out) - begin, int(length * rate))
        phase = 0.0
        for i in range(count):
            t = i / rate
            freq = f0 + (f1 - f0) * (i / max(1, count - 1))
            phase += 2 * math.pi * freq / rate
            env = math.exp(-t * decay) * min(1.0, i / (0.006 * rate))
            out[begin + i] += gain * env * (math.sin(phase) + 0.25 * math.sin(2 * phase))


def _pcm(samples: list[float], channels: int, peak: float) -> array:
    """Normalizacja do zadanego poziomu, łagodne wyciszenie końcówki i zamiana na 16-bitowe PCM."""
    top = max((abs(x) for x in samples), default=1.0) or 1.0
    scale = peak / top
    fade = min(len(samples), 220)
    data = array("h")
    for i, x in enumerate(samples):
        if i >= len(samples) - fade:
            x *= (len(samples) - i) / fade
        value = int(max(-1.0, min(1.0, x * scale)) * 32767)
        for _ in range(channels):
            data.append(value)
    return data


def build_sounds(rate: int) -> dict[str, list[float]]:
    """Wszystkie dźwięki jako próbki (float) — osobno od pygame, żeby dało się je testować."""
    s = _Synth(rate)
    move = s.buffer(0.16)
    s.knock(move, 0.0, 1.0, 1.0)
    capture = s.buffer(0.2)
    s.knock(capture, 0.0, 1.0, 1.45)
    s.knock(capture, 0.028, 0.75, 1.2)
    check = s.buffer(0.45)
    s.knock(check, 0.0, 1.0, 1.1)
    s.bell(check, 0.012, 1245.0, 0.45, decay=7.0, length=0.42)
    castle = s.buffer(0.26)
    s.knock(castle, 0.0, 0.95, 1.0)
    s.knock(castle, 0.085, 0.85, 0.9)
    promote = s.buffer(0.4)
    s.knock(promote, 0.0, 1.0, 1.0)
    s.tone(promote, 0.03, 660.0, 1320.0, 0.3, 0.35, 8.0)
    success = s.buffer(1.1)
    for i, freq in enumerate((784.0, 988.0, 1175.0, 1568.0)):
        s.bell(success, 0.075 * i, freq, 0.6 if i < 3 else 0.8, decay=4.2, length=1.1 - 0.075 * i)
    brilliant = s.buffer(1.2)
    for i, freq in enumerate((1047.0, 1319.0, 1568.0, 2093.0)):
        s.bell(brilliant, 0.055 * i, freq, 0.6, decay=4.0, length=1.2 - 0.055 * i)
    s.bell(brilliant, 0.24, 3136.0, 0.3, decay=3.0, length=0.9)
    error = s.buffer(0.42)
    s.tone(error, 0.0, 330.0, 300.0, 0.2, 0.8, 11.0)
    s.tone(error, 0.12, 247.0, 220.0, 0.3, 0.8, 8.0)
    return {
        "move": move,
        "capture": capture,
        "check": check,
        "castle": castle,
        "promote": promote,
        "success": success,
        "brilliant": brilliant,
        "error": error,
    }


#: Głośność poszczególnych dźwięków (szczyt próbek, 0..1).
_LEVELS = {"move": 0.55, "capture": 0.7, "check": 0.6, "castle": 0.55, "promote": 0.6, "success": 0.55, "brilliant": 0.6, "error": 0.45}


class Sounds:
    def __init__(self, enabled: bool = True, background: bool = False) -> None:
        """``background=True``: dźwięki syntezują się w osobnym wątku (ok. 0,6 s), a okno startuje od razu."""
        self.enabled = enabled
        self.available = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(PREFERRED_RATE, -16, 2, BUFFER)
            init = pygame.mixer.get_init()
            if init is None:
                raise pygame.error("brak dźwięku")
            rate, size, channels = init
            if size != -16:
                raise pygame.error("nieobsługiwany format próbek")
        except (pygame.error, NotImplementedError):
            return
        if background:
            threading.Thread(target=self._build, args=(rate, channels), daemon=True, name="TaktykAI-dźwięki").start()
        else:
            self._build(rate, channels)

    def _build(self, rate: int, channels: int) -> None:
        try:
            sounds = {name: pygame.mixer.Sound(buffer=_pcm(samples, channels, _LEVELS[name])) for name, samples in build_sounds(rate).items()}
        except (pygame.error, NotImplementedError):
            return
        self._sounds = sounds
        self.available = True

    def play(self, name: str) -> None:
        if self.enabled and self.available and name in self._sounds:
            self._sounds[name].play()
