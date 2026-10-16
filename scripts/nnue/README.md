# Trenowanie sieci NNUE dla TacticMind

Sieć w `tacticmind/engine/native/tacticmind.nnue` jest w całości wytrenowana w tym projekcie: na pozycjach z partii
silnika TacticMind z samym sobą. Nie korzystamy z cudzych sieci ani z ocen innych silników (Stockfish służy
wyłącznie jako przeciwnik w `scripts/match.py` do pomiaru siły).

## Architektura

```
768 cech (kolor × figura × pole) ──► 256 neuronów ─┐
     z perspektywy strony na ruchu                  ├─► SCReLU ─► 512 → 1 (ocena × 400 = centypiony)
768 cech z perspektywy przeciwnika ──► 256 neuronów ┘   (te same wagi pierwszej warstwy)
```

- **Akumulator** (pierwsza warstwa) jest aktualizowany przyrostowo: ruch zmienia 2–4 cechy, więc dodajemy
  i odejmujemy tylko 2–4 kolumny wag po 256 liczb zamiast liczyć 768 × 256 od zera (`position.c`, `nnue.c`).
- **SCReLU**: `clamp(x, 0, 1)²`.
- **Kubełki wyjścia**: 8 warstw wyjściowych, wybieranych według liczby figur na planszy (`(figury − 2) · 8 / 31`).
  Kompilacja trenera z `-DBUCKETS=1` daje jedną warstwę (stary format pliku, wersja 1).
- **Kwantyzacja**: wagi pierwszej warstwy × 255 (int16), wyjściowej × 64 — inferencja liczy tylko na liczbach całkowitych.

## Cykl uczenia (bootstrapping)

1. **Generacja 0** — partie z ręczną oceną (HCE), ok. 5000 węzłów na ruch, 8–9 losowych półruchów na start:
   ```bash
   python scripts/build_engine.py
   ./tacticmind/engine/native/build/tmengine datagen gen0.bin 10000 5000 1 hce   # plik, partie, węzły, ziarno, ocena
   ```
   Zapisujemy tylko spokojne pozycje (bez szacha, najlepszy ruch nie jest biciem) z oceną silnika i wynikiem partii.
   Kilka procesów z różnymi ziarnami = kilka rdzeni.
2. **Trening**:
   ```bash
   gcc -O3 -march=native -fopenmp scripts/nnue/train.c -o train -lm
   ./train -o net1.nnue -e 20 -l 1.0 gen0_*.bin
   ```
   Cel = `λ · sigmoid(ocena / 400) + (1 − λ) · wynik partii`, strata = błąd kwadratowy, optymalizator Adam.
   Na naszych danych najlepiej wypada λ = 1 (same oceny silnika): wyniki partii z losowym początkiem są zbyt
   przypadkowe. Pierwsza sieć uczona z λ = 1 wygrała z ręczną oceną 78:22 (+220 Elo), a z λ = 0,5 przegrała 12:88.
3. **Kolejne generacje** — dane z partii silnika już z nową siecią (`datagen gen1.bin … net1.nnue`), trening na
   nowych danych, mecz nowej sieci ze starą (`scripts/match.py`). Każda generacja ma lepsze oceny w danych, więc
   kolejna sieć jest mocniejsza.

## Historia sieci w repozytorium

| Generacja danych | Kto grał | Pozycje | Sieć |
|---|---|---:|---|
| 0 | ręczna ocena (HCE) | 2,2 mln | sieć 1 (+220 Elo względem HCE) |
| 1 | sieć 1 | 10,0 mln | sieć 2 (gen. 0–1, +193 względem sieci 1) |
| 2 | sieć 2 | 7,9 mln | sieć 3 (gen. 0–2, +76 względem sieci 2) |
| 3 | sieć 3 | 7,3 mln | **sieć 4** (gen. 0–3, kubełki, +30 względem sieci 3) — obecna |

Każda generacja: 4 procesy `datagen` po 5000 węzłów na ruch, ok. 700 pozycji/s razem. Trening sieci 4
(27,3 mln pozycji, 20 epok, 2 wątki): ok. 70 minut. Wyniki meczów i porównanie ze Stockfishem — w głównym README.
Sieć z 512 neuronami (te same dane co sieć 3) miała mniejszy błąd, ale w meczu na czas wypadła na remis
(−10 ± 40 Elo) — jest dwa razy wolniejsza. Przy znacznie większej liczbie danych warto spróbować ponownie.

Format rekordu danych (32 bajty): bitboard zajętości, kody figur po 4 bity, ocena z perspektywy białych (int16),
wynik (0 / 1 / 2 = wygrana czarnych / remis / wygrana białych), strona na ruchu.
