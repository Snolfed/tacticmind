"""Haszowanie Zobrista.

Każdej kombinacji (figura, pole), stronie na ruchu, prawom do roszady i polu
en passant przypisujemy losową liczbę 64-bitową. Hasz pozycji to XOR liczb
opisujących jej elementy. Zaletą jest aktualizacja przyrostowa: wykonanie
ruchu to kilka operacji XOR zamiast liczenia hasza od nowa.
"""

import random

_rng = random.Random(0x7A6B5C4D)  # stałe ziarno = powtarzalne hasze


def _rand64() -> int:
    return _rng.getrandbits(64)


#: Klucze figur: indeks = kod_figury * 128 + pole_0x88.
PIECE_KEYS = [_rand64() for _ in range(16 * 128)]
#: Klucz strony na ruchu (XOR, gdy ruch mają czarne).
SIDE_KEY = _rand64()
#: Klucze praw do roszady (16 kombinacji 4 bitów).
CASTLE_KEYS = [_rand64() for _ in range(16)]
#: Klucze pola en passant (indeks = pole 0x88).
EP_KEYS = [_rand64() for _ in range(128)]
