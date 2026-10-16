// Napisy, których potrzebuje tylko interfejs w przeglądarce (ustawienia, łączenie z serwerem).
// Reszta tekstów pochodzi z tych samych słowników co w Pythonie (tacticmind/i18n).

export const UI_STRINGS: Record<string, Record<string, string>> = {
  pl: {
    "ui.settings": "Ustawienia",
    "ui.fps_counter": "Licznik FPS",
    "ui.fps_counter_hint": "F3 włącza i wyłącza licznik",
    "ui.fps_limit": "Limit klatek",
    "ui.fps_unlimited": "Bez limitu",
    "ui.fps_unlimited_hint": "Bez limitu = częstotliwość odświeżania ekranu",
    "ui.fullscreen": "Pełny ekran (F11)",
    "ui.language": "Język",
    "ui.volume": "Głośność",
    "ui.connecting": "Łączę z TacticMind…",
    "ui.connecting_detail": "Jeśli to trwa długo, uruchom grę ponownie poleceniem python main.py.",
    "ui.close": "Zamknij",
    "ui.prev": "Poprzedni ruch (←)",
    "ui.next": "Następny ruch (→)",
    "ui.back_to_game": "Wróć do partii",
  },
  en: {
    "ui.settings": "Settings",
    "ui.fps_counter": "FPS counter",
    "ui.fps_counter_hint": "F3 toggles the counter",
    "ui.fps_limit": "Frame limit",
    "ui.fps_unlimited": "Unlimited",
    "ui.fps_unlimited_hint": "Unlimited = your display's refresh rate",
    "ui.fullscreen": "Full screen (F11)",
    "ui.language": "Language",
    "ui.volume": "Volume",
    "ui.connecting": "Connecting to TacticMind…",
    "ui.connecting_detail": "If this takes long, restart the game with python main.py.",
    "ui.close": "Close",
    "ui.prev": "Previous move (←)",
    "ui.next": "Next move (→)",
    "ui.back_to_game": "Back to the game",
  },
};
