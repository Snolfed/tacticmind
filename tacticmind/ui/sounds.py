"""Dźwięki gry syntezowane w kodzie (bez plików z nagraniami, więc bez problemów z licencją).

Brzmienie wzorowane na chess.com:
 - ruch — krótkie, niskie, drewniane „puknięcie” figury o szachownicę,
 - bicie — podwójne, ostrzejsze „klaśnięcie” (figura uderza w figurę),
 - szach — puknięcie z jasnym dzwoneczkiem,
 - roszada — dwa szybkie puknięcia (król i wieża),
 - promocja — puknięcie z rosnącym tonem,
 - rozwiązane zadanie / genialny ruch — dzwonkowe arpeggio,
 - błąd — miękkie, opadające „bonk”.

Drewniane puknięcie to suma kilku szybko gasnących, niskich drgań własnych (jak deska) i krótkiego,
stłumionego szumu uderzenia. Dzwonek to czysty ton z dwiema słabymi harmonicznymi. Na końcu każdy dźwięk
przechodzi przez filtr dolnoprzepustowy i dostaje delikatne echo — brzmi miękko, nie „bije po uszach”.
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
        # Niskie, „ciepłe” drgania (bez ostrych wysokich tonów, które męczą ucho).
        modes = ((140.0, 30.0, 0.7), (290.0, 42.0, 1.0), (560.0, 65.0, 0.45), (980.0 * brightness, 95.0, 0.15))
        begin = int(start * rate)
        length = min(len(out) - begin, int(0.15 * rate))
        lowpass = 0.0
        alpha = min(0.5, 0.1 * brightness)
        for i in range(length):
            t = i / rate
            drop = 1 + 0.05 * math.exp(-t * 70)  # lekkie opadanie wysokości tuż po uderzeniu
            value = 0.0
            for freq, decay, amp in modes:
                value += amp * math.exp(-t * decay) * math.sin(2 * math.pi * freq * drop * t)
            noise = self._rng.uniform(-1.0, 1.0)
            lowpass += alpha * (noise - lowpass)
            value += 0.5 * lowpass * math.exp(-t * 320)
            attack = min(1.0, i / (0.0025 * rate))
            out[begin + i] += gain * attack * value

    def bell(self, out: list[float], start: float, freq: float, gain: float = 1.0, decay: float = 5.0, length: float = 0.6) -> None:
        """Dzwonek: tony o proporcjach dzwonu, wyższe gasną szybciej."""
        rate = self.rate
        partials = ((1.0, 1.0, 1.0), (2.0, 0.2, 1.8), (3.0, 0.06, 2.6))  # miękki, „szklany” dzwoneczek
        begin = int(start * rate)
        count = min(len(out) - begin, int(length * rate))
        for i in range(count):
            t = i / rate
            value = 0.0
            for ratio, amp, speed in partials:
                value += amp * math.exp(-t * decay * speed) * math.sin(2 * math.pi * freq * ratio * t)
            attack = min(1.0, i / (0.01 * rate))
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
            out[begin + i] += gain * env * (math.sin(phase) + 0.1 * math.sin(2 * phase))


def _soften(samples: list[float], rate: int, cutoff: float = 2600.0, echo: float = 0.12) -> list[float]:
    """Filtr dolnoprzepustowy (zabiera ostre „cyknięcia”) i delikatne, krótkie echo dla ciepła."""
    alpha = 1 - math.exp(-2 * math.pi * cutoff / rate)
    out: list[float] = []
    state = 0.0
    for x in samples:
        state += alpha * (x - state)
        out.append(state)
    delay = int(0.019 * rate)
    for i in range(len(out) - 1, delay - 1, -1):
        out[i] += echo * out[i - delay]
    return out


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
    move = s.buffer(0.18)
    s.knock(move, 0.0, 1.0, 1.0)
    capture = s.buffer(0.22)
    s.knock(capture, 0.0, 1.0, 1.25)
    s.knock(capture, 0.03, 0.7, 1.1)
    check = s.buffer(0.5)
    s.knock(check, 0.0, 1.0, 1.0)
    s.bell(check, 0.015, 880.0, 0.32, decay=6.0, length=0.48)
    castle = s.buffer(0.28)
    s.knock(castle, 0.0, 0.95, 1.0)
    s.knock(castle, 0.09, 0.8, 0.9)
    promote = s.buffer(0.42)
    s.knock(promote, 0.0, 1.0, 1.0)
    s.tone(promote, 0.03, 523.0, 784.0, 0.32, 0.25, 7.0)
    success = s.buffer(1.2)
    for i, freq in enumerate((523.25, 659.25, 783.99, 1046.5)):
        s.bell(success, 0.085 * i, freq, 0.5 if i < 3 else 0.6, decay=3.5, length=1.2 - 0.085 * i)
    brilliant = s.buffer(1.3)
    for i, freq in enumerate((659.25, 783.99, 987.77, 1318.5)):
        s.bell(brilliant, 0.065 * i, freq, 0.5, decay=3.2, length=1.3 - 0.065 * i)
    s.bell(brilliant, 0.27, 1975.5, 0.12, decay=2.5, length=1.0)
    error = s.buffer(0.45)
    s.tone(error, 0.0, 294.0, 277.0, 0.18, 0.7, 12.0)
    s.tone(error, 0.13, 220.0, 208.0, 0.3, 0.7, 9.0)
    sounds = {
        "move": move,
        "capture": capture,
        "check": check,
        "castle": castle,
        "promote": promote,
        "success": success,
        "brilliant": brilliant,
        "error": error,
    }
    return {name: _soften(samples, rate) for name, samples in sounds.items()}


#: Głośność poszczególnych dźwięków (szczyt próbek, 0..1).
_LEVELS = {"move": 0.45, "capture": 0.52, "check": 0.45, "castle": 0.45, "promote": 0.45, "success": 0.42, "brilliant": 0.45, "error": 0.32}


class Sounds:
    def __init__(self, enabled: bool = True, background: bool = False, volume: float = 0.7) -> None:
        """``background=True``: dźwięki syntezują się w osobnym wątku (ok. 0,6 s), a okno startuje od razu."""
        self.enabled = enabled
        self.volume = volume
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
            threading.Thread(target=self._build, args=(rate, channels), daemon=True, name="TacticMind-dźwięki").start()
        else:
            self._build(rate, channels)

    def _build(self, rate: int, channels: int) -> None:
        try:
            sounds = {name: pygame.mixer.Sound(buffer=_pcm(samples, channels, _LEVELS[name])) for name, samples in build_sounds(rate).items()}
        except (pygame.error, NotImplementedError):
            return
        self._sounds = sounds
        self.set_volume(self.volume)
        self.available = True

    def set_volume(self, volume: float) -> None:
        """Głośność 0..1 (krzywa kwadratowa — suwak zmienia głośność „naturalnie” dla ucha)."""
        self.volume = min(1.0, max(0.0, volume))
        for sound in self._sounds.values():
            sound.set_volume(self.volume**2)

    def play(self, name: str) -> None:
        if self.enabled and self.available and self.volume > 0.02 and name in self._sounds:
            self._sounds[name].play()
