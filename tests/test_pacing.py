"""Tempo klatek: limiter FPS, licznik FPS i zapis ustawień w profilu."""

import time

from tacticmind.rating.profile import DEFAULT_FPS_LIMIT, PlayerProfile
from tacticmind.ui.pacing import FpsCounter, FramePacer


def test_frame_pacer_keeps_even_period() -> None:
    pacer = FramePacer()
    pacer.wait(100)  # pierwsza klatka startuje od razu
    start = time.perf_counter()
    pacer.wait(100)
    pacer.wait(100)
    assert time.perf_counter() - start >= 0.0199  # dwie klatki po 10 ms — nigdy krócej


def test_fps_counter_average() -> None:
    counter = FpsCounter()
    for i in range(240):
        start = 100 + i / 120
        counter.record(start, start + 0.004)
    assert abs(counter.fps - 120) < 1
    assert abs(counter.frame_ms - 4.0) < 0.01


def test_profile_fps_settings_round_trip() -> None:
    profile = PlayerProfile(show_fps=True, fps_limit=144)
    loaded = PlayerProfile.from_json(profile.to_json())
    assert loaded.show_fps and loaded.fps_limit == 144
    broken = PlayerProfile.from_json({"show_fps": "yes", "fps_limit": 999})
    assert not broken.show_fps and broken.fps_limit == DEFAULT_FPS_LIMIT
    assert PlayerProfile.from_json({}).fps_limit == DEFAULT_FPS_LIMIT
