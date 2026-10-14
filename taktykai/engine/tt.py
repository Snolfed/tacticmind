"""Tablica transpozycji (TT).

Ta sama pozycja często pojawia się w drzewie wiele razy (inna kolejność tych
samych ruchów = transpozycja). TT zapamiętuje dla pozycji (po haszu Zobrista):
głębokość, ocenę, typ oceny i najlepszy ruch. Przy ponownym spotkaniu pozycji
możemy od razu zwrócić wynik albo przynajmniej zacząć od najlepszego ruchu
(co poprawia cięcia alfa-beta).

Typ oceny wynika z alfa-bety:
 - EXACT: dokładna wartość (alfa < ocena < beta),
 - LOWER: ocena >= zapisanej (było cięcie beta),
 - UPPER: ocena <= zapisanej (żaden ruch nie poprawił alfy).
"""

from __future__ import annotations

TT_EXACT = 1
TT_LOWER = 2
TT_UPPER = 3


class TranspositionTable:
    """Słownik hasz → (głębokość, typ, ocena, ruch, wiek) z ograniczonym rozmiarem."""

    def __init__(self, max_entries: int = 400_000) -> None:
        self.max_entries = max_entries
        self.table: dict[int, tuple[int, int, int, int, int]] = {}
        self.age = 0

    def new_search(self) -> None:
        """Nowe wyszukiwanie: wpisy z poprzednich wyszukiwań można nadpisywać w pierwszej kolejności."""
        self.age = (self.age + 1) & 0xFF

    def clear(self) -> None:
        self.table.clear()

    def probe(self, key: int) -> tuple[int, int, int, int, int] | None:
        return self.table.get(key)

    def store(self, key: int, depth: int, flag: int, score: int, move: int) -> None:
        table = self.table
        old = table.get(key)
        if old is not None:
            # Głębszy wpis z bieżącego wyszukiwania jest cenniejszy — nie nadpisuj go płytszą granicą.
            if old[4] == self.age and old[0] > depth and flag != TT_EXACT:
                return
            if move == 0:
                move = old[3]  # nie gub najlepszego ruchu
        elif len(table) >= self.max_entries:
            # Prosta strategia przy przepełnieniu: wyrzuć wszystkie stare wpisy (albo wszystko).
            current = self.age
            stale = [k for k, v in table.items() if v[4] != current]
            if len(stale) > len(table) // 4:
                for k in stale:
                    del table[k]
            else:
                table.clear()
        table[key] = (depth, flag, score, move, self.age)

    def __len__(self) -> int:
        return len(self.table)
