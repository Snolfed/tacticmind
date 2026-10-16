"""Interfejs w przeglądarce (TypeScript): lokalny serwer HTTP + logika ekranów bez rysowania.

Logika gry, trener i silnik zostają w Pythonie. Ekrany z ``screens/`` to odpowiedniki ekranów
pygame (``ui/screens``) bez kodu rysującego: trzymają stan, reagują na akcje z przeglądarki
i co klatkę oddają „migawkę” stanu (JSON), którą interfejs w TypeScript rysuje wektorowo.
"""
