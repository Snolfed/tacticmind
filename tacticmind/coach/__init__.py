"""Gra z trenerem: nauka otwarć, siła gry zależna od Elo, ocena ruchów i wyjaśnienia trenera.

Moduły bez pygame (testowane jednostkowo):
 - ``openings`` — książka otwarć z objaśnieniem każdego ruchu i rozpoznawaniem nazw debiutów,
 - ``strength`` — jak silnik gra „na zadanym Elo” (głębokość, losowość, przeoczenia),
 - ``review`` — klasyfikacja ruchów jak na chess.com (najlepszy, błąd, przeoczenie…) i celność,
 - ``advice`` — słowne wyjaśnienia trenera (co robi ruch, co było lepsze i dlaczego),
 - ``game`` — przebieg partii lub lekcji otwarcia.
"""
